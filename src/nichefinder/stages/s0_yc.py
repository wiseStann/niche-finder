"""S0: Y Combinator companies of recent batches, from the open yc-oss API.

Downloads one JSON file per batch (https://yc-oss.github.io/api/batches/<batch>.json), cached under
data/cache/yc/, and writes data/raw/yc_companies.csv. Batches that do not exist yet are skipped.
By default the batches of last year and this year are fetched (winter/spring/summer/fall); pass
--batches to choose them explicitly.

The industry filter is soft: only clearly out-of-scope areas (healthcare, biotech, hardware, regulated finance,
crypto, defense, government) get excluded=1; everything else enters the universe as source_type=rising.
Legal tech is kept with expertise_flag=1 so it stays visible.

Columns: name, batch, industry, subindustry, tags, team_size, status, website, one_liner, excluded, expertise_flag.
No keys. About 8 requests.
"""
from __future__ import annotations

import argparse
import csv

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Recent Y Combinator batches (yc-oss API)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

SEASONS = ["winter", "spring", "summer", "fall"]
EXCLUDE_IND = {"Healthcare", "Industrials", "Government", "Fintech"}
EXCLUDE_SUB = {
    "Healthcare", "Biotech", "Drug Discovery and Delivery", "Medical Devices", "Diagnostics", "Therapeutics",
    "Healthcare IT", "Digital Health", "Healthcare Services", "Consumer Health and Wellness",
    "Energy", "Manufacturing and Robotics", "Aviation and Space", "Automotive", "Climate", "Drones", "Agriculture",
    "Banking and Exchange", "Insurance", "Credit and Lending", "Asset Management", "Payments", "Crypto / Web3",
    "Defense", "Legal",  # legal is listed here but kept below: legal tech for lawyers stays, with expertise_flag=1
}
KEEP_LEGAL = True


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--batches", default="", help="comma-separated batch slugs, e.g. winter-2025,summer-2025 "
                                                      "(default: all four seasons of last year and this year)")


def _batches(ws: Workspace, arg: str) -> list[str]:
    if arg:
        return [b.strip() for b in arg.split(",") if b.strip()]
    y = ws.today.year
    return [f"{s}-{yr}" for yr in (y - 1, y) for s in SEASONS]


def fetch(ws: Workspace, batch: str):
    url = f"https://yc-oss.github.io/api/batches/{batch}.json"
    try:
        return http.get_json(url, cache=ws.cache("yc"), cache_key=f"yc_{batch}", hashed=False, timeout=60, sleep=0.5)
    except (http.HttpError, OSError, ValueError) as e:
        print(f"  ! {batch}: {e}")
        return []


def run(ws: Workspace, args: argparse.Namespace) -> None:
    rows = []
    for b in _batches(ws, args.batches):
        for c in fetch(ws, b):
            ind = c.get("industry") or ""
            sub = c.get("subindustry") or ""
            excluded = ind in EXCLUDE_IND or sub in EXCLUDE_SUB
            if sub == "Legal" and KEEP_LEGAL:
                excluded = False
            rows.append({
                "name": c["name"],
                "batch": c.get("batch"),
                "industry": ind,
                "subindustry": sub,
                "tags": "|".join(c.get("tags") or []),
                "team_size": c.get("team_size"),
                "status": c.get("status"),
                "website": c.get("website"),
                "one_liner": (c.get("one_liner") or "").replace("\n", " "),
                "excluded": int(excluded),
                "expertise_flag": int(sub == "Legal"),
            })
    if not rows:
        print("no YC companies fetched; nothing written")
        return
    out = ws.raw("yc_companies.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    kept = [r for r in rows if not r["excluded"]]
    print(f"total {len(rows)}, in scope {len(kept)}")
    print("\nindustry / subindustry (in scope):")
    sub_stats: dict[str, int] = {}
    for r in kept:
        k = f"{r['industry']} / {r['subindustry']}"
        sub_stats[k] = sub_stats.get(k, 0) + 1
    for k, v in sorted(sub_stats.items(), key=lambda x: -x[1]):
        print(f"  {v:4d}  {k}")
    print(f"-> {out}")
