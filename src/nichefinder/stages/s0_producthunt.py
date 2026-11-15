"""S0: Product Hunt launches from the monthly and weekly leaderboards of the last 12 months.

Reads the server-rendered leaderboard pages (no token needed), cached under data/cache/producthunt/, and writes
data/raw/ph_top.csv with columns period, name, slug, tagline, votes, topics. Periods derive from the run date:
the 12 full months before the current month and 52 ISO weeks ending two weeks before the run date.
Duplicate slugs are dropped (monthly pages come first). About 64 requests, 1.5 s apart. No keys.

Product Hunt may answer with an anti-bot challenge (HTTP 403). After 3 consecutive failures the stage stops, keeps any
existing data/raw/ph_top.csv untouched and explains how to provide the file by hand (same columns, one row per post).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Product Hunt launches, last 12 months of leaderboards"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

POST_RE = re.compile(r'"__typename":"Post","id":"(\d+)",(?:"promotedPillImageUrl":"[^"]*",)?"name":"((?:[^"\\]|\\.)*)","slug":"([^"]+)","tagline":"((?:[^"\\]|\\.)*)"')
VOTES_RE = re.compile(r'"votesCount":(\d+)')
TOPICS_RE = re.compile(r'"__typename":"Topic","id":"\d+","name":"([^"]+)"')


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


def fetch(ws: Workspace, y: int, n: int, kind: str) -> str:
    url = f"https://www.producthunt.com/leaderboard/{kind}/{y}/{n}/all"
    return http.get_text(url, cache=ws.cache("producthunt"), cache_key=f"ph_{kind[0]}_{y}-{n:02d}", ext=".html",
                         hashed=False, timeout=60, min_size=1000, sleep=1.5)


def parse(h: str, period: str) -> list[dict]:
    rows = []
    for mm in POST_RE.finditer(h):
        _pid, name, slug, tagline = mm.groups()
        tail = h[mm.end():mm.end() + 3000]
        v = VOTES_RE.search(tail)
        topics = TOPICS_RE.findall(tail)[:4]
        rows.append({
            "period": period,
            "name": json.loads(f'"{name}"'),
            "slug": slug,
            "tagline": json.loads(f'"{tagline}"'),
            "votes": int(v.group(1)) if v else "",
            "topics": "|".join(topics),
        })
    return rows


def run(ws: Workspace, args: argparse.Namespace) -> None:
    rows = []
    failures = 0
    for y, n, kind in periods(ws.today):
        period = f"{kind[0]}{y}-{n:02d}"
        try:
            h = fetch(ws, y, n, kind)
            failures = 0
        except Exception as e:  # noqa: BLE001
            print(f"  ! {period}: {str(e)[:120]}")
            failures += 1
            if failures >= 3:
                print("Product Hunt keeps refusing requests (anti-bot challenge); stopping.")
                break
            continue
        got = parse(h, period)
        rows += got
        print(f"{period}: {len(got)} posts")
    seen: set[str] = set()
    uniq = []
    for r in rows:
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        uniq.append(r)
    if not uniq:
        print("no Product Hunt posts fetched; nothing written.")
        print(f"To provide the data by hand, create {ws.raw('ph_top.csv')} with columns period,name,slug,tagline,votes,topics "
              "(topics joined by |); s0_merge and s5_deals use it when present.")
        return
    out = ws.raw("ph_top.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(uniq[0].keys()))
        w.writeheader()
        w.writerows(uniq)
    print(f"\nunique: {len(uniq)} -> {out}")
