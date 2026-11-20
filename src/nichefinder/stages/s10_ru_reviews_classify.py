"""Label Russian reviews (App Store, Google Play, Startpack) with an LLM: what each review is about, the pain it names,
switching, willingness to pay; then cluster the pains of each niche into themes.

Input: data/out/ru_reviews_docs.jsonl (s10_ru_reviews_fetch), config/ru_reviews.yaml (`sample`).
Sample per niche: reviews with at least `sample.min_chars` characters of text (shorter ones such as "Super!" name no
pain), at most `sample.max_reviews`, drawn round-robin over the niche's apps in a seeded random order. So the leader's
thousands of reviews do not drown the smaller apps, and a re-run draws the same sample and hits the LLM cache.
Each review gets: about (app = the software itself; service = the offline service or goods behind it, such as the salon,
the driver or the shop; off_topic), intent (bug, ux, missing_feature, pricing, ads, support, switching, praise, other),
pain, products, from_to, wtp and a verbatim quote. Shares are over reviews about the app:
  unmet_share   = missing_feature + pricing + switching   (what a new entrant could offer)
  quality_share = bug + ux + ads + support                 (the incumbents do the job badly)
Output: data/out/ru_reviews_items.jsonl (per review), ru_reviews_themes.json (per niche: pain themes with counts and
quotes, switches, intents per app), ru_reviews_llm.csv (per niche; top_app_share = the share of the sample's reviews about
the app that come from its largest product: when one product's review campaign dominates, the niche's voice is its voice). LLM as in s10_reddit_classify (LLM_API_KEY,
LLM_BASE_URL, LLM_MODEL; cached in data/cache/llm/). Cost: one call per 12 reviews plus one clustering call per niche;
--dry prints the sample sizes and a token estimate without any call.
Usage: nf run s10_ru_reviews_classify -- [--niches a,b] [--dry]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict

from nichefinder import llm, niches
from nichefinder.stages.s10_ru_reviews_fetch import DOCS, STORE_NAME, settings
from nichefinder.workspace import Workspace

SUMMARY = "LLM labels for Russian reviews: about, intent, pain, switching, willingness to pay"
KEYS: tuple[str, ...] = ("LLM_API_KEY",)
NEEDS: tuple[str, ...] = ()

BATCH = 12
INTENTS = ("bug", "ux", "missing_feature", "pricing", "ads", "support", "switching", "praise", "other")
UNMET = ("missing_feature", "pricing", "switching")
QUALITY = ("bug", "ux", "ads", "support")

SYSTEM = ("You label reviews (mostly in Russian) of apps and online services in a specific niche, from the App Store, Google Play and "
          "Startpack (a catalogue of business software where reviews come as pros, cons and text). For each item return strict JSON. Fields: "
          "i (item index); "
          "about (one of: app = about the app or service itself: features, bugs, design, price, ads, support; service = about the offline service or goods "
          "behind the app (a driver, a salon, a delivery, a shop, a bank branch), not about the software; off_topic = empty, spam or unintelligible); "
          "intent (for about=app one of: bug = crashes, errors, data loss, stopped working; ux = inconvenient or confusing to use, slow; "
          "missing_feature = asks for a feature or says the app lacks something the user needs; pricing = price, subscription, paywall, payment problems; "
          "ads = too many ads; support = support does not answer or does not help; switching = moved or plans to move to another app, or came from one; "
          "praise = happy with the app; other = about the app but none of the above. For about=service or off_topic use other). "
          "When a review mixes praise with a complaint or a request, the complaint or request wins; "
          "pain (for bug, ux, missing_feature, pricing, ads, support, switching: a short English phrase naming the unmet need or complaint from the "
          "user's perspective, e.g. 'no export to Excel' or 'subscription too expensive for basic features'; empty string otherwise); "
          "products (other apps or services named, normalized, lowercase; empty list if none); "
          "from_to (if the user switched or intends to switch: 'X -> Y' with app names, else empty string); "
          "wtp (one of: none, mentions_price, too_expensive, worth_it, wants_free, cancelled); "
          "quote (verbatim fragment up to 140 chars in the original language that best shows the pain or intent; empty if none). "
          "Output only a JSON object {\"items\": [...]}.")


def load_docs(ws: Workspace) -> dict[str, list[dict]]:
    p = ws.out(DOCS)
    by = defaultdict(list)
    if p.is_file():
        for line in open(p, encoding="utf-8"):
            d = json.loads(line)
            by[d["niche_id"]].append(d)
    return by


def sample(docs: list[dict], n: int, min_chars: int, seed: int = 7) -> list[dict]:
    """Round-robin over apps, each app's substantive reviews in a seeded random order; at most n."""
    by = defaultdict(list)
    for d in docs:
        if len(d.get("text") or "") >= min_chars:
            by[(d["store"], d["app_id"])].append(d)
    rnd = random.Random(seed)
    queues = []
    for key in sorted(by):
        q = sorted(by[key], key=lambda d: str(d["id"]))
        rnd.shuffle(q)
        queues.append(q)
    out: list[dict] = []
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop())
    return out


