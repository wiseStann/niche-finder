"""Bottom-up ceiling and path-to-goal grade for every niche that is not red.

For each green / yellow niche: how many payers are needed to reach the low and high net-profit goals (nf.yaml `goal`) at
competitor prices, how many payers the niche has at all (App Store rating velocity, Capterra / Shopify reviews, or search
volume as a last resort), what share of the niche that means ("leader / top-3 / top-10 / one of many"), and a grade A/B/B-/C
that combines the share, the ticket tier and founder fit. Score weights are untouched.

Inputs: data/out/score_final.csv, supply_deep.csv; optional appstore_velocity.csv, capterra_categories_stats.csv,
shopify_metrics.csv, offsearch.csv (S8), score_ru.csv; config/ceiling.yaml (assumptions), nf.yaml (`goal`, `default_fit`),
config/overrides.yaml per niche: `fit` (0-3) + `fit_note`, `size_override` (payers in the niche, for niches with no
App Store / Capterra / Shopify proxy) + `size_note`, `excluded: true`.
Output: data/out/path_to_goal.csv and reports/S6-path-to-goal.md. Free, no network.
"""
from __future__ import annotations

import argparse
import csv
import re

from nichefinder import niches as nf_niches
from nichefinder.workspace import Workspace

SUMMARY = "Bottom-up ceiling and path-to-goal grade (A/B/B-/C)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def rd(ws, name, key="niche_id", pred=None):
    p = ws.out(name)
    if not p.is_file():
        return {}
    return {r[key]: r for r in csv.DictReader(open(p, encoding="utf-8")) if pred is None or pred(r)}


def price_from_product(text):
    """'$5-15/month' -> 10; '$50-100/year' -> 6.25; '$2-5/employee/month' -> 3.5 (per-unit prices understate ARPU, flagged by the caller)."""
    m = re.search(r"\$\s*(\d+(?:[.,]\d+)?)(?:\s*[–-]\s*(\d+(?:[.,]\d+)?))?\s*(?:/|\s*за\s*|\s*per\s*)?([^\s,;]*)", text or "")
    if not m:
        return None, ""
    a = float(m.group(1).replace(",", "."))
    b = float(m.group(2).replace(",", ".")) if m.group(2) else a
    mid = (a + b) / 2
    unit = (m.group(3) or "").lower()
    if "год" in unit or "year" in unit:
        return mid / 12, "from product (annual)"
    return mid, "from product"


