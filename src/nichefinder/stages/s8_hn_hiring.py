"""Hacker News "Ask HN: Who is hiring?": monthly threads of startup job postings, matched to niches.

Finds the monthly threads (posted by the whoishiring account) of the last --months (default 36) through the Algolia
HN Search API and downloads each thread once (items endpoint; the current month's thread still grows, so it is
re-read once per run day).
A top-level comment is one company's posting; its first line is the headline ("Company | Role | Location | ...").
All postings go to data/raw/hn_hiring.csv: month, company, headline, text (first 600 characters), url.

Postings are matched to niches over their full text with niches.text_matchers (config/deal_keywords.yaml, else the
coverage phrases of shortlisted niches) and counted per niche in data/out/hn_hiring_niche.csv: postings in the last
12 months and the 12 before, over the whole window, distinct companies, and the most recent companies.
Matched postings are listed in data/out/hn_hiring_matches.csv for review.

A match means a funded team builds for this task now, or hires around a tool of this kind: read the examples before
trusting a count. Biased toward dev tools and AI; for SMB verticals 0 is NA, not "no one builds this".
No keys; one request per month of history, plus one for the thread list.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import re

from nichefinder import http, niches
from nichefinder.workspace import Workspace

SUMMARY = "Hacker News 'Who is hiring?' postings per niche (Algolia API)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

API = "https://hn.algolia.com/api/v1"
TITLE = re.compile(r"^Ask HN: Who is hiring\? \((\w+) (\d{4})\)", re.I)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--months", type=int, default=36, help="months of threads to read (default 36)")


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def posting(c: dict, month: str) -> dict | None:
    """A top-level comment -> posting row; None for deleted or empty comments."""
    text = c.get("text") or ""
    if not text.strip():
        return None
    head = plain(re.split(r"<p>", text, maxsplit=1)[0])
    return {"month": month, "company": head.split("|")[0].strip()[:80], "headline": head[:200], "text": plain(text)[:600],
            "url": f"https://news.ycombinator.com/item?id={c.get('id')}"}


def threads(ws: Workspace, months: int) -> list[tuple[str, int]]:
    """(YYYY-MM, story id) of the monthly hiring threads, newest first."""
    since = int(dt.datetime.combine(ws.today - dt.timedelta(days=31 * months + 5), dt.time.min, tzinfo=dt.timezone.utc).timestamp())
    url = f"{API}/search_by_date?tags=story,author_whoishiring&hitsPerPage=1000&numericFilters=created_at_i%3E{since}"
    d = http.get_json(url, cache=ws.cache("hn_hiring"), cache_key=f"threads_{ws.today:%Y-%m}_{months}", hashed=False,
                      user_agent=http.BOT_UA, timeout=60)
    out = []
    for h in d.get("hits", []):
        m = TITLE.match(h.get("title") or "")
        if m and m.group(1).lower() in MONTHS:
            out.append((f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}", int(h["objectID"])))
    out = sorted(set(out), reverse=True)
    return [t for t in out if t[0] <= f"{ws.today:%Y-%m}"][:months]


def run(ws: Workspace, args: argparse.Namespace) -> None:
    found = threads(ws, args.months)
    if not found:
        raise SystemExit("no 'Who is hiring?' threads found - check the network or the Algolia API")
    current = f"{ws.today:%Y-%m}"
    posts: list[dict] = []
    for month, sid in found:
        key = f"item_{sid}" + (f"_{ws.today:%Y-%m-%d}" if month == current else "")   # the current thread still grows
        try:
            item = http.get_json(f"{API}/items/{sid}", cache=ws.cache("hn_hiring"), cache_key=key, hashed=False,
                                 user_agent=http.BOT_UA, timeout=120, sleep=0.5)
        except (http.HttpError, OSError, ValueError) as e:
            print(f"  ! {month} ({sid}): {e}")
            continue
        got = [p for p in (posting(c, month) for c in item.get("children") or []) if p]
        posts += got
        print(f"{month}: {len(got)} postings")
    with open(ws.raw("hn_hiring.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["month", "company", "headline", "text", "url"])
        w.writeheader()
        w.writerows(posts)

    m12 = f"{ws.today - dt.timedelta(days=365):%Y-%m}"
    m24 = f"{ws.today - dt.timedelta(days=730):%Y-%m}"
    rows, matched = [], []
    for nid, hit in niches.text_matchers(ws).items():
        mine = [p for p in posts if hit(p["text"])]
        last = [p for p in mine if p["month"] > m12]
        prev = [p for p in mine if m24 < p["month"] <= m12]
        recent = list(dict.fromkeys(p["company"] for p in mine if p["company"]))
        rows.append({"niche_id": nid, "postings_12m": len(last), "postings_prev12m": len(prev), "postings_window": len(mine),
                     "companies_window": len(set(p["company"].lower() for p in mine)), "recent_companies": "; ".join(recent[:6])})
        matched += [{"niche_id": nid, "month": p["month"], "company": p["company"], "headline": p["headline"], "url": p["url"]} for p in mine]
        if mine:
            print(f"{nid:36} 12m={len(last):3} prev={len(prev):3} window={len(mine):3}  {', '.join(recent[:4])}")
    with open(ws.out("hn_hiring_niche.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "postings_12m", "postings_prev12m", "postings_window", "companies_window", "recent_companies"])
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("hn_hiring_matches.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "month", "company", "headline", "url"])
        w.writeheader()
        w.writerows(matched)
    print(f"threads: {len(found)} ({found[-1][0]} .. {found[0][0]}), postings: {len(posts)}; niches with a match: "
          f"{sum(1 for r in rows if r['postings_window'])} of {len(rows)} -> data/out/hn_hiring_niche.csv")
