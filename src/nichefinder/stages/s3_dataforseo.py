"""Pull Google Ads search volume, CPC, competition and monthly history from DataForSEO for every query.

Demand pools (ws.markets): us = United States, ww = worldwide in English (no location), ru = Russian-language
worldwide (Google Ads does not target Russia). Queries come from queries/*.yaml (English for us/ww, Russian for ru).
Output: data/out/dfs_<pool>.csv (keyword, volume, CPC, bids, competition, monthly history).
Incremental: keywords already in the CSV are not requested again; one batch of up to 1000 new keywords is one paid
call (about $0.09). Batches are cached by content, so re-running is free. The expected cost is printed before any call;
--dry prints it and stops.
Keys: DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json

from nichefinder import niches
from nichefinder.sources import dataforseo as dfs
from nichefinder.workspace import Workspace

SUMMARY = "Google Ads search volume, CPC and 48-month history from DataForSEO (US, worldwide, Russian)"
KEYS: tuple[str, ...] = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")

GEOS = {
    "us": {"lang": "en", "location_code": 2840, "language_code": "en"},
    "ww": {"lang": "en", "location_code": None, "language_code": "en"},
    "ru": {"lang": "ru", "location_code": None, "language_code": "ru"},  # Google Ads cannot target Russia: Russian-language worldwide
}
FIELDS = ["keyword", "geo", "search_volume", "competition", "competition_index", "cpc", "low_bid", "high_bid", "monthly_json"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("pools", nargs="*", help="demand pools: us, ww, ru (default: the markets in nf.yaml)")
    parser.add_argument("--dry", action="store_true", help="print the keyword counts and the expected cost, make no calls")


def date_from(ws: Workspace) -> str:
    """First day of the month `history_months` before the run date (default 48 months)."""
    months = int(ws.load_config("score.yaml", {}).get("history_months", 48))
    t = ws.today
    idx = t.year * 12 + (t.month - 1) - months
    return f"{idx // 12}-{idx % 12 + 1:02d}-01"


def keyword_list(ws: Workspace, lang: str) -> list[str]:
    seen, kws = set(), []
    for r in niches.keyword_rows(ws, lang):
        q = r["q"].strip().lower()
        if q not in seen:
            seen.add(q)
            kws.append(q)
    return kws


def plan(ws: Workspace, geo: str):
    """(path, all keywords, old rows, new keywords, batches, number of batches not in the cache)."""
    cfg = GEOS[geo]
    kws = keyword_list(ws, cfg["lang"])
    path = ws.out(f"dfs_{geo}.csv")
    old_rows = list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []
    have = {r["keyword"] for r in old_rows}
    new_kws = [k for k in kws if k not in have]
    batches = [new_kws[i:i + dfs.BATCH] for i in range(0, len(new_kws), dfs.BATCH)]
    start = date_from(ws)
    paid = sum(1 for b in batches if not dfs.search_volume_cached(ws, b, cfg["location_code"], cfg["language_code"], start))
    return path, kws, old_rows, new_kws, batches, paid


def pull(ws: Workspace, geo: str) -> float:
    cfg = GEOS[geo]
    path, kws, old_rows, new_kws, batches, _ = plan(ws, geo)
    start = date_from(ws)
    total_cost = 0.0
    keep = set(kws)
    rows = [r for r in old_rows if r["keyword"] in keep]
    for n, batch in enumerate(batches, 1):
        data, cost = dfs.search_volume(ws, batch, cfg["location_code"], cfg["language_code"], start)
        total_cost += cost or 0
        print(f"  batch {n}: {len(data)} answers, cost={cost}")
        for kw in batch:
            it = data.get(kw)
            if not it:
                rows.append({"keyword": kw, "geo": geo, "search_volume": "", "competition": "", "competition_index": "", "cpc": "", "low_bid": "", "high_bid": "", "monthly_json": "[]"})
                continue
            monthly = [(f"{m['year']}-{int(m['month']):02d}", m.get("search_volume") or 0) for m in (it.get("monthly_searches") or [])]
            monthly.sort()
            rows.append({
                "keyword": kw, "geo": geo,
                "search_volume": it.get("search_volume") if it.get("search_volume") is not None else "",
                "competition": it.get("competition") or "",
                "competition_index": it.get("competition_index") if it.get("competition_index") is not None else "",
                "cpc": it.get("cpc") if it.get("cpc") is not None else "",
                "low_bid": it.get("low_top_of_page_bid") if it.get("low_top_of_page_bid") is not None else "",
                "high_bid": it.get("high_top_of_page_bid") if it.get("high_top_of_page_bid") is not None else "",
                "monthly_json": json.dumps(monthly),
            })
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    nz = sum(1 for r in rows if r["search_volume"] not in ("", 0, "0"))
    print(f"[{geo}] wrote {len(rows)} rows, with volume > 0: {nz}; cost=${total_cost:.2f} -> {path}")
    return total_cost


def run(ws: Workspace, args: argparse.Namespace) -> None:
    geos = args.pools or [m for m in ws.markets if m in GEOS]
    unknown = [g for g in geos if g not in GEOS]
    if unknown:
        raise SystemExit(f"unknown pool(s): {', '.join(unknown)} (choose from {', '.join(GEOS)})")
    expected = 0.0
    todo = []
    for g in geos:
        _, kws, old_rows, new_kws, batches, paid = plan(ws, g)
        print(f"[{g}] keywords: {len(kws)}, already pulled: {len(old_rows)}, new: {len(new_kws)} -> {len(batches)} call(s), "
              f"{paid} not cached (about ${paid * dfs.COST_PER_CALL:.2f})")
        expected += paid * dfs.COST_PER_CALL
        if new_kws:
            todo.append(g)
    print(f"expected cost: about ${expected:.2f}")
    if args.dry:
        return
    if expected > 0:
        print("balance before:", dfs.balance())
    spent = sum(pull(ws, g) for g in todo)
    if expected > 0:
        print(f"spent ${spent:.2f}; balance after: {dfs.balance()}  ({dt.datetime.now():%Y-%m-%d %H:%M})")
    else:
        print("nothing to pay: every batch came from the cache")
