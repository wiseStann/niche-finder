"""Merge every supply and demand signal per shortlisted niche into data/out/supply_deep.csv.

Inputs: metrics_quick.csv (S3), trends_deep.csv (S4), appstore_metrics.csv, capterra_categories_stats.csv,
shopify_metrics.csv, pricing_b2b_niche.csv, pricing_b2c_niche.csv, deals.csv. For Capterra the primary category (the first
in capterra_map) gives the concentration and the product counts of all categories are summed.
S5 gate "fragmentation by an independent signal": top1_share (by ratings/reviews) <= 0.5 and players >= 8
(B2C: 1k+ ratings; B2B: 100+ reviews). Niches with no measurable supply get gate NA; a Capterra category whose map note
says "broader" or "proxy" gets NA:proxy (supply is judged by hand in the passport). A source row without a top-1 share
(Capterra pages that did not parse, such as an anti-bot "Security Check" page) is no data: the niche falls back to the
other source, or gets NA:nodata. Until 2026-11-21 a missing share counted as 100 % and failed the gate.
A Capterra category whose paging a block page cut short has no shares either, only bounds (s5_capterra). It settles the
gate when the bounds do (top-1 share read so far <= 0.5 and players read so far >= 8 -> PASS; the unread products have
under 100 reviews each and fewer than 8 players were read -> FAIL:players), with `supply_partial` = 1, and is no data
otherwise. Its players and top-3 share stay empty, so the score gives them the neutral half-credit. `cap_stop` says why
Capterra paging ended.
Trend verdict: when the anchor's Google Trends verdict is DOWN or NA (or FLAT/UP and brands disagree), the brand queries
of the category (kind=brand rows, at least 2 with signal and mean_2024 >= 5) vote and may move it by one step.
"""
from __future__ import annotations

import argparse
import csv
import os

from nichefinder import niches
from nichefinder.workspace import Workspace

SUMMARY = "Merge all S3-S5 signals per shortlisted niche into supply_deep.csv with the S5 gate"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

TOP1_MAX, PLAYERS_MIN = 0.5, 8   # gate S5


def f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def capterra_bound(c: dict) -> str | None:
    """The S5 gate that the bounds of an incomplete Capterra category settle, or None."""
    if c.get("complete") != "0":
        return None
    smax, pmin, tail = f(c.get("top1_share_max")), f(c.get("products_100plus_min")), f(c.get("tail_reviews"))
    if smax is None or pmin is None:
        return None
    if smax <= TOP1_MAX and pmin >= PLAYERS_MIN:
        return "PASS"
    if tail is not None and tail < 100 and pmin < PLAYERS_MIN:   # every product with 100+ reviews has been read
        return "FAIL:players"
    return None


