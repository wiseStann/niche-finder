"""Deals, launches and monetization signals: match the S0 corpora to shortlisted niches by regex.

Corpora (data/raw, written by the S0 stages): Flippa SaaS listings for sale (with revenue), Product Hunt launches,
YC companies, TinySeed portfolio, App Store top-grossing apps (us/ru). A missing corpus is skipped with a message.
Niches are matched by the regexes in config/deal_keywords.yaml (a string, or {re, not} to drop neighbouring categories);
shortlisted niches without an entry fall back to the phrases of config/coverage_keywords.yaml.
Outputs: data/out/deals.csv (aggregate per niche) and data/out/deals_matches.csv (what exactly matched, for review).
"""
from __future__ import annotations

import argparse
import csv
import re

from nichefinder import niches
from nichefinder.workspace import Workspace

SUMMARY = "Deal and launch signals per niche: Flippa, Product Hunt, YC, TinySeed, top-grossing apps"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def num(v) -> float:
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except ValueError:
        return 0.0


def run(ws: Workspace, args: argparse.Namespace) -> None:
    def load(name: str) -> list[dict]:
        p = ws.raw(name)
        if not p.is_file():
            print(f"  {name} not found - skipped (run the matching S0 stage)")
            return []
        return list(csv.DictReader(open(p, encoding="utf-8")))

    kw = ws.load_config("deal_keywords.yaml", {}) or {}
    # shortlisted niches without deal keywords: coverage phrases as a word-boundary regex
    cov = ws.load_config("coverage_keywords.yaml", {}) or {}
    for nid in niches.shortlist_ids(ws):
        if nid not in kw and cov.get(nid):
            kw[nid] = r"(?<![a-zа-яё0-9])(" + "|".join(re.escape(str(t).lower()) for t in cov[nid]) + ")"
    rx, neg = {}, {}
    for nid, p in kw.items():
        if isinstance(p, dict):
            rx[nid] = re.compile(p["re"], re.I); neg[nid] = re.compile(p["not"], re.I) if p.get("not") else None
        else:
            rx[nid] = re.compile(p, re.I); neg[nid] = None
    flippa, ph, yc, ts, top = load("flippa_saas.csv"), load("ph_top.csv"), load("yc_companies.csv"), load("tinyseed_portfolio.csv"), load("appstore_top.csv")
    if not (flippa or ph or yc or ts or top):
        print("no S0 corpora found in data/raw - nothing written")
        return
    out, matches = [], []
    for nid, r0 in rx.items():
        n0 = neg[nid]
        r = type("R", (), {"search": staticmethod(lambda t, r0=r0, n0=n0: r0.search(t) and not (n0 and n0.search(t)))})
        f = [x for x in flippa if r.search(f"{x['title']} {x['summary']}")]
        f_rev = [x for x in f if num(x["revenue_average"]) > 0]
        p = [x for x in ph if r.search(f"{x['name']} {x['tagline']}")]
        y = [x for x in yc if r.search(f"{x['name']} {x['one_liner']}") and x.get("excluded") != "1"]
        t = [x for x in ts if r.search(f"{x['name']} {x['excerpt']}")]
        g_us = [x for x in top if x["country"] == "us" and r.search(f"{x['name']} {x['summary'][:300]}")]
        g_ru = [x for x in top if x["country"] == "ru" and r.search(f"{x['name']} {x['summary'][:300]}")]
        rev = sorted((num(x["revenue_average"]) for x in f_rev), reverse=True)
        out.append({
            "niche_id": nid, "flippa_listings": len(f), "flippa_with_revenue": len(f_rev),
            "flippa_max_mrr": int(rev[0]) if rev else "", "flippa_median_mrr": int(rev[len(rev) // 2]) if rev else "",
            "ph_launches_12m": len(p), "yc_companies": len(y), "tinyseed": len(t),
            "topgrossing_us": len({x["app_id"] for x in g_us}), "topgrossing_ru": len({x["app_id"] for x in g_ru}),
        })
        for src, items, key in (("flippa", f, "title"), ("ph", p, "name"), ("yc", y, "name"), ("tinyseed", t, "name"), ("topgross_us", g_us, "name"), ("topgross_ru", g_ru, "name")):
            for x in items:
                matches.append({"niche_id": nid, "source": src, "name": x[key][:80], "extra": (x.get("revenue_average") or x.get("tagline") or x.get("one_liner") or x.get("genre") or "")[:80]})
        o = out[-1]
        print(f"{nid:34} flippa={o['flippa_listings']:2} (rev {o['flippa_with_revenue']}, max MRR {o['flippa_max_mrr']}) ph={o['ph_launches_12m']:2} yc={o['yc_companies']:2} ts={o['tinyseed']} topgross us={o['topgrossing_us']:2} ru={o['topgrossing_ru']:2}")
    if not out:
        print("no niches with deal keywords - nothing written")
        return
    with open(ws.out("deals.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    with open(ws.out("deals_matches.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["niche_id", "source", "name", "extra"]); w.writeheader(); w.writerows(matches)
