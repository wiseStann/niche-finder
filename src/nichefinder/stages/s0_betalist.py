"""S0: BetaList - startups shortly before launch, from the chronological list betalist.com/startups?page=N.

Walks the list newest first until the day headings are older than --months (default 12) or --max-pages is reached, and
writes data/raw/betalist.csv: name, slug, tagline, date, url. A list page carries day headings
(data-duplicate-id="day_<unix time>") followed by startup rows (name and a one-line tagline); a startup listed twice
(boosted) is kept once, with its newest date.

BetaList shows products 3-6 months before Product Hunt and about half never launch: the signal is where new founders
are heading (source_type=rising), not proven demand. Pages shift as startups are added, so the cache key carries the
month of the run (ws.today): a re-run within the month is free and the next month fetches fresh pages.
No keys; 1.5 s between live requests; a page holds ~50 startups (3-4 days), so a year of history is ~110 pages
(5,322 startups in the run of 2026-11-17), about 4 minutes on the first run.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import re

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "BetaList pre-launch startups, newest first (betalist.com/startups)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

FIELDS = ["name", "slug", "tagline", "date", "url"]
TOKEN = re.compile(r'data-duplicate-id="day_(\d+)"|startup-row"')
SLUG = re.compile(r'href="/startups/([a-z0-9-]+)"')
SPAN = re.compile(r"<span[^>]*>(.*?)</span>", re.S)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--months", type=float, default=12, help="how far back to walk, in months (default 12)")
    parser.add_argument("--max-pages", type=int, default=400, help="safety cap on list pages (default 400)")


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_page(h: str) -> list[dict]:
    """Startup rows of one list page, each with the date of the day heading above it (empty before the first heading)."""
    rows, day = [], ""
    marks = list(TOKEN.finditer(h))
    for i, m in enumerate(marks):
        if m.group(1):
            day = dt.datetime.fromtimestamp(int(m.group(1)), dt.timezone.utc).date().isoformat()
            continue
        block = h[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(h)]
        slug = SLUG.search(block)
        # the name span may hold a badge link (TESTFLIGHT); the follow button's spans hold only icons
        texts = [t for t in (_plain(re.sub(r"<a\b.*?</a>", " ", s, flags=re.S)) for s in SPAN.findall(block)) if t]
        if not slug or not texts:
            continue
        rows.append({"name": texts[0], "slug": slug.group(1), "tagline": texts[1] if len(texts) > 1 else "", "date": day,
                     "url": f"https://betalist.com/startups/{slug.group(1)}"})
    return rows


def fetch(ws: Workspace, stamp: str, page: int) -> str:
    return http.get_text(f"https://betalist.com/startups?page={page}", cache=ws.cache("betalist"), cache_key=f"betalist_{stamp}_p{page}",
                         ext=".html", hashed=False, timeout=60, min_size=20_000, sleep=1.5, backend="auto")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cutoff = (ws.today - dt.timedelta(days=round(args.months * 30.44))).isoformat()
    stamp = f"{ws.today:%Y-%m}"
    seen: dict[str, dict] = {}
    for page in range(1, args.max_pages + 1):
        try:
            rows = parse_page(fetch(ws, stamp, page))
        except (http.HttpError, OSError) as e:
            print(f"  ! page {page}: {e}")
            break
        if not rows:
            print(f"page {page}: no startup rows (the end of the list, or the layout changed) - stopping")
            break
        oldest = min((r["date"] for r in rows if r["date"]), default="")
        new = 0
        for r in rows:
            if r["date"] and r["date"] < cutoff:
                continue
            if r["slug"] not in seen:
                seen[r["slug"]] = r
                new += 1
        print(f"page {page}: {len(rows)} startups, oldest day {oldest or '?'}, new {new}")
        if oldest and oldest < cutoff:
            break
    else:
        print(f"stopped at --max-pages {args.max_pages} before reaching {cutoff}")
    out = ws.raw("betalist.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(seen.values())
    if not seen:
        print("warning: no BetaList startups parsed (the site may have changed or blocked the request); wrote an empty file")
    dates = sorted(r["date"] for r in seen.values() if r["date"])
    print(f"startups: {len(seen)}" + (f", {dates[0]} .. {dates[-1]}" if dates else "") + f" -> {out}")
