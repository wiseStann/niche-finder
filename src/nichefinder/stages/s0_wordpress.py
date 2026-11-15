"""S0: the most popular WordPress plugins from the official plugin API (active installs, ratings, tags).

Takes the "popular" list, 250 plugins per page, 12 pages, cached under data/cache/wordpress/popular_<page>.json,
and writes data/raw/wordpress_plugins.csv: slug, name, active_installs, rating, num_ratings, downloaded, added,
last_updated, tags, short_description. Signal type proven/transactions: B2B-SMB tools with honest install counts.
12 requests, 1 s apart. No keys.
"""
from __future__ import annotations

import argparse
import csv
import urllib.parse

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Popular WordPress plugins (official API)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

PAGES = 12


def fetch(ws: Workspace, page: int):
    q = urllib.parse.urlencode({"action": "query_plugins", "request[browse]": "popular", "request[per_page]": 250, "request[page]": page})
    return http.get_json("https://api.wordpress.org/plugins/info/1.2/?" + q, cache=ws.cache("wordpress"),
                         cache_key=f"popular_{page}", hashed=False, timeout=60, sleep=1.0)


def run(ws: Workspace, args: argparse.Namespace) -> None:
    rows = []
    for p in range(1, PAGES + 1):
        try:
            d = fetch(ws, p)
        except Exception as e:  # noqa: BLE001
            print(f"  ! page {p}: {e}")
            continue
        for x in d.get("plugins", []):
            rows.append({"slug": x["slug"], "name": x["name"], "active_installs": x.get("active_installs", 0), "rating": x.get("rating", 0),
                         "num_ratings": x.get("num_ratings", 0), "downloaded": x.get("downloaded", 0), "added": x.get("added", ""),
                         "last_updated": (x.get("last_updated") or "")[:10],
                         "tags": "|".join((x.get("tags") or {}).values()), "short_description": (x.get("short_description") or "")[:200]})
        print(f"page {p}: {len(d.get('plugins', []))}")
    if not rows:
        print("no WordPress plugins fetched; nothing written")
        return
    out = ws.raw("wordpress_plugins.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("->", out, len(rows))