def review_block(j: int, d: dict) -> str:
    head = f"[{STORE_NAME.get(d['store'], d['store'])}, \"{d['app']}\", {d['rating']} stars]"
    body = (d.get("title") + ". " if d.get("title") else "") + (d.get("text") or "")
    return f"### item {j}\n{head}\n{body[:900]}"


def shares(recs: list[dict]) -> dict:
    """Intent shares over reviews about the app."""
    app = [r for r in recs if r["about"] == "app"]
    n = max(1, len(app))
    c = Counter(r["intent"] for r in app)
    out = {f"{k}_share": round(c.get(k, 0) / n, 3) for k in INTENTS}
    out["unmet_share"] = round(sum(c.get(k, 0) for k in UNMET) / n, 3)
    out["quality_share"] = round(sum(c.get(k, 0) for k in QUALITY) / n, 3)
    return {"about_app": len(app), **out}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: all in ru_reviews_docs.jsonl)")
    parser.add_argument("--dry", action="store_true", help="only draw the samples and estimate tokens; no LLM calls")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    by_niche = load_docs(ws)
    if not by_niche:
        print(f"{ws.out(DOCS)} is missing or empty - run s10_ru_reviews_fetch first")
        return
    st = settings(ws, "sample")
    names = niches.niche_names(ws)
    wanted = {x.strip() for x in args.niches.split(",") if x.strip()}
    items_out, themes, summary = [], {}, []
    usage = Counter()
    for nid, docs in by_niche.items():
        if wanted and nid not in wanted:
            continue
        sel = sample(docs, int(st["max_reviews"]), int(st["min_chars"]))
        apps = sorted({d["app"] for d in sel})
        est = sum(len(d["text"]) + len(d.get("title") or "") for d in sel) // 3
        print(f"{nid:36} reviews {len(docs)} -> sample {len(sel)} from {len(apps)} apps, ~{est // 1000}k tokens")
        if args.dry or not sel:
            continue
        recs = []
        for i in range(0, len(sel), BATCH):
            batch = sel[i:i + BATCH]
            user = (f"Niche: {names.get(nid, nid)} (id {nid}). Apps in this batch: {', '.join(sorted({d['app'] for d in batch}))}.\n\nItems:\n\n"
                    + "\n\n".join(review_block(j, d) for j, d in enumerate(batch)))
            content, cached, use = llm.chat_json(ws, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], max_tokens=3000)
            if not content:
                continue
            if use and not cached:
                usage["in"] += use.get("prompt_tokens", 0)
                usage["out"] += use.get("completion_tokens", 0)
            for it in content.get("items") or []:
                try:
                    d = batch[int(it.get("i"))]
                except (TypeError, ValueError, IndexError):
                    continue
                about = it.get("about") if it.get("about") in ("app", "service", "off_topic") else "app"
                intent = it.get("intent") if it.get("intent") in INTENTS else "other"
                rec = {"niche_id": nid, **{k: d[k] for k in ("store", "app_id", "app", "id", "date", "rating")},
                       "about": about, "intent": intent if about == "app" else "other",
                       "pain": (it.get("pain") or "").strip()[:200], "products": [str(p).lower() for p in (it.get("products") or [])][:8],
                       "from_to": (it.get("from_to") or "")[:120], "wtp": it.get("wtp", "none"), "quote": (it.get("quote") or "")[:160]}
                recs.append(rec)
                items_out.append(rec)
        sw = Counter()
        for r in recs:
            ft = [x.strip() for x in r["from_to"].lower().replace("→", "->").split("->")]
            if len(ft) == 2 and all(ft) and ft[0] != ft[1]:
                sw[f"{ft[0]} -> {ft[1]}"] += 1
        per_app = defaultdict(Counter)
        for r in recs:
            if r["about"] == "app":
                c = per_app[f"{r['store']}:{r['app']}"]
                c["n"] += 1
                c["unmet"] += r["intent"] in UNMET
                c["quality"] += r["intent"] in QUALITY
                c["praise"] += r["intent"] == "praise"
        t_out = {"themes": [], "switching": sw.most_common(15), "apps": {k: dict(v) for k, v in per_app.items()},
                 "intents": dict(Counter(r["intent"] for r in recs if r["about"] == "app")),
                 "about": dict(Counter(r["about"] for r in recs)), "wtp": dict(Counter(r["wtp"] for r in recs)), "n": len(recs)}
        pains = [r for r in recs if r["about"] == "app" and r["pain"] and r["intent"] in UNMET + QUALITY]
        if pains:
            user = (f"Niche: {names.get(nid, nid)}. Below are {len(pains)} pain statements extracted from Russian reviews (App Store, Google Play, "
                    "Startpack) of the niche's apps and services, one per line as 'k: [intent] pain | quote'. Group them into 6-12 themes (distinct unmet needs or complaints). "
                    "For each theme return: theme (short English name), kind (unmet = a missing feature, price or switching; quality = bugs, UX, ads or "
                    "support of existing apps), description (one sentence), count (number of statements in it), ids (list of k), "
                    "quotes (2 best verbatim quotes from the list). Output JSON {\"themes\": [...]}, sorted by count desc.\n\n"
                    + "\n".join(f"{k}: [{r['intent']}] {r['pain']} | {r['quote']}" for k, r in enumerate(pains)))
            content, cached, use = llm.chat_json(ws, [{"role": "system", "content": "You are a rigorous market researcher. Output only JSON."},
                                                      {"role": "user", "content": user}], max_tokens=4000)
            if content:
                if use and not cached:
                    usage["in"] += use.get("prompt_tokens", 0)
                    usage["out"] += use.get("completion_tokens", 0)
                t_out["themes"] = content.get("themes") or []
        themes[nid] = t_out
        sh = shares(recs)
        wtp = Counter(r["wtp"] for r in recs)
        top = t_out["themes"][0] if t_out["themes"] else {}
        top_app = max(per_app.items(), key=lambda kv: kv[1]["n"], default=("", Counter()))
        summary.append({"niche_id": nid, "sampled": len(sel), "classified": len(recs), "apps": len({r["app_id"] for r in recs if r["about"] == "app"}),
                        **sh, "app_share": round(sh["about_app"] / max(1, len(recs)), 3),
                        "top_app": top_app[0], "top_app_share": round(top_app[1]["n"] / max(1, sh["about_app"]), 3),
                        "too_expensive": wtp.get("too_expensive", 0), "worth_it": wtp.get("worth_it", 0), "wants_free": wtp.get("wants_free", 0),
                        "cancelled": wtp.get("cancelled", 0), "themes": len(t_out["themes"]), "top_theme": top.get("theme", ""),
                        "top_theme_kind": top.get("kind", ""), "top_theme_count": top.get("count", ""),
                        "top_switch": t_out["switching"][0][0] if t_out["switching"] else ""})
        s = summary[-1]
        print(f"   -> {s['classified']} labeled, about the app {s['about_app']}: unmet {s['unmet_share']:.0%} (feature {s['missing_feature_share']:.0%}, "
              f"price {s['pricing_share']:.0%}, switch {s['switching_share']:.0%}), quality {s['quality_share']:.0%}, praise {s['praise_share']:.0%} | "
              f"theme #1: {s['top_theme']} ({s['top_theme_count']})")
    if args.dry or not summary:
        return
    partial = bool(wanted)   # a partial run merges into the existing outputs
    ip = ws.out("ru_reviews_items.jsonl")
    done = {s["niche_id"] for s in summary}
    old_items = [json.loads(x) for x in open(ip, encoding="utf-8")] if partial and ip.is_file() else []
    with open(ip, "w", encoding="utf-8") as fh:
        for r in [x for x in old_items if x["niche_id"] not in done] + items_out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tp = ws.out("ru_reviews_themes.json")
    old = json.loads(tp.read_text(encoding="utf-8")) if partial and tp.is_file() else {}
    old.update(themes)
    tp.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    sp = ws.out("ru_reviews_llm.csv")
    prev = {r["niche_id"]: r for r in csv.DictReader(open(sp, encoding="utf-8"))} if partial and sp.is_file() else {}
    for s in summary:
        prev[s["niche_id"]] = s
    with open(sp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(prev.values())
    print(f"-> ru_reviews_items.jsonl, ru_reviews_themes.json, ru_reviews_llm.csv | tokens: {usage['in']} in / {usage['out']} out")
