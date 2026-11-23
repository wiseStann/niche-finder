"""Label Telegram chat messages (s10_tg_fetch) with an LLM: is the message about the niche, an advertisement or off
topic, which buyer signal it carries, the need it names and the products it mentions.

Input: data/out/tg_docs.jsonl, config/tg_voice.yaml (`sample`), niches.yaml (who, task, product).
Sample per niche: messages with at least `sample.min_chars` characters, repeated texts dropped (copy-paste ads), at
most `sample.max_messages`, drawn round-robin over the niche's chats in a seeded random order, so one busy chat does
not drown the others and a re-run draws the same sample and hits the LLM cache (the sampler of s10_yt_comments_classify).
Each message gets:
  about     niche = the task, its problem, or the products, services and tools for it (own experience or a question
            to peers); ad = an advertisement or self-promotion (a vendor, agency, freelancer, course or vacancy);
            off_topic = small talk, greetings, chat rules, politics, another trade, unintelligible
  kind      for about=niche: pain, unmet_need, price, product_request, question, praise, other (the kinds and their
            rules are those of the YouTube comments, so the two sources compare)
  pain      a short English phrase naming the need, for pain, unmet_need, price and product_request
  products  products, apps, services and brands named
Shares are over messages about the niche, as for YouTube comments: unmet_share = unmet_need + price, pain_share,
product_request_share, question_share; about_ad counts the advertisements (vendor pressure in the chats).
Output: data/out/tg_items.jsonl (per message), tg_llm.csv (per niche; niche_chats = chats with at least one message
about the niche, top_chat_share = the share of the niche's messages about the niche from its largest chat,
failed_batches = LLM calls without an answer: the report leaves such a niche out as "incomplete" until a re-run).
LLM as in s10_reddit_classify (LLM_API_KEY; cached in data/cache/llm/). One call per 25 messages, --workers at a time;
--dry prints the sample sizes and a token estimate without any call.
Usage: nf run s10_tg_classify -- [--niches a,b] [--dry] [--workers 6]
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from nichefinder import llm, niches
from nichefinder.stages.s10_tg_fetch import DOCS, settings
from nichefinder.stages.s10_yt_comments_classify import KINDS, VOICE, label_rules, sample, shares
from nichefinder.stages.s10_yt_comments_fetch import read_rows
from nichefinder.workspace import Workspace

SUMMARY = "LLM labels for Telegram chat messages: about the niche or an ad, pain, unmet need, price, product request, question, praise"
KEYS: tuple[str, ...] = ("LLM_API_KEY",)
NEEDS: tuple[str, ...] = ()

BATCH = 25
ABOUT = ("niche", "ad", "off_topic")
LLM_COLS = ["niche_id", "chats", "messages", "sampled", "classified", "about_niche", "about_ad", "off_topic", "niche_share",
            *[f"{k}_share" for k in KINDS], "unmet_share", "voice_share", "niche_chats", "top_chat", "top_chat_share", "products",
            "failed_batches"]

SYSTEM = (
    "You label messages (mostly in Russian) from public Telegram group chats where a market niche's users talk among themselves: "
    "owners and practitioners of a trade, or the users of its tools. A niche is who x task x product. For each message return "
    "strict JSON with the fields: "
    "i (item index); "
    "about (niche = the author speaks about the niche's task, its problem, or the products, services and tools for it, including "
    "their own experience or a question to peers; ad = an advertisement or self-promotion: a vendor, agency, freelancer or the "
    "author offers a product, service, course, job or vacancy; off_topic = anything else: small talk, greetings, chat rules, "
    "politics, another trade, unintelligible); "
    + label_rules("ad"))


def load_docs(ws: Workspace) -> dict[str, list[dict]]:
    by = defaultdict(list)
    for d in read_rows(ws.out(DOCS)):
        by[d["niche_id"]].append(d)
    return by


def batch_prompt(niche: dict, batch: list[dict]) -> str:
    chats = list(dict.fromkeys(d["chat_id"] for d in batch))
    tag = {c: chr(65 + k) if k < 26 else f"C{k}" for k, c in enumerate(chats)}
    first = {d["chat_id"]: d for d in reversed(batch)}
    legend = "\n".join(f"{tag[c]} = \"{first[c]['chat'][:100]}\" ({first[c]['members']} members)" for c in chats)
    items = "\n\n".join(f"### item {j} [chat {tag[d['chat_id']]}{', a reply' if d.get('reply') else ''}{', forwarded' if d.get('fwd') else ''}]"
                        f"\n{d['text'][:500]}" for j, d in enumerate(batch))
    return (f"Niche: {niche.get('name') or niche.get('id', '')}\nWho: {niche.get('who', '')}\nTask: {niche.get('task', '')}\n"
            f"Product: {niche.get('product', '')}\n\nChats:\n{legend}\n\nMessages:\n\n{items}")


def label(it: dict, d: dict, nid: str) -> dict:
    about = it.get("about") if it.get("about") in ABOUT else "off_topic"
    kind = it.get("kind") if it.get("kind") in KINDS and about == "niche" else "other"
    return {"niche_id": nid, "chat_id": d["chat_id"], "id": d["id"], "date": d.get("date", ""), "about": about, "kind": kind,
            "pain": (it.get("pain") or "").strip()[:200] if kind in VOICE else "",
            "products": [str(p).lower().strip() for p in (it.get("products") or []) if str(p).strip()][:8],
            "text": (d.get("text") or "")[:300]}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: all in tg_docs.jsonl)")
    parser.add_argument("--dry", action="store_true", help="only draw the samples and estimate tokens; no LLM calls")
    parser.add_argument("--workers", type=int, default=6, help="parallel LLM calls")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    by_niche = load_docs(ws)
    if not by_niche:
        print(f"{ws.out(DOCS)} is missing or empty - run s10_tg_fetch first")
        return
    st = settings(ws, "sample")
    by_id = {n["id"]: n for n in niches.load_niches(ws)}
    wanted = {x.strip() for x in (getattr(args, "niches", "") or "").split(",") if x.strip()}
    jobs: list[tuple[str, list[dict]]] = []
    sampled: dict[str, int] = {}
    for nid, docs in by_niche.items():
        if wanted and nid not in wanted:
            continue
        sel = sample(docs, int(st["max_messages"]), int(st["min_chars"]), group="chat_id")
        sampled[nid] = len(sel)
        est = sum(min(len(d["text"]), 500) for d in sel) // 3
        print(f"{nid:36} messages {len(docs)} from {len({d['chat_id'] for d in docs})} chats -> sample {len(sel)}, ~{est // 1000}k tokens")
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
        s = {"niche_id": nid, "chats": len({d["chat_id"] for d in docs}), "messages": len(docs), "sampled": sampled[nid],
             **shares(recs, group="chat_id", unit="chat", other="ad"), "failed_batches": failed[nid]}
        summary.append(s)
        print(f"   {nid:36} {s['classified']} labeled, about the niche {s['about_niche']} ({s['niche_share']:.0%}), ads {s['about_ad']}: "
              f"unmet {s['unmet_share']:.0%}, pain {s['pain_share']:.0%}, asks for a product {s['product_request_share']:.0%}, "
              f"how-to {s['question_share']:.0%}, praise {s['praise_share']:.0%}" + (f" | {failed[nid]} batches without an answer" if failed[nid] else ""))
    partial = bool(wanted)   # a partial run merges into the existing outputs
    done = set(sampled)
    ip = ws.out("tg_items.jsonl")
    old_items = [r for r in read_rows(ip) if r["niche_id"] not in done] if partial else []
    with open(ip, "w", encoding="utf-8") as fh:
        for r in old_items + [r for nid in sampled for r in recs_by.get(nid, [])]:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    sp = ws.out("tg_llm.csv")
    prev = {r["niche_id"]: r for r in read_rows(sp)} if partial else {}
    for s in summary:
        prev[s["niche_id"]] = s
    with open(sp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LLM_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(prev.values())
    print(f"-> {ip.name}, {sp.name}: {len(summary)} niches | tokens: {usage['in']} in / {usage['out']} out"
          + (f" | {sum(failed.values())} batches without an answer: re-run to retry" if failed else ""))
