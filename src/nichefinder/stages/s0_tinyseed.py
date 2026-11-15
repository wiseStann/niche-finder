"""S0: TinySeed accelerator portfolio (small-team, bootstrapped B2B SaaS companies).

Fetches https://tinyseed.com/portfolio (one request, cached under data/cache/tinyseed/) and writes
data/raw/tinyseed_portfolio.csv with columns name, website, excerpt, location, profile_url, which s0_merge
and s5_deals read. Source type: proven.

If the page cannot be fetched or parsed (the site is a hosted page builder and its markup can change), the stage
explains how to provide the file by hand and exits without error: create data/raw/tinyseed_portfolio.csv with at
least the columns name, website, excerpt (one row per portfolio company). An existing file is never overwritten
by an empty result. No keys.
"""
from __future__ import annotations

import argparse
import csv
import html
import re

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "TinySeed portfolio companies (tinyseed.com/portfolio)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

URL = "https://tinyseed.com/portfolio"
FIELDS = ["name", "website", "excerpt", "location", "profile_url"]
ITEM_SPLIT = re.compile(r'class="\s*summary-item\s')
TITLE_RE = re.compile(r'<a\s+href="([^"]*)"\s+class="summary-title-link">\s*(.*?)\s*</a>', re.S)
EXCERPT_RE = re.compile(r'class="\s*summary-excerpt[^"]*"\s*>(.*?)</div>', re.S)
LOCATION_RE = re.compile(r'summary-metadata-item--location"><a[^>]*>(.*?)</a>', re.S)
PROFILE_HREF_RE = re.compile(r'<a href="([^"]+)" class="summary-read-more-link"')


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse(page: str) -> list[dict]:
    rows, seen = [], set()
    for block in ITEM_SPLIT.split(page)[1:]:
        t = TITLE_RE.search(block)
        if not t:
            continue
        name = _text(t.group(2))
        if not name or name in seen:
            continue
        seen.add(name)
        ex, loc, prof = EXCERPT_RE.search(block), LOCATION_RE.search(block), PROFILE_HREF_RE.search(block)
        profile = prof.group(1) if prof else ""
        rows.append({
            "name": name,
            "website": t.group(1).strip(),
            "excerpt": _text(ex.group(1)) if ex else "",
            "location": _text(loc.group(1)) if loc else "",
            "profile_url": ("https://tinyseed.com" + profile) if profile.startswith("/") else profile,
        })
    return rows


def _manual_hint(ws: Workspace, why: str) -> None:
    print(f"TinySeed portfolio not fetched ({why}).")
    print(f"To provide it by hand, create {ws.raw('tinyseed_portfolio.csv')} with columns name,website,excerpt "
          f"(one row per portfolio company; see {URL}). Stages that read it treat a missing file as empty.")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    try:
        page = http.get_text(URL, cache=ws.cache("tinyseed"), cache_key="portfolio", ext=".html", hashed=False,
                             timeout=60, min_size=10_000)
    except Exception as e:  # noqa: BLE001
        _manual_hint(ws, str(e)[:120])
        return
    rows = parse(page)
    if not rows:
        _manual_hint(ws, "no company cards found on the page")
        return
    out = ws.raw("tinyseed_portfolio.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"TinySeed portfolio: {len(rows)} companies -> {out}")
