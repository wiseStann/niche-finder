"""Comments under matched posts of big subreddits (Arctic Shift, comments/search?link_id=).

s10_reddit_fetch keeps only term-matching posts for big subreddits and skips their comments (thousands per day). Yet the
threads under "which app do you use?" are the densest buyer voice. This stage adds them: per niche, up to MAX_THREADS matched
posts from big subreddits with at least MIN_COMMENTS comments (by descending num_comments) have their comments fetched (up to
MAX_PAGES pages of 100). Rows are appended to <niche>_comments.jsonl with native=0, thread=1 and `terms` (local match);
idempotent by id. Run after s10_reddit_fetch.
Usage: nf run s10_reddit_threads -- [--niches a,b]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from nichefinder.stages.s10_reddit_fetch import COMM_FIELDS, get, stats, terms_config
from nichefinder.workspace import Workspace

SUMMARY = "Comment threads under matched posts of big subreddits"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

MAX_THREADS, MIN_COMMENTS, MAX_PAGES = 120, 3, 3


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")] if Path(path).exists() else []


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: all)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg, _ = terms_config(ws)
    cache = ws.cache("arctic")
    for nid, c in cfg.items():
        if args.niches and nid not in args.niches.split(","):
            continue
        cp = cache / f"{nid}_comments.jsonl"
        posts = load(cache / f"{nid}_posts.jsonl")
        if not posts:
            continue
        terms_rx = {t: re.compile(r"(?<![a-z0-9])" + re.escape(t.lower()) + r"(?![a-z0-9])") for t in c["terms"]}
        comments = {x["id"]: x for x in load(cp)}
        n0 = len(comments)
        cand = sorted((p for p in posts if not p.get("native") and (p.get("num_comments") or 0) >= MIN_COMMENTS),
                      key=lambda p: -(p.get("num_comments") or 0))[:MAX_THREADS]
        for p in cand:
            before, pages = None, 0
            while pages < MAX_PAGES:
                params = {"link_id": "t3_" + p["id"], "limit": 100, "fields": COMM_FIELDS}
                if before:
                    params["before"] = before
                d = get(ws, "comments/search", params)
                pages += 1
                items = (d or {}).get("data") or []
                for it in items:
                    tl = (it.get("body") or "").lower()
                    comments.setdefault(it["id"], {**it, "body": (it.get("body") or "")[:2000],
                                                   "terms": [t for t, rx in terms_rx.items() if rx.search(tl)], "native": 0, "thread": 1})
                if len(items) < 100:
                    break
                before = min(int(x["created_utc"]) for x in items)
        with open(cp, "w", encoding="utf-8") as fh:
            for r in sorted(comments.values(), key=lambda x: x["created_utc"]):
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{nid:34} threads={len(cand):3} comments {n0} -> {len(comments)} req={stats['req']} cached={stats['cached']} fail={stats['fail']}", flush=True)
