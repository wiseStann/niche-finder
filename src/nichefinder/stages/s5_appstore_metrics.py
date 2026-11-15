"""App Store supply metrics from appstore_apps.csv (the relevant set after manual edits).

players_1k/10k - apps with 1k+ / 10k+ ratings; top1/top3/hhi - concentration by ratings; new_12m/new_24m - apps released
within 12/24 months of the run date (releaseDate); free_share_top20 - share of free apps (IAP ignored) in the top 20;
top_seller_share - share of the largest developer by ratings (clone factories). Niches with `na: true` in
config/appstore_relevance.yaml are written as na=1 without metrics.
Input: data/out/appstore_apps.csv. Output: data/out/appstore_metrics.csv.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import timedelta

from nichefinder.workspace import Workspace

SUMMARY = "App Store concentration, new-app and free-share metrics per niche"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def run(ws: Workspace, args: argparse.Namespace) -> None:
    src = ws.out("appstore_apps.csv")
    if not src.is_file():
        print(f"{src} not found - run s5_appstore first")
        return
    rel = ws.load_config("appstore_relevance.yaml", {}) or {}
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    by = defaultdict(list)
    for r in rows:
        if r["relevant"] == "1":
            by[(r["niche_id"], r["store"])].append(r)
    out = []
    today = ws.today
    d12, d24 = (today - timedelta(days=365)).isoformat(), (today - timedelta(days=730)).isoformat()
    for (nid, store), rs in sorted(by.items()):
        cfg = (rel.get(nid) or {}).get(store) or {}
        if cfg.get("na"):
            out.append({"niche_id": nid, "store": store, "na": 1}); continue
        rs.sort(key=lambda r: -int(r["ratings"]))
        tot = sum(int(r["ratings"]) for r in rs)
        sh = [int(r["ratings"]) / tot for r in rs] if tot else []
        sellers = defaultdict(int)
        for r in rs:
            sellers[r["seller"]] += int(r["ratings"])
        top_seller = max(sellers.items(), key=lambda x: x[1]) if sellers else ("", 0)
        top20 = rs[:20]
        out.append({
            "niche_id": nid, "store": store, "na": 0, "apps": len(rs),
            "players_1k": sum(1 for r in rs if int(r["ratings"]) >= 1000),
            "players_10k": sum(1 for r in rs if int(r["ratings"]) >= 10000),
            "ratings_total": tot, "top1": rs[0]["name"][:40] if rs else "", "top1_ratings": rs[0]["ratings"] if rs else "",
            "top1_share": round(sh[0], 3) if sh else "", "top3_share": round(sum(sh[:3]), 3) if sh else "",
            "hhi": round(sum(x * x for x in sh), 3) if sh else "",
            "new_12m": sum(1 for r in rs if r["release"] >= d12), "new_24m": sum(1 for r in rs if r["release"] >= d24),
            "new_12m_1k": sum(1 for r in rs if r["release"] >= d12 and int(r["ratings"]) >= 1000),
            "free_share_top20": round(sum(1 for r in top20 if float(r["price"]) == 0) / len(top20), 2) if top20 else "",
            "top_seller": top_seller[0][:30], "top_seller_share": round(top_seller[1] / tot, 3) if tot else "",
            "top5": " | ".join(f"{r['name'][:28]} ({int(r['ratings'])//1000}k)" for r in rs[:5]),
        })
        o = out[-1]
        print(f"{nid:34} {store} apps={o['apps']:3} >=1k={o['players_1k']:3} >=10k={o['players_10k']:3} top1={o['top1_share']:.0%} top3={o['top3_share']:.0%} new12={o['new_12m']:3} (>=1k {o['new_12m_1k']}) free={o['free_share_top20']} seller={o['top_seller'][:18]} {o['top_seller_share']:.0%} | {o['top1']}")
    keys = ["niche_id", "store", "na", "apps", "players_1k", "players_10k", "ratings_total", "top1", "top1_ratings", "top1_share",
            "top3_share", "hhi", "new_12m", "new_24m", "new_12m_1k", "free_share_top20", "top_seller", "top_seller_share", "top5"]
    with open(ws.out("appstore_metrics.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(out)
