"""Reddit posts and comments per niche from the Arctic Shift archive (no keys).

The official Reddit API needs an approved app and reddit.com/*.json refuses non-browser clients, so this stage uses
Arctic Shift (arctic-shift.photon-reddit.com), an open mirror of the Reddit archive. Its full-text search (`query`/`body`)
and aggregates time out on medium and large subreddits (HTTP 422 "Timeout. Maybe slow down a bit"), while a plain listing by
date (subreddit + after/before, no text) answers in about a second even for r/personalfinance. So each subreddit is
listed by date and filtered by terms locally.

Volume rules (config/reddit_terms.yaml: subs, terms, brands, and the `_settings` block):
- "native" subreddit (at most `native_max_posts` posts in total): all posts since `history_start` are kept (the community is
  the niche), comments for the last `recent_months`;
- big subreddit: posts for the last `recent_months` (at most 100 pages = 10k recent posts), only those matching the niche
  terms are kept; comments are not fetched (thousands per day).
All windows end at the run date (`as_of` in nf.yaml, today by default).

Output: data/cache/arctic/<niche>_posts.jsonl and _comments.jsonl (`terms` = matched phrases, `native` = from a native
subreddit), data/out/reddit_subs_stats_<shard>.csv, reddit_fetch_log_<shard>.csv. Raw API pages are cached in
data/cache/arctic/req/, so re-runs are free. Env ARCTIC_PAUSE sets the pause between live requests (default 0.6 s;
the archive serves about 30 pages a minute over 3 parallel shards).
Usage: nf run s10_reddit_fetch -- [--niches a,b] [--shard k/N] [--posts-only]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.parse

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Reddit posts and comments per niche from the Arctic Shift archive"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

API = "https://arctic-shift.photon-reddit.com/api"
UA = "niche-finder/0.1 (non-commercial market research)"
DEFAULT_SETTINGS = {"history_start": "2022-01-01", "native_max_posts": 70_000, "recent_months": 12}
# Safety caps (100 records per page): native posts, big-subreddit posts, comments.
MAX_PAGES_NATIVE, MAX_PAGES_BIG, MAX_PAGES_COMMENTS = 300, 100, 120
POST_FIELDS = "id,created_utc,subreddit,title,selftext,num_comments,score,author"
COMM_FIELDS = "id,created_utc,subreddit,body,score,link_id,author"
stats = {"req": 0, "cached": 0, "fail": 0}


def pause() -> float:
    return float(os.environ.get("ARCTIC_PAUSE", 0.6))


def terms_config(ws: Workspace) -> tuple[dict, dict]:
    """(niches, settings) from config/reddit_terms.yaml; keys starting with "_" are settings."""
    raw = ws.load_config("reddit_terms.yaml")
    settings = {**DEFAULT_SETTINGS, **(raw.get("_settings") or {})}
    return {k: v for k, v in raw.items() if not str(k).startswith("_")}, settings


def months_back(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    m += 1
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(d.day, last))


def ts(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def get(ws: Workspace, path: str, params: dict, tries: int = 6):
    """One Arctic Shift call with the raw page cached by URL hash. None after all retries fail."""
    req_dir = ws.cache("arctic") / "req"
    req_dir.mkdir(parents=True, exist_ok=True)
    u = f"{API}/{path}?" + urllib.parse.urlencode(params)
    key = req_dir / (hashlib.sha1(u.encode()).hexdigest() + ".json")
    if key.exists():
        stats["cached"] += 1
        return json.loads(key.read_text(encoding="utf-8"))
    for i in range(tries):
        stats["req"] += 1
        try:
            resp = http.request(u, user_agent=UA, timeout=150, tries=1, raise_for_status=False)
            if resp.status == 400:
                print("    400 (bad parameter, not retried):", u[:160])
                break
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}")
            d = resp.json()
            if d.get("error"):
                raise RuntimeError(d["error"])
            key.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            time.sleep(pause())
            return d
        except Exception as e:  # noqa: BLE001 — network, HTTP, timeout, bad JSON: retry
            wait = (2, 4, 8, 15, 30, 60)[i]   # connection resets usually clear on the next try
            print(f"    retry {i + 1}/{tries} in {wait}s: {str(e)[:50]} | {path} {params.get('subreddit')} {params.get('after')}..{params.get('before')}", flush=True)
            time.sleep(wait)
    stats["fail"] += 1
    return None


def dump(ws, kind, sub, t_from, t_to, max_pages, log):
    """List a subreddit by date, 100 per page, newest first; the cursor is before = min(created_utc)."""
    path = "posts/search" if kind == "posts" else "comments/search"
    fields = POST_FIELDS if kind == "posts" else COMM_FIELDS
    out, before, pages = [], t_to, 0
    while pages < max_pages:
        d = get(ws, path, {"subreddit": sub, "after": t_from, "before": before, "limit": 100, "fields": fields})
        pages += 1
        if d is None:
            log.append({"kind": kind, "sub": sub, "after": t_from, "before": before, "n": "", "status": "FAIL"}); break
        items = d.get("data") or []
        out.extend(items)
        if len(items) < 100:
            break
        before = min(int(x["created_utc"]) for x in items)   # records in the same second may repeat: deduplicated by id later
    log.append({"kind": kind, "sub": sub, "after": t_from, "before": t_to, "n": len(out), "status": f"pages={pages}"})
    return out


def sub_stats(ws, sub):
    d = get(ws, "subreddits/search", {"subreddit": sub})
    if not d or not d.get("data"):
        return {"sub": sub}
    s = d["data"][0]; m = s.get("_meta") or {}
    return {"sub": sub, "display": s.get("display_name"), "subscribers": s.get("subscribers"),
            "created": dt.datetime.fromtimestamp(s["created_utc"], dt.timezone.utc).date().isoformat() if s.get("created_utc") else "",
            "num_posts": m.get("num_posts"), "num_comments": m.get("num_comments")}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: all in reddit_terms.yaml)")
    parser.add_argument("--shard", default="0/1", help="k/N: process every N-th niche starting at k (parallel runs)")
    parser.add_argument("--posts-only", action="store_true", help="skip comments")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg, st = terms_config(ws)
    now_d = ws.today
    now = ts(now_d)
    t_history = ts(dt.date.fromisoformat(str(st["history_start"])))
    t_recent = ts(months_back(now_d, int(st["recent_months"])))
    native_max = int(st["native_max_posts"])
    cache = ws.cache("arctic")
    ids = [n for n in cfg if not args.niches or n in args.niches.split(",")]
    k, n = map(int, args.shard.split("/"))
    ids = [x for i, x in enumerate(ids) if i % n == k]
    log, substats = [], {}
    for nid in ids:
        c = cfg[nid]
        terms_rx = {t: re.compile(r"(?<![a-z0-9])" + re.escape(t.lower()) + r"(?![a-z0-9])") for t in c["terms"]}
        posts, comments = {}, {}
        t0 = time.time()
        for sub in c["subs"]:
            if sub not in substats:
                substats[sub] = sub_stats(ws, sub)
            native = (substats[sub].get("num_posts") or 10**9) <= native_max
            for it in dump(ws, "posts", sub, t_history if native else t_recent, now, MAX_PAGES_NATIVE if native else MAX_PAGES_BIG, log):
                tl = ((it.get("title") or "") + " " + (it.get("selftext") or "")).lower()
                matched = [t for t, rx in terms_rx.items() if rx.search(tl)]
                if native or matched:
                    posts.setdefault(it["id"], {**it, "selftext": (it.get("selftext") or "")[:3000], "terms": matched, "native": int(native)})
            if native and not args.posts_only:
                for it in dump(ws, "comments", sub, t_recent, now, MAX_PAGES_COMMENTS, log):
                    tl = (it.get("body") or "").lower()
                    matched = [t for t, rx in terms_rx.items() if rx.search(tl)]
                    comments.setdefault(it["id"], {**it, "body": (it.get("body") or "")[:2000], "terms": matched, "native": 1})
            print(f"  {nid:34} r/{sub:22} {'native' if native else 'big   '} posts={len(posts):6} comments={len(comments):6} req={stats['req']} cached={stats['cached']} fail={stats['fail']} {time.time() - t0:.0f}s", flush=True)
        with open(cache / f"{nid}_posts.jsonl", "w", encoding="utf-8") as fh:
            for r in sorted(posts.values(), key=lambda x: x["created_utc"]):
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        if not args.posts_only:
            with open(cache / f"{nid}_comments.jsonl", "w", encoding="utf-8") as fh:
                for r in sorted(comments.values(), key=lambda x: x["created_utc"]):
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"-> {nid}: posts {len(posts)}, comments {len(comments)}", flush=True)
    tag = args.shard.replace("/", "of")
    with open(ws.out(f"reddit_fetch_log_{tag}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["kind", "sub", "after", "before", "n", "status"]); w.writeheader(); w.writerows(log)
    cols = ["sub", "display", "subscribers", "created", "num_posts", "num_comments"]
    with open(ws.out(f"reddit_subs_stats_{tag}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        w.writerows([{k: v.get(k, "") for k in cols} for v in substats.values()])
    print("done", stats)
