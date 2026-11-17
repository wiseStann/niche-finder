"""Deals, launches and monetization signals: match the S0 corpora to shortlisted niches by regex.

Corpora (data/raw, written by the S0 stages): Flippa SaaS listings for sale (with revenue), Product Hunt launches,
YC companies, TinySeed portfolio, App Store top-grossing apps (us/ru), BetaList pre-launch startups, Product Radar
(Russian-language launches), Kickstarter projects. A missing corpus is skipped with a message.
Niches are matched by the regexes in config/deal_keywords.yaml (a string, or {re, not} to drop neighbouring categories);
shortlisted niches without an entry fall back to the phrases of config/coverage_keywords.yaml (niches.text_matchers).
Product Radar text is Russian, so it is matched with the coverage phrases as well as the (English) regexes.
BetaList, Product Radar and Kickstarter are counted over the last 12 months of ws.today.

The score's deals component (s6_score) reads only the Flippa, Product Hunt, YC, TinySeed and top-grossing columns;
the BetaList, Product Radar and Kickstarter columns are shown in the passports and do not change the score.
Outputs: data/out/deals.csv (aggregate per niche) and data/out/deals_matches.csv (what exactly matched, for review).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt

from nichefinder import niches
from nichefinder.workspace import Workspace

SUMMARY = "Deal and launch signals per niche: Flippa, Product Hunt, YC, TinySeed, top-grossing apps, BetaList, Product Radar, Kickstarter"
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

    mx = niches.text_matchers(ws)
    mx_ru = niches.text_matchers(ws, with_coverage=True)
    flippa, ph, yc, ts, top = load("flippa_saas.csv"), load("ph_top.csv"), load("yc_companies.csv"), load("tinyseed_portfolio.csv"), load("appstore_top.csv")
    since = (ws.today - dt.timedelta(days=365)).isoformat()
    today = ws.today.isoformat()
    bl = [x for x in load("betalist.csv") if since <= x["date"] <= today]
    pr = [x for x in load("productradar.csv") if since[:7] < x["month"] <= today[:7]]
    ks = [x for x in load("kickstarter_projects.csv") if since <= x["launched"] <= today]
    if not (flippa or ph or yc or ts or top or bl or pr or ks):
        print("no S0 corpora found in data/raw - nothing written")
        return
    out, matches = [], []
    for nid, hit in mx.items():
        hit_ru = mx_ru[nid]
        f = [x for x in flippa if hit(f"{x['title']} {x['summary']}")]
        f_rev = [x for x in f if num(x["revenue_average"]) > 0]
        p = [x for x in ph if hit(f"{x['name']} {x['tagline']}")]
        y = [x for x in yc if hit(f"{x['name']} {x['one_liner']}") and x.get("excluded") != "1"]
        t = [x for x in ts if hit(f"{x['name']} {x['excerpt']}")]
        g_us = [x for x in top if x["country"] == "us" and hit(f"{x['name']} {x['summary'][:300]}")]
        g_ru = [x for x in top if x["country"] == "ru" and hit(f"{x['name']} {x['summary'][:300]}")]
        b = [x for x in bl if hit(f"{x['name']} {x['tagline']}")]
        r = [x for x in pr if hit_ru(f"{x['name']} {x['description']} {x['categories']}")]
        k = [x for x in ks if hit(f"{x['name']} {x['blurb']}")]
        k_ok = [x for x in k if x["state"] == "successful"]
        rev = sorted((num(x["revenue_average"]) for x in f_rev), reverse=True)
        out.append({
            "niche_id": nid, "flippa_listings": len(f), "flippa_with_revenue": len(f_rev),
            "flippa_max_mrr": int(rev[0]) if rev else "", "flippa_median_mrr": int(rev[len(rev) // 2]) if rev else "",
            "ph_launches_12m": len(p), "yc_companies": len(y), "tinyseed": len(t),
            "topgrossing_us": len({x["app_id"] for x in g_us}), "topgrossing_ru": len({x["app_id"] for x in g_ru}),
            "betalist_12m": len(b), "productradar_12m": len(r),
            "kickstarter_12m": len(k), "kickstarter_success_12m": len(k_ok),
            "kickstarter_pledged_12m": int(sum(num(x["pledged_usd"]) for x in k_ok)),
        })
        for src, items, key in (("flippa", f, "title"), ("ph", p, "name"), ("yc", y, "name"), ("tinyseed", t, "name"), ("topgross_us", g_us, "name"),
                                ("topgross_ru", g_ru, "name"), ("betalist", b, "name"), ("productradar", r, "name"),
                                ("kickstarter", sorted(k, key=lambda x: -num(x["pledged_usd"])), "name")):
            for x in items:
                extra = (x.get("revenue_average") or x.get("tagline") or x.get("one_liner") or x.get("genre") or x.get("description") or "")
                if src == "kickstarter":
                    extra = f"{x['state']}, ${num(x['pledged_usd']):,.0f}, {x['backers']} backers"
                matches.append({"niche_id": nid, "source": src, "name": x[key][:80], "extra": extra[:80]})
        o = out[-1]
        print(f"{nid:34} flippa={o['flippa_listings']:2} (rev {o['flippa_with_revenue']}, max MRR {o['flippa_max_mrr']}) ph={o['ph_launches_12m']:2} yc={o['yc_companies']:2} ts={o['tinyseed']} "
              f"topgross us={o['topgrossing_us']:2} ru={o['topgrossing_ru']:2} betalist={o['betalist_12m']:2} pradar={o['productradar_12m']:2} kickstarter={o['kickstarter_12m']:2} (ok {o['kickstarter_success_12m']})")
    if not out:
        print("no niches with deal keywords - nothing written")
        return
    with open(ws.out("deals.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    with open(ws.out("deals_matches.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["niche_id", "source", "name", "extra"]); w.writeheader(); w.writerows(matches)
