"""S0: top-100 grossing App Store apps per genre in the US and RU storefronts (public iTunes RSS).

Writes data/raw/appstore_top.csv with columns country, genre, rank, name, developer, price, app_id, summary.
Games and medical apps are left out by design (hit-driven, expertise-heavy). Shows B2C categories where people
already pay. Responses are cached under data/cache/appstore_top/ (one file per country and genre).
32 requests (2 storefronts x 16 genres). No keys.
"""
from __future__ import annotations

import argparse
import csv

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Top-grossing App Store apps by genre (iTunes RSS)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

GENRES = {
    6000: "Business", 6002: "Utilities", 6007: "Productivity", 6008: "Photo & Video", 6012: "Lifestyle",
    6013: "Health & Fitness", 6015: "Finance", 6017: "Education", 6027: "Graphics & Design", 6023: "Food & Drink",
    6003: "Travel", 6011: "Music", 6006: "Reference", 6004: "Sports", 6005: "Social Networking", 6024: "Shopping",
}
COUNTRIES = ["us", "ru"]


def fetch(ws: Workspace, country: str, genre: int):
    url = f"https://itunes.apple.com/{country}/rss/topgrossingapplications/limit=100/genre={genre}/json"
    return http.get_json(url, cache=ws.cache("appstore_top"), cache_key=f"appstore_{country}_{genre}", hashed=False,
                         timeout=60, sleep=0.5, user_agent="Mozilla/5.0 niche-finder")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    rows = []
    for country in COUNTRIES:
        for gid, gname in GENRES.items():
            try:
                feed = fetch(ws, country, gid)["feed"]
            except Exception as e:  # noqa: BLE001
                print(f"  ! {country} {gname}: {e}")
                continue
            for i, e in enumerate(feed.get("entry", []), 1):
                rows.append({
                    "country": country,
                    "genre": gname,
                    "rank": i,
                    "name": e["im:name"]["label"],
                    "developer": e.get("im:artist", {}).get("label", ""),
                    "price": e.get("im:price", {}).get("attributes", {}).get("amount", ""),
                    "app_id": e.get("id", {}).get("attributes", {}).get("im:id", ""),
                    "summary": (e.get("summary", {}).get("label", "") or "").replace("\n", " ")[:300],
                })
            print(f"{country} {gname}: {len(feed.get('entry', []))}")
    if not rows:
        print("no App Store rows fetched; nothing written")
        return
    out = ws.raw("appstore_top.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nrows: {len(rows)} -> {out}")
