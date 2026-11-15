"""Classify Reddit posts and comments by intent and pain with an LLM, then cluster pains into themes.

Input: data/cache/arctic/<niche>_posts.jsonl, _comments.jsonl (s10_reddit_fetch, s10_reddit_threads). Per niche, a sample of up to
MAX_POSTS posts and MAX_COMMENTS comments is drawn in tiers: (1) matched the niche terms (field `terms`: phrases, brands) AND have
a marker (question, "looking for", "alternative", "switched", "sucks", price); (2) matched terms; (3) marker only; (4) the rest,
at random. Without tiers the sample from a native subreddit (r/weightroom, r/Fitness) drowns in talk about programs and injuries
instead of software. The model marks documents that are not about software as off_topic; intent shares are computed over
documents about software only.

Output: data/out/reddit_voice_items.jsonl (per document: intent, pain, products, from->to, wtp, quote),
reddit_voice_themes.json (per niche: pain themes with counts and quotes, switching map), reddit_voice_llm.csv (per-niche summary).
LLM: any OpenAI-compatible chat endpoint through nichefinder.llm (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL). Responses are cached
in data/cache/llm/, so re-runs are free. The prompt needs plain JSON output, so turn model "thinking" off where the provider
supports it, e.g. LLM_EXTRA_BODY='{"thinking": {"type": "disabled"}}' for DeepSeek.
Cost: one call per 12 documents (up to 320 documents per niche) plus one clustering call per niche; --dry prints the sample sizes and a token estimate without any call.
Usage: nf run s10_reddit_classify -- [--niches a,b] [--dry]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter

from nichefinder import llm, niches
from nichefinder.stages.s10_reddit_fetch import terms_config
from nichefinder.stages.s10_reddit_threads import load
from nichefinder.workspace import Workspace

SUMMARY = "LLM classification of Reddit posts and comments: intent, pain, switching, willingness to pay"
KEYS: tuple[str, ...] = ("LLM_API_KEY",)
NEEDS: tuple[str, ...] = ()

MAX_POSTS, MAX_COMMENTS, BATCH = 160, 160, 12
PRIORITY = re.compile(r"\?|\b(recommend|looking for|any good|best app|which app|what app|suggest|alternative|alternatives|switched|switching|moved from|instead of|"
                      r"sucks|terrible|awful|annoying|buggy|broken|hate|frustrat\w*|worst|useless|cancel\w*|refund|expensive|price|pricing|subscription|paywall|worth it|free version|premium|wish|"
                      r"missing|lacks|doesn't have|does not have|can't|cannot|won't|unsubscrib\w*)\b", re.I)

SYSTEM = ("You classify Reddit posts and comments by whether and how they talk about SOFTWARE (apps, web services, tools) in a specific niche. "
          "For each item return strict JSON. Fields: i (item index), intent (one of: seeking_recommendation = asks which app/tool to use or for an alternative; complaint = unhappy with an app/tool; "
          "switching = moved or plans to move between apps/tools; pricing = discusses app price/subscription/paywall; praise = happy with an app/tool; howto = asks how to do something in an app/tool; "
          "news_or_promo = app maker promotion, release notes, moderator notice; other = about software but none of the above; off_topic = NOT about software/apps at all, e.g. training programs, recipes, travel tips, personal finance advice without tools), "
          "pain (only for software: short English phrase naming the unmet need or complaint about apps/tools from the user's perspective, e.g. 'sync loses data between devices' or 'no app tracks X'; empty string if none or off_topic), "
          "products (list of product/app names mentioned, normalized, lowercase; empty list if none), "
          "from_to (if the user switched or intends to switch: 'X -> Y' with product names, else empty string), "
          "wtp (one of: none, mentions_price, too_expensive, worth_it, wants_free, cancelled), "
          "quote (verbatim fragment up to 140 chars that best shows the pain or intent, in the original language; empty if none). "
          "Ignore moderator notices and promotional posts by app makers (mark intent news_or_promo). Output only a JSON object {\"items\": [...]}.")


def pick(items, text_of, n, brands_rx, seed=7):
    random.seed(seed)
    tiers = [[], [], [], []]
    for x in items:
        t = text_of(x)
        on = bool(x.get("terms")) or bool(brands_rx.search(t.lower()))
        pr = bool(PRIORITY.search(t))
        tiers[0 if on and pr else 1 if on else 2 if pr else 3].append(x)
    for tr in tiers:
        random.shuffle(tr)
    return [x for tr in tiers for x in tr][:n]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: all)")
    parser.add_argument("--dry", action="store_true", help="only draw the samples and estimate tokens; no LLM calls")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg, _ = terms_config(ws)
    cache = ws.cache("arctic")
    names = niches.niche_names(ws)
    items_out, themes, summary = [], {}, []
    usage = Counter()
    for nid, c in cfg.items():
        if args.niches and nid not in args.niches.split(","):
            continue
        posts, comments = load(cache / f"{nid}_posts.jsonl"), load(cache / f"{nid}_comments.jsonl")
        if not posts and not comments:
            continue
        brx = re.compile("|".join("(?<![a-z0-9])" + re.escape(b.lower()) + "(?![a-z0-9])" for b in c.get("brands", [])) or "$^")   # word boundaries: "liftin" would otherwise match "lifting" in every post
        sel_p = pick(posts, lambda p: (p.get("title") or "") + " " + (p.get("selftext") or ""), MAX_POSTS, brx)
        sel_c = pick(comments, lambda x: x.get("body") or "", MAX_COMMENTS, brx)
        docs = [{"id": p["id"], "kind": "post", "sub": p["subreddit"], "ts": p["created_utc"], "text": ((p.get("title") or "") + "\n" + (p.get("selftext") or ""))[:1400]} for p in sel_p] + \
               [{"id": x["id"], "kind": "comment", "sub": x["subreddit"], "ts": x["created_utc"], "text": (x.get("body") or "")[:900]} for x in sel_c]
        est_tokens = sum(len(d["text"]) for d in docs) // 3
        on_p, on_c = sum(1 for p in sel_p if p.get("terms")), sum(1 for x in sel_c if x.get("terms"))
        print(f"{nid:34} posts {len(posts)}->{len(sel_p)} (with terms {on_p}), comments {len(comments)}->{len(sel_c)} (with terms {on_c}), ~{est_tokens // 1000}k tokens")
        if args.dry:
            continue
        classified = []
        for i in range(0, len(docs), BATCH):
            batch = docs[i:i + BATCH]
            user = f"Niche: {names.get(nid, nid)} (id {nid}). Known products in this niche: {', '.join(c.get('brands', [])[:20])}.\n\nItems:\n" + \
                   "\n\n".join(f"### item {j}\n[{d['kind']} in r/{d['sub']}]\n{d['text']}" for j, d in enumerate(batch))
            content, cached, use = llm.chat_json(ws, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], max_tokens=3000)
            if not content:
                continue
            if use and not cached:
                usage["in"] += use.get("prompt_tokens", 0); usage["out"] += use.get("completion_tokens", 0)
            for it in (content.get("items") or []):
                try:
                    d = batch[int(it.get("i"))]
                except (TypeError, ValueError, IndexError):
                    continue
                rec = {"niche_id": nid, **{k: d[k] for k in ("id", "kind", "sub", "ts")}, "intent": it.get("intent", "other"), "pain": (it.get("pain") or "").strip()[:200],
                       "products": [str(p).lower() for p in (it.get("products") or [])][:8], "from_to": (it.get("from_to") or "")[:120], "wtp": it.get("wtp", "none"), "quote": (it.get("quote") or "")[:160]}
                classified.append(rec); items_out.append(rec)
        # pain themes: a second call clusters the pain statements
        pains = [r for r in classified if r["pain"] and r["intent"] in ("complaint", "seeking_recommendation", "switching", "pricing")]
        theme_out = {"themes": [], "switching": Counter(), "intents": Counter(r["intent"] for r in classified), "wtp": Counter(r["wtp"] for r in classified), "n": len(classified)}
        for r in classified:
            ft = [x.strip() for x in r["from_to"].lower().replace("→", "->").split("->")]
            if len(ft) == 2 and all(ft):
                theme_out["switching"][f"{ft[0]} -> {ft[1]}"] += 1
        if pains:
            user = (f"Niche: {names.get(nid, nid)}. Below are {len(pains)} pain statements extracted from Reddit posts/comments, one per line as 'k: pain | quote'. "
                    "Group them into 6-12 themes (distinct unmet needs or complaints). For each theme return: theme (short English name), description (one sentence), "
                    "count (number of statements in it), ids (list of k), quotes (2 best verbatim quotes from the list). Output JSON {\"themes\": [...]}, sorted by count desc.\n\n" +
                    "\n".join(f"{k}: {r['pain']} | {r['quote']}" for k, r in enumerate(pains)))
            content, cached, use = llm.chat_json(ws, [{"role": "system", "content": "You are a rigorous market researcher. Output only JSON."}, {"role": "user", "content": user}], max_tokens=4000)
            if content:
                if use and not cached:
                    usage["in"] += use.get("prompt_tokens", 0); usage["out"] += use.get("completion_tokens", 0)
                theme_out["themes"] = content.get("themes") or []
        theme_out["switching"] = theme_out["switching"].most_common(15)
        theme_out["intents"] = dict(theme_out["intents"]); theme_out["wtp"] = dict(theme_out["wtp"])
        themes[nid] = theme_out
        on_topic = [r for r in classified if r["intent"] != "off_topic"]
        n = max(1, len(on_topic))   # intent shares are over documents about software
        summary.append({"niche_id": nid, "classified": len(classified), "on_topic": len(on_topic), "on_topic_share": round(len(on_topic) / max(1, len(classified)), 3),
                        "seek_share": round(theme_out["intents"].get("seeking_recommendation", 0) / n, 3),
                        "complaint_share": round(theme_out["intents"].get("complaint", 0) / n, 3), "switching_share": round(theme_out["intents"].get("switching", 0) / n, 3),
                        "pricing_share": round(theme_out["intents"].get("pricing", 0) / n, 3), "praise_share": round(theme_out["intents"].get("praise", 0) / n, 3),
                        "too_expensive": theme_out["wtp"].get("too_expensive", 0), "worth_it": theme_out["wtp"].get("worth_it", 0), "wants_free": theme_out["wtp"].get("wants_free", 0), "cancelled": theme_out["wtp"].get("cancelled", 0),
                        "themes": len(theme_out["themes"]), "top_theme": (theme_out["themes"][0].get("theme") if theme_out["themes"] else ""),
                        "top_theme_count": (theme_out["themes"][0].get("count") if theme_out["themes"] else ""), "top_switch": (theme_out["switching"][0][0] if theme_out["switching"] else "")})
        s = summary[-1]
        print(f"   -> {s['classified']} classified, about software {s['on_topic']}: seek {s['seek_share']:.0%} complaint {s['complaint_share']:.0%} switch {s['switching_share']:.0%} price {s['pricing_share']:.0%} | theme #1: {s['top_theme']} ({s['top_theme_count']}) | {s['top_switch']}")
    if args.dry or not summary:
        return
    partial = bool(args.niches)   # a partial run merges into the existing outputs
    with open(ws.out("reddit_voice_items.jsonl"), "a" if partial else "w", encoding="utf-8") as fh:
        for r in items_out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tp = ws.out("reddit_voice_themes.json")
    old = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() and partial else {}
    old.update(themes)
    tp.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    sp = ws.out("reddit_voice_llm.csv")
    prev = {r["niche_id"]: r for r in csv.DictReader(open(sp, encoding="utf-8"))} if sp.exists() and partial else {}
    for s in summary:
        prev[s["niche_id"]] = s
    with open(sp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(prev.values())
    print(f"-> reddit_voice_items.jsonl, reddit_voice_themes.json, reddit_voice_llm.csv | tokens: {usage['in']} in / {usage['out']} out")