def run(ws: Workspace, args: argparse.Namespace) -> None:
    OUT = ws.out()

    def load(name, key="niche_id"):
        p = os.path.join(OUT, name)
        if not os.path.exists(p):
            print(f"  {name} not found - its columns stay empty")
            return {}
        d = {}
        for r in csv.DictReader(open(p, encoding="utf-8")):
            d.setdefault(r[key], r)
        return d

    def rows_of(name):
        p = os.path.join(OUT, name)
        if not os.path.exists(p):
            print(f"  {name} not found - its columns stay empty")
            return []
        return list(csv.DictReader(open(p, encoding="utf-8")))

    all_niches = {x["id"]: x for x in niches.load_niches(ws)}
    scope = niches.scope_ids(ws)   # a run profile merges only its own niches
    tiers = {}
    for tier, items in niches.shortlist(ws).items():
        if tier == "ru" or not isinstance(items, list):
            continue
        label = tier[5:].upper() if tier.startswith("tier_") else tier.upper()
        for it in items:
            nid = it["id"] if isinstance(it, dict) else it
            if scope is None or nid in scope:
                tiers[nid] = label
    cmap = ws.load_config("capterra_map.yaml", {}) or {}
    quick = load("metrics_quick.csv", "id")
    trends = {}   # the anchor row; if the anchor is NA and a broad phrase (kind=extra) has a verdict, take that one
    brand_rows = {}
    for r in rows_of("trends_deep.csv"):
        if r["kind"] == "brand":
            brand_rows.setdefault((r["niche_id"], r["lang"]), []).append(r)
            continue
        k = (r["niche_id"], r["lang"]); cur = trends.get(k)
        if cur is None or (cur.get("verdict") in ("NA", "") and r.get("verdict") not in ("NA", "")):
            trends[k] = r
    # Brand cross-check. A single broad "X software" query is unreliable (a one-off hump can make a category look like it
    # is declining): when the anchor/broad verdict is DOWN or NA and 2+ category brands (config/trends_brands.yaml) give a
    # signal (mean_2024 >= 5), the majority of the brands decides: broad DOWN + brands not DOWN -> FLAT; broad NA -> the
    # brands' verdict. Symmetrically, broad FLAT/UP + brands DOWN -> one step lower (FLAT->DOWN, UP->FLAT); brands UP never
    # lift broad to UP (growth must be visible in the category itself); a tie among brands -> FLAT. Marked kind=brands.
    for k, br in brand_rows.items():
        cur = trends.get(k)
        if cur is None:
            continue
        sig = [b for b in br if b.get("status") == "ok" and b.get("verdict") not in ("NA", "")]
        if len(sig) < 2:
            continue
        n_up = sum(1 for b in sig if b["verdict"] == "UP"); n_dn = sum(1 for b in sig if b["verdict"] == "DOWN")
        bv = "UP" if (n_up > n_dn and n_up * 2 >= len(sig)) else ("DOWN" if (n_dn > n_up and n_dn * 2 >= len(sig)) else "FLAT")
        cv = cur.get("verdict") or "NA"
        if cv in ("NA", ""):
            final = bv
        elif cv == "DOWN":
            final = "DOWN" if bv == "DOWN" else "FLAT"
        elif cv == "FLAT":
            final = "DOWN" if bv == "DOWN" else "FLAT"
        else:   # UP
            final = "FLAT" if bv == "DOWN" else "UP"
        if final == cv:
            continue
        merged = dict(cur); merged["verdict"] = final; merged["kind"] = "brands"
        merged["anchor"] = f"{cur.get('anchor')} -> brands {', '.join(b['anchor'] + ':' + b['verdict'] for b in sig)}"
        trends[k] = merged
    aps = {}
    for r in rows_of("appstore_metrics.csv"):
        aps[(r["niche_id"], r["store"])] = r
    cap = {}
    for r in rows_of("capterra_categories_stats.csv"):
        cap.setdefault(r["niche_id"], []).append(r)
    pb2b, pb2c, deals = load("pricing_b2b_niche.csv"), load("pricing_b2c_niche.csv"), load("deals.csv")
    shop = {}   # Shopify App Store: the primary subcategory (primary=1)
    for r in rows_of("shopify_metrics.csv"):
        if r["primary"] == "1":
            shop[r["niche_id"]] = r

    rows = []
    for nid, tier in tiers.items():
        n, q = all_niches[nid], quick.get(nid, {})
        t = trends.get((nid, "en"), {})
        a = aps.get((nid, "us"), {})
        c_list = cap.get(nid, [])
        c = c_list[0] if c_list else {}
        row = {
            "niche_id": nid, "tier": tier, "side": n["side"], "geo": n["geo"], "expertise_flag": n.get("expertise_flag", 0),
            # S3
            "demand_us": f(q.get("us_demand_cat")), "demand_2023": f(q.get("us_demand_2023")), "cpc": f(q.get("us_cpc_med")),
            "trend_kp": q.get("us_trend"), "yoy": f(q.get("us_yoy")), "yoy_pre": f(q.get("us_yoy_pre")), "gates_s3": q.get("us_gates"),
            "brand_top1": q.get("us_top1_brand"), "brand_top1_share": f(q.get("us_top1_brand_share")), "hhi_brand": f(q.get("us_hhi_brand")),
            "comp_idx": f(q.get("us_comp_idx")), "quick_score": f(q.get("us_quick_score")),
            # S4
            "trend_gt": t.get("verdict", "NA"), "gt_r_24_22": f(t.get("r_24_22")), "gt_mean_2024": f(t.get("mean_2024")),
            # App Store
            "as_na": int(a.get("na", "1") == "1") if a else 1,
            "as_players_1k": f(a.get("players_1k")), "as_players_10k": f(a.get("players_10k")), "as_top1": a.get("top1", ""),
            "as_top1_share": f(a.get("top1_share")), "as_top3_share": f(a.get("top3_share")), "as_hhi": f(a.get("hhi")),
            "as_new_12m": f(a.get("new_12m")), "as_new_12m_1k": f(a.get("new_12m_1k")), "as_free_top20": f(a.get("free_share_top20")),
            "as_top_seller": a.get("top_seller", ""), "as_top_seller_share": f(a.get("top_seller_share")),
            # Capterra
            "cap_slug": c.get("slug", ""), "cap_products_total": sum(int(x["products_total"] or 0) for x in c_list) if c_list else None,
            "cap_products_100": f(c.get("products_100plus")), "cap_products_10": f(c.get("products_10plus")),
            "cap_top1": c.get("top1", ""), "cap_top1_share": f(c.get("top1_share")), "cap_top3_share": f(c.get("top3_share")), "cap_hhi": f(c.get("hhi")),
            "cap_generic": c.get("generic_present", ""), "cap_note": (cmap.get(nid) or {}).get("note", ""), "cap_stop": c.get("stop", ""),
            # Shopify App Store
            "shop_cat": shop.get(nid, {}).get("category", ""), "shop_players_100": f(shop.get(nid, {}).get("players_100")),
            "shop_top1": shop.get(nid, {}).get("top1", ""), "shop_top1_share": f(shop.get(nid, {}).get("top1_share")), "shop_top3_share": f(shop.get(nid, {}).get("top3_share")),
            # pricing
            "b2b_median_monthly": f(pb2b.get(nid, {}).get("median_monthly_usd")), "b2b_price_public": f(pb2b.get(nid, {}).get("price_public_share")),
            "b2b_under100": f(pb2b.get(nid, {}).get("under_100_share")), "b2b_trial": f(pb2b.get(nid, {}).get("free_trial_share")), "b2b_free": f(pb2b.get(nid, {}).get("free_version_share")),
            "b2c_monetized": f(pb2c.get(nid, {}).get("monetized_share")), "b2c_median_monthly": f(pb2c.get(nid, {}).get("median_monthly")),
            "b2c_median_yearly": f(pb2c.get(nid, {}).get("median_yearly")), "b2c_with_monthly": f(pb2c.get(nid, {}).get("with_monthly")), "b2c_n": f(pb2c.get(nid, {}).get("n")),
            # deals
            "ph_12m": f(deals.get(nid, {}).get("ph_launches_12m")), "yc": f(deals.get(nid, {}).get("yc_companies")), "tinyseed": f(deals.get(nid, {}).get("tinyseed")),
            "topgross_us": f(deals.get(nid, {}).get("topgrossing_us")), "topgross_ru": f(deals.get(nid, {}).get("topgrossing_ru")),
        }
        # independent concentration: App Store for b2c/prosumer, Capterra for b2b; if both exist, the one matching the side
        # a Capterra row without a top-1 share means its pages did not parse (a "Security Check" page): no data
        has_cap = bool(c) and row["cap_top1_share"] is not None
        cap_bound = capterra_bound(c) if c and not has_cap else None
        has_cap = has_cap or cap_bound is not None
        use_as = row["as_na"] == 0 and n["side"] in ("b2c", "prosumer")
        use_cap = has_cap and n["side"].startswith("b2b")
        if not use_as and not use_cap:   # fallback: whatever is available
            use_as, use_cap = row["as_na"] == 0, has_cap and not (row["as_na"] == 0)
        if nid in shop:   # Shopify niches: apps.shopify.com is the only direct supply signal
            row["supply_src"], row["supply_top1_share"], row["supply_top3_share"], row["supply_players"], row["supply_top1"] = "shopify", row["shop_top1_share"], row["shop_top3_share"], row["shop_players_100"], row["shop_top1"]
        elif use_as:
            row["supply_src"], row["supply_top1_share"], row["supply_top3_share"], row["supply_players"], row["supply_top1"] = "appstore", row["as_top1_share"], row["as_top3_share"], row["as_players_1k"], row["as_top1"]
        elif use_cap:
            row["supply_src"], row["supply_top1_share"], row["supply_top3_share"], row["supply_players"], row["supply_top1"] = "capterra", row["cap_top1_share"], row["cap_top3_share"], row["cap_products_100"], row["cap_top1"]
        else:
            row["supply_src"], row["supply_top1_share"], row["supply_top3_share"], row["supply_players"], row["supply_top1"] = "na", None, None, None, ""
        row["supply_partial"] = int(row["supply_src"] == "capterra" and cap_bound is not None)
        note = row["cap_note"].lower()
        if row["supply_src"] == "na":
            row["gate_s5"] = "NA"
        elif row["supply_src"] == "capterra" and ("proxy" in note or "broader" in note):
            row["gate_s5"] = "NA:proxy"   # the Capterra category does not match the niche - supply is judged by hand in the passport
        elif row["supply_partial"]:
            row["gate_s5"] = cap_bound   # settled by the bounds of an incomplete category; players and top-3 stay unmeasured
        elif row["supply_top1_share"] is None:
            row["gate_s5"] = "NA:nodata"   # the source has no concentration for this niche: missing data is not a failed gate
        else:
            ok = (row["supply_top1_share"] or 1) <= TOP1_MAX and (row["supply_players"] or 0) >= PLAYERS_MIN
            row["gate_s5"] = "PASS" if ok else ("FAIL:top1" if (row["supply_top1_share"] or 1) > TOP1_MAX else "FAIL:players")
        rows.append(row)
        cap_off = ""
        if c and row["cap_stop"] not in ("", "end", "cap"):
            cap_off = f" | Capterra {row['cap_stop']}, " + ("gate from bounds" if row["supply_partial"] else "no data" if not has_cap else "not used")
        print(f"{tier} {nid:34} {row['supply_src']:8} top1={row['supply_top1_share'] if row['supply_top1_share'] is not None else '-'} players={row['supply_players']} -> {row['gate_s5']:12} | GT={row['trend_gt']} KP={row['trend_kp']}{cap_off}")
    if not rows:
        print("empty shortlist - nothing written")
        return
    keys = list(rows[0].keys())
    with open(ws.out("supply_deep.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    print("-> data/out/supply_deep.csv", len(rows))
