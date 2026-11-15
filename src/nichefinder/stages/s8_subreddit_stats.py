"""Size and activity of each niche's subreddits (config/reddit_map.yaml), from subredditstats.com.

Reddit's own pages and API refuse scripts without OAuth, so the source is subredditstats.com: a snapshot of
subscriberCount, commentsPerHour, postsPerHour and ranks. It is a comparison of community sizes, not current
growth. The snapshot label written to the CSV comes from `_settings.snapshot` in the config (default 2023-12).

Input: config/reddit_map.yaml (niche id -> [subreddits], the first one is the primary community).
Output: data/out/reddit_subs.csv (per subreddit) and data/out/reddit_niche.csv (primary + sum per niche).
Cache: data/cache/reddit/<subreddit>.json. Cost: free, no key.
"""
from __future__ import annotations

import argparse
import csv
import json
import time

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Subreddit sizes per niche (subredditstats.com)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

FIELDS = ("name", "subscriberCount", "commentsPerHour", "postsPerHour", "subscriberCountRank",
          "lastSubscriberCountCheck", "creationTime", "isActiveSubreddit", "title")


def fetch(cache, sub):
    path = cache / f"{sub.lower()}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(3):
        try:
            r = http.request(f"https://subredditstats.com/api/subreddit?name={sub}", user_agent="Mozilla/5.0 niche-finder",
                             timeout=25, tries=1, raise_for_status=False)
            d = json.loads(r.text)
            if isinstance(d, dict) and "subscriberCount" in d:
                path.write_text(json.dumps({k: d.get(k) for k in FIELDS}), encoding="utf-8")
                time.sleep(0.7)
                return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
        time.sleep(3 * (attempt + 1))
    path.write_text(json.dumps({"name": sub, "subscriberCount": None}), encoding="utf-8")
    return {"name": sub, "subscriberCount": None}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    smap = dict(ws.load_config("reddit_map.yaml"))
    snapshot = str((smap.pop("_settings", None) or {}).get("snapshot", "2023-12"))
    cache = ws.cache("reddit")
    rows, agg = [], []
    for nid, subs in smap.items():
        got = []
        for i, sub in enumerate(subs):
            d = fetch(cache, sub)
            rows.append({"niche_id": nid, "subreddit": sub, "primary": int(i == 0), "subscribers": d.get("subscriberCount") or "",
                         "comments_per_hour": d.get("commentsPerHour") or "", "posts_per_hour": d.get("postsPerHour") or "", "rank": d.get("subscriberCountRank") or ""})
            if d.get("subscriberCount"):
                got.append((sub, d["subscriberCount"], d.get("commentsPerHour") or 0))
        prim = got[0] if got and got[0][0] == subs[0] else (got[0] if got else None)
        agg.append({"niche_id": nid, "subs_found": len(got), "primary_sub": prim[0] if prim else "", "primary_subscribers": prim[1] if prim else "",
                    "primary_comments_ph": round(prim[2], 2) if prim else "", "sum_subscribers": sum(x[1] for x in got), "snapshot": snapshot})
        print(f"{nid:36} {agg[-1]['primary_sub']:22} {agg[-1]['primary_subscribers']:>9} subscribers, {agg[-1]['primary_comments_ph']:>6} comments/h | total {agg[-1]['sum_subscribers']:>9}", flush=True)
    for name, data in (("reddit_subs.csv", rows), ("reddit_niche.csv", agg)):
        with open(ws.out(name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
    print("-> reddit_subs.csv", len(rows), "| reddit_niche.csv", len(agg))
