"""YouTube search interest (Google Trends, gprop=youtube) for each shortlisted niche, US.

Google Trends indexes are relative within one query, so every topic is requested together with a reference
topic (`ref`): level = mean(topic) / mean(ref) over the last year. The trend is the last year versus two years
earlier (yt_r_24_22 in the default window). Topics are subject phrases, not product phrases: people search
YouTube for "meal prep", not for "recipe app". B2B topics are usually near zero and come out as NA.

Input: shortlist, config/youtube_topics.yaml (niche id -> topic phrase; optional `_settings: {ref, last_year}`).
Output: data/out/youtube_trends.csv. Cache: data/cache/trends_yt/. Cost: free (unofficial Google Trends client,
rate-limited: about 12 s per new request).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time

from nichefinder import niches
from nichefinder.workspace import Workspace

SUMMARY = "YouTube search interest per niche topic (Google Trends, gprop=youtube)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("trendspy",)

DEFAULT_REF = "budgeting"   # mid-level reference topic: level 1.0


def fetch(tr, cache, words, geo, timeframe):
    key = "__".join(w.replace(" ", "_") for w in words)
    path = cache / f"{geo}__{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(4):
        try:
            df = tr.interest_over_time(words, timeframe=timeframe, geo=geo, gprop="youtube")
            data = {"dates": [str(d)[:10] for d in df.index.tolist()], **{w: [int(x) for x in df[w].tolist()] for w in words}}
            path.write_text(json.dumps(data), encoding="utf-8")
            time.sleep(12)
            return data
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"  retry {attempt + 1} {words}: {type(e).__name__} {str(e)[:80]}\n")
            time.sleep(45 * (attempt + 1))
    return None


def yearly(dates, v):
    by = {}
    for d, x in zip(dates, v):
        by.setdefault(d[:4], []).append(x)
    return {y: sum(xs) / len(xs) for y, xs in by.items() if len(xs) >= 40}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    from trendspy import Trends
    ids = niches.shortlist_ids(ws)
    topics = dict(ws.load_config("youtube_topics.yaml"))
    settings = topics.pop("_settings", None) or {}
    ref = settings.get("ref") or DEFAULT_REF
    last = int(settings.get("last_year") or ws.today.year - 1)   # last full calendar year of the window
    y0, y1, y2 = str(last), str(last - 2), str(last - 3)
    timeframe = f"{y2}-01-01 {y0}-12-31"
    years = [str(last - 3 + i) for i in range(4)]
    suf = f"{y0[2:]}_{y1[2:]}"
    cache = ws.cache("trends_yt")
    tr = Trends()
    rows = []
    for nid in ids:
        anchor = topics.get(nid)
        if not anchor:
            print("  !! no topic for", nid)
            continue
        data = fetch(tr, cache, [ref, anchor], "US", timeframe)
        if not data:
            rows.append({"niche_id": nid, "anchor": anchor, "status": "FAILED"})
            continue
        ya, yr = yearly(data["dates"], data[anchor]), yearly(data["dates"], data[ref])
        lvl = (ya.get(y0, 0) / yr[y0]) if yr.get(y0) else None
        r = (ya[y0] / ya[y1] - 1) if ya.get(y1) else None
        if ya.get(y0, 0) < 2 and lvl is not None and lvl < 0.03:
            verdict = "NA"
        elif r is None:
            verdict = "UP" if ya.get(y0, 0) >= 5 and ya.get(y1, 0) == 0 else "NA"
        else:
            verdict = "UP" if r >= 0.15 else ("DOWN" if r <= -0.15 else "FLAT")
        row = {"niche_id": nid, "anchor": anchor, "status": "ok", "ref": ref}
        for y in years:
            row[f"yt_{y}"] = round(ya.get(y, 0), 1)
        row[f"yt_level_vs_ref_{y0}"] = round(lvl, 3) if lvl is not None else ""
        row[f"yt_r_{suf}"] = round(r, 3) if r is not None else ""
        row["yt_verdict"] = verdict
        rows.append(row)
        print(f"{nid:36} {anchor[:34]:34} " + " ".join(f"{y[2:]}={ya.get(y, 0):.0f}" for y in years)
              + f" lvl={lvl if lvl is None else round(lvl, 2)} -> {verdict}", flush=True)
    out = ws.out("youtube_trends.csv")
    cols = (["niche_id", "anchor", "status", "ref"] + [f"yt_{y}" for y in years]
            + [f"yt_level_vs_ref_{y0}", f"yt_r_{suf}", "yt_verdict"])
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    print("->", out, len(rows))
