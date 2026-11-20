"""S0: Product Hunt launches from the official GraphQL API v2: the top featured posts of the last 12 months.

The web leaderboards sit behind a Cloudflare JavaScript challenge (HTTP 403 since November 2026), so the stage reads the
official API with a free developer token, PRODUCTHUNT_TOKEN: create an application at
https://www.producthunt.com/v2/oauth/applications and copy its developer token into the workspace .env.

Periods derive from the run date: the 12 full months before the current month and 52 ISO weeks ending two weeks before
the run date. For each period the stage asks for featured posts ordered by votes and keeps the top --top-month posts of a
month and the top --top-week posts of a week. Pages of 20 posts are cached under data/cache/producthunt/, so a re-run is
free and an interrupted run resumes. The API allows a query complexity of 6,250 points per 15 minutes; on a rate-limit
answer the stage waits for the reset and goes on.

Writes data/raw/ph_top.csv with columns period, name, slug, tagline, votes, topics (up to 4, joined by |). Duplicate
slugs are dropped (monthly periods come first). When nothing is fetched an existing ph_top.csv is kept. A file with the
same columns can also be provided by hand; s0_merge and s5_deals use it when present.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import time

from nichefinder import http, keys
from nichefinder.workspace import Workspace

SUMMARY = "Product Hunt launches, top featured posts of the last 12 months (official API)"
KEYS: tuple[str, ...] = ("PRODUCTHUNT_TOKEN",)
NEEDS: tuple[str, ...] = ()

API = "https://api.producthunt.com/v2/api/graphql"
PAGE = 20
QUERY = """query($first: Int!, $after: String, $postedAfter: DateTime, $postedBefore: DateTime) {
  posts(featured: true, order: VOTES, first: $first, after: $after, postedAfter: $postedAfter, postedBefore: $postedBefore) {
    pageInfo { hasNextPage endCursor }
    edges { node { name slug tagline votesCount topics(first: 4) { edges { node { name } } } } }
  }
}"""


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--top-month", type=int, default=60, help="posts kept per month (default 60)")
    p.add_argument("--top-week", type=int, default=20, help="posts kept per week (default 20)")


def periods(today: dt.date) -> list[tuple[int, int, str]]:
    """(year, month-or-week, 'monthly'|'weekly') for the last 12 full months and 52 weeks."""
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        months.append((y, m))
    months.reverse()
    end = today - dt.timedelta(days=14)
    weeks = []
    for k in range(52):
        iso = (end - dt.timedelta(days=7 * k)).isocalendar()
        weeks.append((iso[0], iso[1]))
    weeks.reverse()
    return [(y, m, "monthly") for y, m in months] + [(y, w, "weekly") for y, w in weeks]


def bounds(y: int, n: int, kind: str) -> tuple[str, str]:
    """postedAfter / postedBefore of a period, UTC midnights."""
    if kind == "monthly":
        start, end = dt.date(y, n, 1), dt.date(y + n // 12, n % 12 + 1, 1)
    else:
        start = dt.date.fromisocalendar(y, n, 1)
        end = start + dt.timedelta(days=7)
    return f"{start}T00:00:00Z", f"{end}T00:00:00Z"


def reset_wait(text: str) -> int:
    """Seconds until the rate-limit window resets, from the error details; 15 minutes when the answer does not say."""
    try:
        errs = json.loads(text).get("errors") or []
        sec = int(errs[0].get("details", {}).get("reset_in"))
    except (ValueError, AttributeError, IndexError, TypeError):
        sec = 900
    return min(max(sec, 5), 960) + 5


def fetch_page(ws: Workspace, token: str, period: str, start: str, end: str, after: str | None) -> dict:
    """One page of posts (the `posts` connection). Only complete answers are cached."""
    path = http.cache_file(ws.cache("producthunt"), f"gql|{period}|{PAGE}|{after or ''}")
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    body = {"query": QUERY, "variables": {"first": PAGE, "after": after, "postedAfter": start, "postedBefore": end}}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    for _ in range(4):
        resp = http.request(API, method="POST", data=body, headers=headers, user_agent=http.BOT_UA, timeout=60,
                            retry_statuses=(500, 502, 503, 504), raise_for_status=False)
        if resp.status == 429 or (resp.status == 200 and '"errors"' in resp.text and "rate_limit" in resp.text):
            wait = reset_wait(resp.text)
            print(f"  rate limit reached; waiting {wait} s for the reset", flush=True)
            time.sleep(wait)
            continue
        break
    if resp.status in (401, 403):
        raise RuntimeError(f"Product Hunt API answered HTTP {resp.status}; check PRODUCTHUNT_TOKEN: {resp.text[:200]}")
    if resp.status >= 400:
        raise http.HttpError(resp.status, API, resp.text)
    data = resp.json()
    posts = (data.get("data") or {}).get("posts")
    if data.get("errors") or posts is None:
        raise RuntimeError(f"Product Hunt API error for {period}: {json.dumps(data.get('errors'))[:300]}")
    path.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    time.sleep(1.0)
    return posts


def parse(posts: dict, period: str) -> list[dict]:
    rows = []
    for e in posts.get("edges") or []:
        n = e["node"]
        topics = [t["node"]["name"] for t in ((n.get("topics") or {}).get("edges") or [])][:4]
        rows.append({"period": period, "name": n["name"], "slug": n["slug"], "tagline": n.get("tagline") or "",
                     "votes": n.get("votesCount", ""), "topics": "|".join(topics)})
    return rows


def run(ws: Workspace, args: argparse.Namespace) -> None:
    (token,) = keys.require("PRODUCTHUNT_TOKEN", purpose="the Product Hunt API")
    top = {"monthly": getattr(args, "top_month", 60), "weekly": getattr(args, "top_week", 20)}
    rows = []
    for y, n, kind in periods(ws.today):
        period = f"{kind[0]}{y}-{n:02d}"
        start, end = bounds(y, n, kind)
        got: list[dict] = []
        after = None
        while len(got) < top[kind]:
            posts = fetch_page(ws, token, period, start, end, after)
            got += parse(posts, period)
            info = posts.get("pageInfo") or {}
            if not info.get("hasNextPage") or not info.get("endCursor"):
                break
            after = info["endCursor"]
        got = got[:top[kind]]
        rows += got
        print(f"{period}: {len(got)} posts", flush=True)
    seen: set[str] = set()
    uniq = []
    for r in rows:
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        uniq.append(r)
    if not uniq:
        print("no Product Hunt posts fetched; nothing written (an existing ph_top.csv is kept).")
        return
    out = ws.raw("ph_top.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(uniq[0].keys()))
        w.writeheader()
        w.writerows(uniq)
    print(f"\nunique: {len(uniq)} -> {out}")