def position(share, th):
    if share is None:
        return "—"
    if share > th["leader"]:
        return "leader"
    if share > th["top3"]:
        return "top-3"
    if share > th["top10"]:
        return "top-10"
    return "one of many"


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = ws.load_config("ceiling.yaml")
    ov = nf_niches.overrides(ws)
    niches = {x["id"]: x for x in nf_niches.load_niches(ws)}
    score = rd(ws, "score_final.csv")
    if not score:
        raise SystemExit(f"{ws.out('score_final.csv')} not found - run s6_score first")
    supply = rd(ws, "supply_deep.csv")
    vel = rd(ws, "appstore_velocity.csv", pred=lambda r: r["store"] == "us")
    cap = rd(ws, "capterra_categories_stats.csv")
    shop = rd(ws, "shopify_metrics.csv", pred=lambda r: r.get("primary") in ("1", "True", "true"))
    off = rd(ws, "offsearch.csv")
    has_ru = ws.out("score_ru.csv").is_file()
    ru = rd(ws, "score_ru.csv")
    g = ws.setting("goal") or {}
    cur = g.get("currency", "USD")
    upu = float(g.get("units_per_usd", 1.0))
    net_low, net_high = float(g.get("net_month_low", 60000)), float(g.get("net_month_high", 120000))
    margin = float(g.get("net_margin", 0.40))
    default_fit = int(ws.setting("default_fit", 1))
    rev_low = net_low / upu / margin      # $/month of revenue
    rev_high = net_high / upu / margin
    rows = []
    for nid, s in score.items():
        if s["verdict"] == "red":
            continue
        sp, x = supply[nid], niches[nid]
        o = ov.get(nid) or {}
        b2c = s["side"] in ("b2c", "prosumer")
        notes = []
        # --- price
        pm = f(sp["b2c_median_monthly"]) if b2c else f(sp["b2b_median_monthly"])
        src_price = "App Store IAP" if b2c else "GetApp"
        if "S5:manual" in (s.get("flags") or ""):   # the Capterra category is only a proxy: take the price from the niche's product description
            pm = None
        if not pm:
            pm, src_price = price_from_product(x.get("product", ""))
            if pm is None:
                pm, src_price = (8.0 if b2c else 50.0), "default"
            prod = x.get("product") or ""
            if "сотрудник" in prod or "экран" in prod or "per unit" in prod or "employee" in prod or "screen" in prod or "per seat" in prod:
                notes.append("price is per unit (employee/screen) - ARPU understated")
        if b2c:
            c = cfg["b2c"]
            arpu = pm * c["annual_discount"] * (1 - c["store_fee"])
        else:
            c = cfg["b2b"]
            arpu = pm * (1 - c["payment_fee"])
        need_low, need_high = rev_low / arpu, rev_high / arpu
        # --- niche size in payers
        size, proxy = None, ""
        if b2c:
            v = f((vel.get(nid) or {}).get("vel_total_pm"))
            if v:
                installs_pm = v * c["installs_per_rating_ios"] * c["android_multiplier"]
                size = installs_pm * c["install_to_paid"] * c["paid_lifetime_months"]
                proxy = f"App Store: {v:,.0f} ratings/month × {c['installs_per_rating_ios']} × {c['android_multiplier']:.0f} platforms × {c['install_to_paid']:.0%} × {c['paid_lifetime_months']} months"
            gp = f((off.get(nid) or {}).get("gp_us_new24_installs"))
            if gp:
                notes.append(f"Google Play US: apps released in the last 24 months gain {gp/24:,.0f} installs/month")
        else:
            src = sp.get("supply_src")
            if src == "shopify" and shop.get(nid):
                rv = f(shop[nid].get("reviews_total"))
                if rv:
                    size = rv * c["customers_per_review_shopify"]
                    proxy = f"Shopify: {rv:,.0f} subcategory reviews × {c['customers_per_review_shopify']}"
            elif cap.get(nid) and "S5:manual" not in (s.get("flags") or ""):   # proxy category (not the niche itself) -> search proxy
                rv = f(cap[nid].get("reviews_niche")) or f(cap[nid].get("reviews_total"))
                if rv:
                    size = rv * c["customers_per_review"]
                    proxy = f"Capterra: {rv:,.0f} reviews × {c['customers_per_review']}"
            if size is None:
                d = f(sp.get("demand_us"), 0)
                if d:
                    size = d * 12 * c["search_to_customer"]
                    proxy = f"search: {d:,.0f}/month × 12 × {c['search_to_customer']:.0%} (proxy - no Capterra category)"
                    notes.append("size from search is the roughest proxy")
        if o.get("size_override"):
            size, proxy = float(o["size_override"]), f"manual estimate - {o.get('size_note', '')}"
        elif "S5:manual" in (s.get("flags") or "") and size:
            notes.append("lower bound: the category is not bought through Google, so the search proxy understates it")
        share_low = need_low / size if size else None
        share_high = need_high / size if size else None
        th = c["position_thresholds"]
        pos_low, pos_high = position(share_low, th), position(share_high, th)
        # --- path-to-goal grade
        tier = "<50" if pm < 50 else ("50-250" if pm < 250 else ">250")   # ticket tier by the price used here
        fit = int(o.get("fit", default_fit))
        excluded = bool(o.get("excluded"))
        gr = cfg["grade"]
        if excluded:
            grade = "—"
        elif share_low is None:
            grade = "?"
        elif fit == 0:
            grade = "C"          # outside the team's competence - the path to the goal is not through a product
        elif share_low <= gr["a_max_share"] and tier in gr["a_ticket_tiers"] and fit >= gr["a_min_fit"]:
            grade = "A"
        elif share_low <= gr["b_max_share"] and (tier in gr["a_ticket_tiers"] or fit >= gr["a_min_fit"]):
            grade = "B"
        elif share_low <= gr["b_max_share"]:
            grade = "B-"
        else:
            grade = "C"
        row = {
            "niche_id": nid, "verdict": s["verdict"], "score": s["score"], "side": s["side"],
            "price_month": round(pm, 2), "price_src": src_price, "arpu_net": round(arpu, 2),
            "payers_low": round(need_low), "payers_high": round(need_high),
            "niche_payers_est": round(size) if size else None, "size_proxy": proxy,
            "share_low": round(share_low, 3) if share_low is not None else None,
            "share_high": round(share_high, 3) if share_high is not None else None,
            "position_low": pos_low, "position_high": pos_high,
            "ticket_tier": tier, "founder_fit": fit, "founder_fit_why": o.get("fit_note", ""),
        }
        if has_ru:
            row["ru_verdict"] = (ru.get(nid) or {}).get("verdict", "")
        row.update({"grade": grade, "notes": "; ".join(notes)})
        rows.append(row)
    if not rows:
        print("no green / yellow niches - nothing to write")
        return
    rows.sort(key=lambda r: ({"A": 0, "B": 1, "B-": 2, "C": 3, "?": 4, "—": 5}[r["grade"]], -float(r["score"])))
    p = ws.out("path_to_goal.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("->", p)
    write_report(ws, rows, cfg, niches, cur, net_low, net_high, upu, margin, rev_low, rev_high)


def write_report(ws, rows, cfg, niches, cur, net_low, net_high, upu, margin, rev_low, rev_high):
    b, c = cfg["b2c"], cfg["b2b"]
    V = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    ru_col = "ru_verdict" in rows[0]
    L = ["# Ceiling and path to goal", "",
         f"Goal: {net_low:,.0f}–{net_high:,.0f} {cur}/month net = ${net_low/upu/1e3:,.0f}–{net_high/upu/1e3:,.0f}K/month at {upu:g} {cur}/$ → at a "
         f"{margin:.0%} net margin the revenue needed is **${rev_low/1e3:,.0f}K–{rev_high/1e3:,.0f}K/month (${rev_low*12/1e6:.1f}–{rev_high*12/1e6:.1f}M ARR)**.",
         "", "**How it is computed (all coefficients are in `config/ceiling.yaml`; order of magnitude, not a forecast):**",
         f"- B2C: ARPU = median monthly competitor price (IAP) × {b['annual_discount']} (annual plans) × (1 − {b['store_fee']:.0%} store fee). "
         f"Payers in the niche = App Store ratings/month × {b['installs_per_rating_ios']} installs per rating × {b['android_multiplier']:.0f} (Android) × {b['install_to_paid']:.0%} conversion × {b['paid_lifetime_months']} months of payer lifetime.",
         f"- B2B: ARPU = median starting price (GetApp) × (1 − {c['payment_fee']:.0%}). Customers in the niche = Capterra reviews × {c['customers_per_review']} "
         f"(Shopify × {c['customers_per_review_shopify']}); without a category, search demand × 12 × {c['search_to_customer']:.0%}.",
         f"- Position: share of the niche's payers needed for the goal: > {b['position_thresholds']['leader']:.0%} leader; > {b['position_thresholds']['top3']:.0%} top-3; "
         f"> {b['position_thresholds']['top10']:.0%} top-10; otherwise \"one of many\".",
         f"- Grade: **A** - share for the low goal ≤ {cfg['grade']['a_max_share']:.0%}, ticket ≥ $50/month, fit ≥ {cfg['grade']['a_min_fit']}; "
         f"**B** - share ≤ {cfg['grade']['b_max_share']:.0%} and (ticket ≥ $50 or fit ≥ {cfg['grade']['a_min_fit']}); **B-** - share ≤ {cfg['grade']['b_max_share']:.0%} but ticket < $50 and fit < {cfg['grade']['a_min_fit']}; "
         "**C** - the goal requires leading the niche (or fit 0).",
         "", f"## Table ({len(rows)} open niches, by grade and score)", "",
         "| Grade | Niche | Verdict | Score | Side | Price/mo | Net ARPU | Payers for low / high goal | Payers in niche (est.) | Share low / high | Position low / high | Ticket | Fit |" + (" RU |" if ru_col else "") + " Size proxy |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|" + ("---|" if ru_col else "") + "---|"]
    for r in rows:
        nm = niches[r["niche_id"]].get("name", r["niche_id"])
        sh = lambda v: f"{v:.0%}" if v is not None else "—"  # noqa: E731
        ru_cell = f" {r['ru_verdict'] or '—'} |" if ru_col else ""
        L.append(f"| **{r['grade']}** | {nm} (`{r['niche_id']}`) | {V[r['verdict']]} | {r['score']} | {r['side']} | ${r['price_month']:.0f} ({r['price_src']}) | ${r['arpu_net']:.1f} | "
                 f"{r['payers_low']:,} / {r['payers_high']:,} | {(format(r['niche_payers_est'], ',')) if r['niche_payers_est'] else '—'} | {sh(r['share_low'])} / {sh(r['share_high'])} | "
                 f"{r['position_low']} / {r['position_high']} | {r['ticket_tier'] or '—'} | {r['founder_fit']} |{ru_cell} {r['size_proxy']}{('; ' + r['notes']) if r['notes'] else ''} |")
    cnt = {k: sum(1 for r in rows if r["grade"] == k) for k in ("A", "B", "B-", "C", "?", "—")}
    L += ["", "## Reading the table", "",
          f"- Grades: A - {cnt['A']}, B - {cnt['B']}, B- - {cnt['B-']}, C - {cnt['C']} (including fit 0), excluded - {cnt['—']}, no size estimate - {cnt['?']}.",
          "- \"Position\" answers \"what do you have to become in the niche to reach the goal\". \"Leader\" means racing the incumbent for first place; \"one of many\" means the goal is reachable without winning the niche, only acquisition cost matters.",
          "- For B2C the niche size comes from App Store rating velocity, the shakiest multiplier (50 installs per rating may be 30 or 100): read shares as ±2×. For B2B it comes from Capterra reviews (30 customers per review is also ±2×).",
          "- Fit is a manual 0-3 score per niche (`fit` in `config/overrides.yaml`, default `default_fit` in nf.yaml); ticket is the median competitor price.", ""]
    p = ws.report("S6-path-to-goal.md")
    open(p, "w", encoding="utf-8").write("\n".join(L))
    print("->", p)
