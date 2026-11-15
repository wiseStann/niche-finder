"""Buyer-voice metrics without an LLM: discussion volume by month, brand share of voice, intent markers.

Input: data/cache/arctic/<niche>_posts.jsonl / _comments.jsonl (s10_reddit_fetch), config/reddit_terms.yaml.
Output: data/out/reddit_voice.csv (per niche), reddit_brands.csv (per brand), reddit_monthly.csv (series).
Post trend uses native subreddits only (native=1; big ones are fetched for the last <= 100 pages and would distort the
series): the yearly average of the compare year / the yearly average of the base year (only when the base year has >= 60 posts),
and the last 12 months / the previous 12 (more than +20 % is UP, less than -20 % is DOWN, else FLAT). The base year is the
year of `history_start` in reddit_terms.yaml (2022 by default), the compare year is base + 2. The series ends at the last full
month before the run date (the archive can lag by weeks). Markers are counted over title+selftext of posts and body of
comments. Brands match on word boundaries and not after "/", otherwise "r/loseit" would count as the app Lose It.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from nichefinder.stages.s10_reddit_fetch import terms_config
from nichefinder.workspace import Workspace

SUMMARY = "Reddit buyer-voice metrics: volume trend, brand share of voice, intent markers"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

MARKERS = {
    "seek": r"\b(recommend|recommendation|looking for|any good|best app|which app|what app|suggest|is there an app|anyone use|anyone tried|worth trying)\b",
    "complain": r"\b(sucks|terrible|awful|annoying|buggy|bug|broken|hate|frustrat\w*|worst|garbage|useless|unusable|crash\w*|glitch\w*|ads everywhere|scam)\b",
    "switch": r"\b(switched|switching|moved from|moving from|alternative to|alternatives to|replace|replacement for|migrat\w*|left \w+ for|instead of)\b",
    "price": r"\b(expensive|too much money|price|pricing|subscription|paywall|worth it|worth the|free version|free alternative|premium|per month|per year|\$\d)\b",
}


def month(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m")


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")] if Path(path).exists() else []


def last_month(today: dt.date) -> str:
    """Last full month before the run date, as YYYY-MM."""
    return (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")


def windows(last: str) -> tuple[set, set]:
    """(last 12 months, previous 12 months) ending at `last`; 30-day steps, as month keys."""
    end = dt.date(int(last[:4]), int(last[5:]), 1)
    l12 = {(end - dt.timedelta(days=30 * i)).strftime("%Y-%m") for i in range(12)}
    p12 = {(end - dt.timedelta(days=30 * i)).strftime("%Y-%m") for i in range(12, 24)}
    return l12, p12


def series_metrics(native_posts, last, base_year):
    """Trend over native subreddits. A fetch is capped at 300 pages (30k posts) per subreddit, so a busy subreddit's series is
    truncated: it counts toward compare/base only if its earliest post is within a month of the base year start, and toward
    the 12/12 trend only if its earliest post is not later than the start of the previous 12-month window."""
    l12, p12 = windows(last)
    by_sub = defaultdict(list)
    for p in native_posts:
        by_sub[p["subreddit"]].append(month(p["created_utc"]))
    earliest = {sub: min(ms) for sub, ms in by_sub.items()}
    subs22 = [sub for sub, e in earliest.items() if e <= f"{base_year}-02"]
    subs24 = [sub for sub, e in earliest.items() if e <= min(p12)]
    mon22 = Counter(m for sub in subs22 for m in by_sub[sub])
    mon24 = Counter(m for sub in subs24 for m in by_sub[sub])
    m22 = sum(mon22.get(f"{base_year}-{m:02d}", 0) for m in range(1, 13)) / 12
    m24 = sum(mon22.get(f"{base_year + 2}-{m:02d}", 0) for m in range(1, 13)) / 12
    s_l, s_p = sum(v for m, v in mon24.items() if m in l12), sum(v for m, v in mon24.items() if m in p12)
    r_24_22 = round(m24 / m22, 2) if subs22 and m22 * 12 >= 60 else None
    yoy = round(s_l / s_p - 1, 2) if subs24 and s_p else None
    v = "NA"
    if yoy is not None and s_p >= 20:
        v = "UP" if yoy > 0.2 else ("DOWN" if yoy < -0.2 else "FLAT")
    elif by_sub and not subs24:
        v = "NA:short"
    return {"posts_2022": round(m22 * 12), "posts_2024": round(m24 * 12), "posts_last12": s_l, "posts_prev12": s_p, "r_24_22": r_24_22, "yoy": yoy, "verdict": v,
            "trend_subs": "|".join(f"{sub}:{e}" for sub, e in sorted(earliest.items()))}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg, st = terms_config(ws)
    base_year = int(str(st["history_start"])[:4])
    last = last_month(ws.today)
    l12, p12 = windows(last)
    cache = ws.cache("arctic")
    rows, brand_rows, monthly = [], [], []
    for nid, c in cfg.items():
        posts, comments = load(cache / f"{nid}_posts.jsonl"), load(cache / f"{nid}_comments.jsonl")
        if not posts and not comments:
            continue
        mon_p, mon_c = Counter(month(p["created_utc"]) for p in posts), Counter(month(x["created_utc"]) for x in comments)
        mon_n = Counter(month(p["created_utc"]) for p in posts if p.get("native"))
        for m in sorted(set(mon_p) | set(mon_c)):
            monthly.append({"niche_id": nid, "month": m, "posts": mon_p.get(m, 0), "posts_native": mon_n.get(m, 0), "comments": mon_c.get(m, 0)})
        sm = series_metrics([p for p in posts if p.get("native")], last, base_year)
        texts = [(p.get("title") or "") + " " + (p.get("selftext") or "") for p in posts] + [x.get("body") or "" for x in comments]
        low = [t.lower() for t in texts]
        marks = {k: sum(1 for t in low if re.search(rx, t)) for k, rx in MARKERS.items()}
        # brand share of voice: a document counts once per brand
        bcount, bcount_l12, bcount_p12 = Counter(), Counter(), Counter()
        docs = [(month(p["created_utc"]), (p.get("title") or "") + " " + (p.get("selftext") or "")) for p in posts] + [(month(x["created_utc"]), x.get("body") or "") for x in comments]
        brx = {b: re.compile(r"(?<![a-z0-9/])" + re.escape(b.lower()) + r"(?![a-z0-9])") for b in c.get("brands", [])}
        for m, t in docs:
            tl = t.lower()
            for b, rx in brx.items():
                if rx.search(tl):
                    bcount[b] += 1
                    if m in l12:
                        bcount_l12[b] += 1
                    elif m in p12:
                        bcount_p12[b] += 1
        tot = sum(bcount.values()) or 1
        top = bcount.most_common(3)
        hhi = round(sum((v / tot) ** 2 for v in bcount.values()), 3)
        for b, v in bcount.most_common():
            brand_rows.append({"niche_id": nid, "brand": b, "mentions": v, "share": round(v / tot, 3), "last12": bcount_l12[b], "prev12": bcount_p12[b],
                               "trend": round(bcount_l12[b] / bcount_p12[b] - 1, 2) if bcount_p12[b] >= 10 else ""})
        ndocs = len(docs) or 1
        rows.append({"niche_id": nid, "subs": "|".join(c["subs"]), "posts": len(posts), "comments": len(comments), **sm,
                     "comments_last12": sum(v for m, v in mon_c.items() if m in l12), "comments_prev12": sum(v for m, v in mon_c.items() if m in p12),
                     "seek": marks["seek"], "complain": marks["complain"], "switch": marks["switch"], "price": marks["price"],
                     "seek_share": round(marks["seek"] / ndocs, 3), "complain_share": round(marks["complain"] / ndocs, 3), "switch_share": round(marks["switch"] / ndocs, 3), "price_share": round(marks["price"] / ndocs, 3),
                     "brand_mentions": sum(bcount.values()), "brand_top1": top[0][0] if top else "", "brand_top1_share": round(top[0][1] / tot, 3) if top else "",
                     "brand_top3": " | ".join(f"{b} {v / tot:.0%}" for b, v in top), "brand_hhi": hhi, "brands_10plus": sum(1 for v in bcount.values() if v >= 10)})
        r = rows[-1]
        print(f"{nid:34} posts={r['posts']:5} com={r['comments']:5} 24/22={r['r_24_22']} yoy={r['yoy']} {r['verdict']:5} seek={r['seek_share']:.0%} complain={r['complain_share']:.0%} switch={r['switch_share']:.0%} price={r['price_share']:.0%} | {r['brand_top3']}")
    for name, data in (("reddit_voice.csv", rows), ("reddit_brands.csv", brand_rows), ("reddit_monthly.csv", monthly)):
        if data:
            with open(ws.out(name), "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(data[0].keys())); w.writeheader(); w.writerows(data)
    print("->", len(rows), "niches")
