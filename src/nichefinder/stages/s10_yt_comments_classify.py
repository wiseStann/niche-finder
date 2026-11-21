"""Label YouTube comments (s10_yt_comments_fetch) with an LLM: is the comment about the niche, which buyer signal it
carries, the need it names and the products it mentions.

Input: data/out/yt_comments_docs.jsonl, config/yt_comments.yaml (`sample`), niches.yaml (who, task, product).
Sample per niche: comments with at least `sample.min_chars` characters (shorter ones such as "Thanks!" name no need),
repeated texts dropped (bots, copy-paste), at most `sample.max_comments`, drawn round-robin over the niche's videos in
a seeded random order. So one viral video does not drown the others, and a re-run draws the same sample and hits the
LLM cache.
Each comment gets:
  about     niche = the task, its problem, or the products and tools for it (the commenter's own experience counts);
            video = only a reaction to the video or its author (thanks, compliments, critique of the presenter);
            off_topic = jokes, politics, spam, self-promotion, unintelligible
  kind      for about=niche: pain, unmet_need, price, product_request, question, praise, other (see SYSTEM)
  pain      a short English phrase naming the need, for pain, unmet_need, price and product_request
  products  products, apps, services and brands named
Shares are over comments about the niche:
  unmet_share    = unmet_need + price    (what a new product could answer: something missing, a price objection)
  pain_share     = pain                  (the task or the existing tools hurt)
  product_request_share                  (buyers ask which product to use: they compare, they do not flee)
  question_share = question              (how-to questions: demand for know-how, the info cohort's signal)
  voice_share    = pain + unmet_need + price + product_request
Output (with --lang en the names end in _en): data/out/yt_comments_items.jsonl (per comment), yt_comments_llm.csv (per
niche; niche_videos = videos with at least one comment about the niche, top_video_share = the share of the niche's
comments about the niche that come from its largest video, products = the products named most often, failed_batches =
LLM calls without an answer: the report leaves such a niche out of the verdict as "incomplete" until a re-run, which
pays only for the missing batches, fills it).
LLM as in s10_reddit_classify (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL; cached in data/cache/llm/). Cost: one call per 25
comments, run --workers at a time; --dry prints the sample sizes and a token estimate without any call.
Usage: nf run s10_yt_comments_classify -- [--lang ru|en] [--niches a,b] [--dry] [--workers 6]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from nichefinder import llm, niches
from nichefinder.stages.s10_yt_comments_fetch import DOCS, lang_of, out_name, read_rows, settings
from nichefinder.workspace import Workspace

SUMMARY = "LLM labels for YouTube comments: about the niche, pain, unmet need, price, product request, question, praise"
KEYS: tuple[str, ...] = ("LLM_API_KEY",)
NEEDS: tuple[str, ...] = ()

BATCH = 25
ABOUT = ("niche", "video", "off_topic")
KINDS = ("pain", "unmet_need", "price", "product_request", "question", "praise", "other")
UNMET = ("unmet_need", "price")
VOICE = ("pain", "unmet_need", "price", "product_request")
LLM_COLS = ["niche_id", "lang", "videos", "comments", "sampled", "classified", "about_niche", "about_video", "off_topic", "niche_share",
            *[f"{k}_share" for k in KINDS], "unmet_share", "voice_share", "niche_videos", "top_video", "top_video_share", "products",
            "failed_batches"]

SYSTEM = (
    "You label YouTube comments (mostly in Russian) left under videos about a market niche: how-to videos for its task and reviews "
    "of its products. A niche is who x task x product. For each comment return strict JSON with the fields: "
    "i (item index); "
    "about (niche = the commenter speaks about the niche's task, its problem, or the products and tools for it, including their own "
    "experience; video = only a reaction to the video or its author: thanks, compliments, critique of the presenter or the editing; "
    "off_topic = anything else: jokes, politics, spam, self-promotion, links, unintelligible); "
    "kind (for about=niche one of: pain = a complaint or difficulty: the task is hard, a product or tool fails, is inconvenient, buggy, "
    "blocked or gone, support does not help; unmet_need = names something missing: wishes for a product, feature or option the tools "
    "they know lack, or says there is no good tool for it; price = price, subscription, paywall, too expensive, wants a free option, "
    "cancelled over price; product_request = asks which product, app, service or tool to use, or for a recommendation; "
    "question = asks how to do the task or how to use a product, not which product to choose; praise = satisfied with a product, a "
    "tool or their current way of doing the task, or recommends one; other = about the niche but none of the above: a story, an "
    "opinion, advice without a product. For about=video or off_topic use other. When a comment mixes kinds, the first of this "
    "order wins: unmet_need, price, pain, product_request, question, praise, other); "
    "pain (for pain, unmet_need, price and product_request: a short English phrase naming the need from the commenter's "
    "perspective, e.g. 'no app tracks supersets', 'subscription too expensive', 'looking for a simple offline budget app'; "
    "empty string otherwise); "
    "products (products, apps, services, tools or brands named, normalized, lowercase; empty list if none). "
    'Output only a JSON object {"items": [...]}.')


def load_docs(ws: Workspace, lang: str) -> dict[str, list[dict]]:
    by = defaultdict(list)
    for d in read_rows(ws.out(out_name(DOCS, lang))):
        by[d["niche_id"]].append(d)
    return by


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def sample(docs: list[dict], n: int, min_chars: int, seed: int = 7) -> list[dict]:
    """Round-robin over videos, each video's substantive comments in a seeded random order, repeated texts dropped; at
    most n."""
    by = defaultdict(list)
    seen: set[str] = set()
    for d in sorted(docs, key=lambda d: (d["video_id"], str(d["id"]))):
        t = norm(d.get("text") or "")
        if len(d.get("text") or "") < min_chars or t in seen:
            continue
        seen.add(t)
        by[d["video_id"]].append(d)
    rnd = random.Random(seed)
    queues = []
    for vid in sorted(by):
        q = list(by[vid])
        rnd.shuffle(q)
        queues.append(q)
    out: list[dict] = []
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop())
    return out


def batch_prompt(niche: dict, batch: list[dict]) -> str:
    vids = list(dict.fromkeys(d["video_id"] for d in batch))
    tag = {v: chr(65 + k) if k < 26 else f"V{k}" for k, v in enumerate(vids)}
    first = {d["video_id"]: d for d in reversed(batch)}
    legend = "\n".join(f"{tag[v]} = \"{first[v]['video'][:100]}\" ({first[v]['channel'][:40]})" for v in vids)
    items = "\n\n".join(f"### item {j} [video {tag[d['video_id']]}]\n{d['text'][:500]}" for j, d in enumerate(batch))
    return (f"Niche: {niche.get('name') or niche.get('id', '')}\nWho: {niche.get('who', '')}\nTask: {niche.get('task', '')}\n"
            f"Product: {niche.get('product', '')}\n\nVideos:\n{legend}\n\nComments:\n\n{items}")


def label(it: dict, d: dict, nid: str) -> dict:
    about = it.get("about") if it.get("about") in ABOUT else "off_topic"
    kind = it.get("kind") if it.get("kind") in KINDS and about == "niche" else "other"
    return {"niche_id": nid, "video_id": d["video_id"], "id": d["id"], "date": d.get("date", ""), "likes": d.get("likes", 0),
            "about": about, "kind": kind, "pain": (it.get("pain") or "").strip()[:200] if kind in VOICE else "",
            "products": [str(p).lower().strip() for p in (it.get("products") or []) if str(p).strip()][:8],
            "text": (d.get("text") or "")[:300]}


def shares(recs: list[dict]) -> dict:
    """Kind shares over comments about the niche, plus the about split, videos and products."""
    nic = [r for r in recs if r["about"] == "niche"]
    n = max(1, len(nic))
    c = Counter(r["kind"] for r in nic)
    per_video = Counter(r["video_id"] for r in nic)
    top = per_video.most_common(1)[0] if per_video else ("", 0)
    prods = Counter(p for r in nic for p in dict.fromkeys(r["products"]))
    ab = Counter(r["about"] for r in recs)
    return {"classified": len(recs), "about_niche": len(nic), "about_video": ab.get("video", 0), "off_topic": ab.get("off_topic", 0),
            "niche_share": round(len(nic) / max(1, len(recs)), 3),
            **{f"{k}_share": round(c.get(k, 0) / n, 3) for k in KINDS},
            "unmet_share": round(sum(c.get(k, 0) for k in UNMET) / n, 3),
            "voice_share": round(sum(c.get(k, 0) for k in VOICE) / n, 3),
            "niche_videos": len(per_video), "top_video": top[0], "top_video_share": round(top[1] / n, 3) if nic else 0,
            "products": "; ".join(f"{p} ({k})" for p, k in prods.most_common(8))}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lang", default="", choices=["", "ru", "en"], help="ru (default when nf.yaml markets include ru) or en")
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: all in yt_comments_docs.jsonl)")
    parser.add_argument("--dry", action="store_true", help="only draw the samples and estimate tokens; no LLM calls")
    parser.add_argument("--workers", type=int, default=6, help="parallel LLM calls")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    lang = lang_of(ws, args)
    by_niche = load_docs(ws, lang)
    if not by_niche:
        print(f"{ws.out(out_name(DOCS, lang))} is missing or empty - run s10_yt_comments_fetch first")
        return
    st = settings(ws, "sample")
    by_id = {n["id"]: n for n in niches.load_niches(ws)}
    wanted = {x.strip() for x in (getattr(args, "niches", "") or "").split(",") if x.strip()}
    jobs: list[tuple[str, list[dict]]] = []
    sampled: dict[str, int] = {}
    for nid, docs in by_niche.items():
        if wanted and nid not in wanted:
            continue
        sel = sample(docs, int(st["max_comments"]), int(st["min_chars"]))
        sampled[nid] = len(sel)
        est = sum(min(len(d["text"]), 500) for d in sel) // 3
        print(f"{nid:36} comments {len(docs)} from {len({d['video_id'] for d in docs})} videos -> sample {len(sel)}, ~{est // 1000}k tokens")
        jobs += [(nid, sel[i:i + BATCH]) for i in range(0, len(sel), BATCH)]
    if getattr(args, "dry", False) or not jobs:
        return
    usage = Counter()

    def call(job):
        nid, batch = job
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": batch_prompt(by_id.get(nid, {"id": nid}), batch)}]
        return llm.chat_json(ws, msgs, max_tokens=4000)

    with ThreadPoolExecutor(max_workers=max(1, int(getattr(args, "workers", 6) or 1))) as ex:
        results = list(ex.map(call, jobs))
    recs_by = defaultdict(list)
    failed = Counter()
    for (nid, batch), (content, cached, use) in zip(jobs, results):
        if not content:
            failed[nid] += 1
            continue
        if use and not cached:
            usage["in"] += use.get("prompt_tokens", 0)
            usage["out"] += use.get("completion_tokens", 0)
        for it in content.get("items") or []:
            try:
                d = batch[int(it.get("i"))]
            except (TypeError, ValueError, IndexError):
                continue
            recs_by[nid].append(label(it, d, nid))
    summary = []
    for nid in sampled:
        recs = recs_by.get(nid, [])
        docs = by_niche[nid]
        s = {"niche_id": nid, "lang": lang, "videos": len({d["video_id"] for d in docs}), "comments": len(docs), "sampled": sampled[nid], **shares(recs),
             "failed_batches": failed[nid]}
        summary.append(s)
        print(f"   {nid:36} {s['classified']} labeled, about the niche {s['about_niche']} ({s['niche_share']:.0%}): unmet {s['unmet_share']:.0%}, "
              f"pain {s['pain_share']:.0%}, asks for a product {s['product_request_share']:.0%}, how-to {s['question_share']:.0%}, "
              f"praise {s['praise_share']:.0%}" + (f" | {failed[nid]} batches without an answer" if failed[nid] else ""))
    partial = bool(wanted)   # a partial run merges into the existing outputs
    done = set(sampled)
    ip = ws.out(out_name("yt_comments_items.jsonl", lang))
    old_items = [r for r in read_rows(ip) if r["niche_id"] not in done] if partial else []
    with open(ip, "w", encoding="utf-8") as fh:
        for r in old_items + [r for nid in sampled for r in recs_by.get(nid, [])]:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    sp = ws.out(out_name("yt_comments_llm.csv", lang))
    prev = {r["niche_id"]: r for r in read_rows(sp)} if partial else {}
    for s in summary:
        prev[s["niche_id"]] = s
    with open(sp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LLM_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(prev.values())
    print(f"-> {ip.name}, {sp.name}: {len(summary)} niches | tokens: {usage['in']} in / {usage['out']} out"
          + (f" | {sum(failed.values())} batches without an answer: re-run to retry" if failed else ""))
