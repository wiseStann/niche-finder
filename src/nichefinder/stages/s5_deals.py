"""Deals, launches and monetization signals: match the S0 corpora to shortlisted niches by regex.

Corpora (data/raw, written by the S0 stages): Product Hunt launches, YC companies, TinySeed portfolio, App Store
top-grossing apps (us/ru), BetaList pre-launch startups, Product Radar (Russian-language launches), Kickstarter projects,
Empire Flippers listings with a verified P&L (software listings only, all years, for sale and sold), TrustMRR startups
with payment-provider-verified revenue (s0_trustmrr; only rows with revenue in the last 30 days or MRR above zero). A
missing corpus is skipped with a message.
Niches are matched by the regexes in config/deal_keywords.yaml (a string, or {re, not} to drop neighbouring categories);
shortlisted niches without an entry fall back to the phrases of config/coverage_keywords.yaml (niches.text_matchers).
Product Radar text is Russian, so it is matched with the coverage phrases as well as the (English) regexes.
BetaList, Product Radar and Kickstarter are counted over the last 12 months of ws.today; Empire Flippers over all years,
because it has about ten software listings a year; TrustMRR is a snapshot of the fetch month (revenue of the last 30
days, MRR, asking price), matched on name and description.

The score's deals component (s6_score) reads only the Product Hunt, YC, TinySeed and top-grossing columns; the BetaList,
Product Radar, Kickstarter, Empire Flippers and TrustMRR columns are shown in the passports and do not change the score.
TrustMRR columns: trustmrr_n (matched paying startups), trustmrr_mrr_sum / trustmrr_mrr_median (USD, over the matched),
trustmrr_rev30_sum (USD, revenue of the last 30 days), trustmrr_for_sale (matched startups listed for sale). The keyless
TrustMRR snapshot holds about 1,000 top earners, so a zero there means "no proven top earner", not "no revenue".
Outputs: data/out/deals.csv (aggregate per niche) and data/out/deals_matches.csv (what exactly matched, for review).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import statistics

from nichefinder import niches
from nichefinder.workspace import Workspace

SUMMARY = "Deal and launch signals per niche: Product Hunt, YC, TinySeed, top-grossing apps, BetaList, Product Radar, Kickstarter, Empire Flippers, TrustMRR"
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
    ph, yc, ts, top = load("ph_top.csv"), load("yc_companies.csv"), load("tinyseed_portfolio.csv"), load("appstore_top.csv")
    ef = [x for x in load("ef_listings.csv") if x["kind"] == "software"]
    since = (ws.today - dt.timedelta(days=365)).isoformat()
    today = ws.today.isoformat()
    bl = [x for x in load("betalist.csv") if since <= x["date"] <= today]
    pr = [x for x in load("productradar.csv") if since[:7] < x["month"] <= today[:7]]
    ks = [x for x in load("kickstarter_projects.csv") if since <= x["launched"] <= today]
    tm = [x for x in load("trustmrr.csv") if num(x["revenue_30d"] or 0) > 0 or num(x["mrr"] or 0) > 0]
    if not (ph or yc or ts or top or bl or pr or ks or ef or tm):
        print("no S0 corpora found in data/raw - nothing written")
        return
    out, matches = [], []
    for nid, hit in mx.items():
        hit_ru = mx_ru[nid]
        p = [x for x in ph if hit(f"{x['name']} {x['tagline']}")]
        y = [x for x in yc if hit(f"{x['name']} {x['one_liner']}") and x.get("excluded") != "1"]
        t = [x for x in ts if hit(f"{x['name']} {x['excerpt']}")]
        g_us = [x for x in top if x["country"] == "us" and hit(f"{x['name']} {x['summary'][:300]}")]
        g_ru = [x for x in top if x["country"] == "ru" and hit(f"{x['name']} {x['summary'][:300]}")]
        b = [x for x in bl if hit(f"{x['name']} {x['tagline']}")]
        r = [x for x in pr if hit_ru(f"{x['name']} {x['description']} {x['categories']}")]
        k = [x for x in ks if hit(f"{x['name']} {x['blurb']}")]
        k_ok = [x for x in k if x["state"] == "successful"]
        e = [x for x in ef if hit(f"{x['public_title']} {x['summary']} {x['niches'].replace('|', ' ')}")]
        e_profit = [num(x["monthly_net_profit"]) for x in e if x["monthly_net_profit"] != ""]
        e_mult = [num(x["listing_multiple"]) for x in e if num(x["listing_multiple"]) > 0]
        m = sorted((x for x in tm if hit(f"{x['name']} {x['description']}")), key=lambda x: -num(x["revenue_30d"] or 0))
        m_mrr = [num(x["mrr"] or 0) for x in m]
        out.append({
            "niche_id": nid, "ph_launches_12m": len(p), "yc_companies": len(y), "tinyseed": len(t),
            "topgrossing_us": len({x["app_id"] for x in g_us}), "topgrossing_ru": len({x["app_id"] for x in g_ru}),
            "betalist_12m": len(b), "productradar_12m": len(r),
            "kickstarter_12m": len(k), "kickstarter_success_12m": len(k_ok),
            "kickstarter_pledged_12m": int(sum(num(x["pledged_usd"]) for x in k_ok)),
            "ef_software": len(e), "ef_software_sold": sum(1 for x in e if x["listing_status"] in ("Sold", "Pending Sold")),
            "ef_median_profit": int(statistics.median(e_profit)) if e_profit else "",
            "ef_median_multiple": round(statistics.median(e_mult)) if e_mult else "",
            "trustmrr_n": len(m), "trustmrr_mrr_sum": int(sum(m_mrr)),
            "trustmrr_mrr_median": int(statistics.median(m_mrr)) if m_mrr else "",
            "trustmrr_rev30_sum": int(sum(num(x["revenue_30d"] or 0) for x in m)),
            "trustmrr_for_sale": sum(1 for x in m if x["on_sale"] == "1"),
        })
        for src, items, key in (("ph", p, "name"), ("yc", y, "name"), ("tinyseed", t, "name"), ("topgross_us", g_us, "name"),
                                ("topgross_ru", g_ru, "name"), ("betalist", b, "name"), ("productradar", r, "name"),
                                ("kickstarter", sorted(k, key=lambda x: -num(x["pledged_usd"])), "name"),
                                ("ef", sorted(e, key=lambda x: x["first_listed_at"], reverse=True), "public_title"),
                                ("trustmrr", m, "name")):
            for x in items:
                extra = (x.get("tagline") or x.get("one_liner") or x.get("genre") or x.get("description") or "")
                if src == "kickstarter":
                    extra = f"{x['state']}, ${num(x['pledged_usd']):,.0f}, {x['backers']} backers"
                elif src == "ef":
                    extra = f"{x['listing_status']} {x['first_listed_at'][:7]}, ${num(x['monthly_net_profit']):,.0f}/mo profit, {x['listing_multiple']}x"
                elif src == "trustmrr":
                    extra = (f"${num(x['mrr'] or 0):,.0f} MRR, ${num(x['revenue_30d'] or 0):,.0f}/30d"
                             + (f", for sale ${num(x['asking_price']):,.0f}" if x["on_sale"] == "1" and x["asking_price"] else ""))
                matches.append({"niche_id": nid, "source": src, "name": x[key][:80], "extra": extra[:80]})
        o = out[-1]
        print(f"{nid:34} ph={o['ph_launches_12m']:2} yc={o['yc_companies']:2} ts={o['tinyseed']} "
              f"topgross us={o['topgrossing_us']:2} ru={o['topgrossing_ru']:2} betalist={o['betalist_12m']:2} pradar={o['productradar_12m']:2} kickstarter={o['kickstarter_12m']:2} (ok {o['kickstarter_success_12m']}) "
              f"ef={o['ef_software']} (sold {o['ef_software_sold']}) trustmrr={o['trustmrr_n']}")
    if not out:
        print("no niches with deal keywords - nothing written")
        return
    with open(ws.out("deals.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    with open(ws.out("deals_matches.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["niche_id", "source", "name", "extra"]); w.writeheader(); w.writerows(matches)
