"""Shopify App Store supply: review concentration per niche subcategory.

Share = app reviews / total reviews of the subcategory; players = apps with 100+ reviews; free_share = share of apps with
a free plan. Horizontal apps (page builders, subscriptions, reviews...) are excluded per config/shopify_generic.yaml.
Inputs: data/raw/shopify_apps.csv (s0_shopify), config/shopify_map.yaml (niche -> subcategories; the first is primary).
Output: data/out/shopify_metrics.csv.
"""
from __future__ import annotations

import argparse
import csv

from nichefinder.workspace import Workspace

SUMMARY = "Shopify App Store concentration per niche subcategory"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def run(ws: Workspace, args: argparse.Namespace) -> None:
    src = ws.raw("shopify_apps.csv")
    if not src.is_file():
        print(f"{src} not found - run s0_shopify first; skipping")
        return
    smap = ws.load_config("shopify_map.yaml", {})
    generic = ws.load_config("shopify_generic.yaml", {}) or {}
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    out = []
    for nid, cats in smap.items():
        for i, c in enumerate(cats or []):
            apps = {}
            for r in rows:
                if r["category"] == c and not (r["handle"] in generic and (not generic[r["handle"]] or c in generic[r["handle"]])):
                    apps[r["handle"]] = r
            lst = sorted(apps.values(), key=lambda r: -int(r["reviews"] or 0))
            rv = [int(r["reviews"] or 0) for r in lst]
            tot = sum(rv) or 1
            hhi = sum((x / tot) ** 2 for x in rv)
            free = sum(1 for r in lst if "free" in r["pricing"].lower()) / max(len(lst), 1)
            out.append({"niche_id": nid, "category": c, "primary": int(i == 0), "apps": len(lst), "players_100": sum(1 for x in rv if x >= 100),
                        "players_1k": sum(1 for x in rv if x >= 1000), "reviews_total": tot, "top1_share": round(rv[0] / tot, 3) if rv else "",
                        "top3_share": round(sum(rv[:3]) / tot, 3) if rv else "", "hhi": round(hhi, 3), "free_share": round(free, 2),
                        "top1": lst[0]["name"] if lst else "", "top3": " | ".join(r["name"] for r in lst[:3])})
            t1 = out[-1]["top1_share"]
            t3 = out[-1]["top3_share"]
            print(f"{nid:34} {c[-40:]:40} apps={len(lst):>3} >=100={out[-1]['players_100']:>3} top1={t1 if t1 == '' else format(t1, '.0%')} top3={t3 if t3 == '' else format(t3, '.0%')} free={free:.0%} | {out[-1]['top1'][:35]}")
    if not out:
        print("no subcategories configured - nothing written")
        return
    p = ws.out("shopify_metrics.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    print("->", p, len(out))
