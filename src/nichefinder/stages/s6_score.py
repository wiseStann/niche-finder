"""Full niche score (0-100) over the shortlist cohort, gates G3/G5/S5 and an automatic verdict.

Score = demand 30 + growth 20 + fragmentation 25 + deals 15 + switching 10, times a trend adjustment.
- demand: 20 * percentile of log10(search demand) + 10 * CPC-band factor;
- growth: 10 * yoy percentile + 5 * momentum percentile + 5 * 3-year CAGR percentile;
- fragmentation: 10 * (1 - brand HHI) + 5 * competition-index percentile
  + 5 * players percentile + 5 * (1 - top-3 share) (players / top-3 come from App Store, Capterra or Shopify;
  when the supply proxy is weak (NA) the last two are neutral 50%);
- deals: 15 * percentile of tinyseed*2 + ph_12m + yc + topgrossing_us (the marketplace term was dropped on 2026-11-20:
  Flippa blocks automated clients and Empire Flippers has too few software listings; methodology section 7.2);
- switching: 4 * self_serve + 3 * monthly + 1 * 0.5 (import, unmeasured) + 2 * (2 - lock_in) / 2.
Percentiles are taken within a segment (B2C + prosumer / B2B), not across the whole cohort. Trend: +5% / -5% for UP / DOWN
by Keyword Planner and again by Google Trends.
Search volume is taken from the clean base year (demand_2023 column) when Keyword Planner growth is >= 3x versus that year
(or a Q:step2025 / Q:hump2024 flag is set) and Google Trends does not confirm it (FLAT / DOWN); flag D:2023-base.

Gates (any failure = red): G3 platform_risk = 2; G5 feasibility score >= 2; S5 supply concentration (top-1 > 50% or too few
players) - PASS when the Google Play leader holds <= 50% with >= 8 players above 100k installs (PASS:android); unmeasured
supply passes only with a manual supply estimate (PASS*).

Verdict: gates failed -> red; otherwise green when score >= nf.yaml `verdict.green_min_score` (default 70), else yellow.
`verdict` in config/overrides.yaml for a niche replaces the automatic green/yellow. The reason is written to `verdict_note`.

Inputs: data/out/metrics_quick.csv, supply_deep.csv; optional offsearch.csv (S8), entrant_survival.csv (S9);
config/score.yaml (weights, CPC bands), config/overrides.yaml (per-niche judgments). Output: data/out/score_final.csv.
"""
from __future__ import annotations

import argparse
import csv
import math

from nichefinder import niches as nf_niches
from nichefinder.workspace import Workspace

SUMMARY = "Full score, gates and automatic verdict for shortlisted niches"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def pct(values, v):
    vals = [x for x in values if x is not None]
    if v is None or not vals:
        return 0.5
    return sum(1 for x in vals if x <= v) / len(vals)


def _read(path, key):
    if not path.is_file():
        return {}
    return {r[key]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def _need(path, hint):
    if not path.is_file():
        raise SystemExit(f"{path} not found - {hint}")
    return path


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = ws.load_config("score.yaml")
    manual = nf_niches.overrides(ws)
    green_min = float(ws.setting("verdict.green_min_score", 70))
    quick = _read(_need(ws.out("metrics_quick.csv"), "run the S3 stages first"), "id")
    rows = list(csv.DictReader(open(_need(ws.out("supply_deep.csv"), "run the S5 stages first"), encoding="utf-8")))
    # S8 -> S5 gate "second platform": the App Store is one concentration signal; when the iOS top-1 holds > 50% but the
    # Google Play US leader holds <= 50% with >= 8 players above 100k installs, the market is not a monopoly: gate = PASS:android.
    off = _read(ws.out("offsearch.csv"), "niche_id")
    for r in rows:
        o = off.get(r["niche_id"], {})
        gp_top1, gp_players = f(o.get("gp_us_top1_share")), f(o.get("gp_us_players_100k"))
        if r["gate_s5"] == "FAIL:top1" and gp_top1 is not None and gp_top1 <= 0.5 and (gp_players or 0) >= 8:
            r["gate_s5"] = "PASS:android"
    # New-entrant survival in the App Store (s9_entrants): flags E:churn / E:traction, weights untouched.
    ent = _read(ws.out("entrant_survival.csv"), "niche_id")
    for r in rows:
        q = quick[r["niche_id"]]
        # Keyword Planner growth >= 3x versus the clean base year that independent Trends data does not confirm (FLAT / DOWN)
        # is treated as contamination ("X software" 2024, "X app" 2025): volume for the percentile comes from demand_2023.
        d_us, d_23 = f(r["demand_us"], 0), f(r["demand_2023"], 0)
        g3 = r.get("gates_s3") or ""
        contaminated = d_23 > 0 and (d_us / d_23 >= 3 or "Q:step2025" in g3 or "Q:hump2024" in g3) and r["trend_gt"] in ("FLAT", "DOWN")
        r["_dem_eff"] = d_23 if contaminated else d_us
        r["_dem_flag"] = "D:2023-base" if contaminated else ""
        r["_dem"] = math.log10(r["_dem_eff"] + 1)
        r["_grp"] = "b2c" if r["side"] in ("b2c", "prosumer") else "b2b"
        r["_yoy"], r["_mom"], r["_cagr"] = f(q.get("us_yoy")), f(q.get("us_momentum")), f(q.get("us_cagr_3y"))
        r["_comp"] = f(r["comp_idx"])
        r["_players"] = f(r["supply_players"])
        r["_deals"] = 2 * f(r["tinyseed"], 0) + f(r["ph_12m"], 0) + f(r["yc"], 0) + f(r["topgross_us"], 0)
    # Percentiles within the segment (B2C+prosumer / B2B): volumes, player counts and deals are not comparable across segments
    # by construction (B2C queries run ~10x larger, App Store top-grossing exists only for B2C).
    keys = ("_dem", "_yoy", "_mom", "_cagr", "_comp", "_players", "_deals")
    cohorts = {g: {k: [r[k] for r in rows if r["_grp"] == g] for k in keys} for g in ("b2c", "b2b")}
    out = []
    for r in rows:
        m = manual.get(r["niche_id"]) or {}
        cohort = cohorts[r["_grp"]]
        # demand 30
        s_vol = 20 * pct(cohort["_dem"], r["_dem"])
        cpc = f(r["cpc"])
        # CPC band per segment: B2B has no upper penalty (a higher ticket means higher retention), see score.yaml
        lo, hi = cfg["cpc_band"]["en_b2b" if r["_grp"] == "b2b" else "en"]
        s_cpc = 10 * (1.0 if cpc is not None and lo <= cpc <= hi else (cfg["cpc_below"] if cpc is not None and cpc < lo else cfg["cpc_above"]))
        # growth 20
        s_gr = 10 * pct(cohort["_yoy"], r["_yoy"]) + 5 * pct(cohort["_mom"], r["_mom"]) + 5 * pct(cohort["_cagr"], r["_cagr"])
        # fragmentation 25
        supply_na = r["gate_s5"] in ("NA", "NA:proxy")
        s_fr = 10 * (1 - f(r["hhi_brand"], 0.5)) + 5 * pct(cohort["_comp"], r["_comp"])
        s_fr += (2.5 + 2.5) if supply_na else (5 * pct(cohort["_players"], r["_players"]) + 5 * (1 - f(r["supply_top3_share"], 0.5)))
        # deals 15
        s_de = 15 * pct(cohort["_deals"], r["_deals"])
        # switching 10
        b2c = r["side"] in ("b2c", "prosumer")
        self_serve = 1.0 if b2c else f(r["b2b_price_public"], 0.5)
        monthly = (f(r["b2c_with_monthly"], 0) / max(1, f(r["b2c_n"], 8))) if b2c else f(r["b2b_under100"], 0.5)
        if r["supply_src"] == "shopify":   # Shopify apps: public prices, monthly billing, one-click install
            self_serve, monthly = 1.0, 1.0
        lock = m.get("lock_in", 1)
        s_sw = 4 * self_serve + 3 * monthly + 1 * 0.5 + 2 * ((2 - lock) / 2)
        base = s_vol + s_cpc + s_gr + s_fr + s_de + s_sw
        adj = {"UP": cfg["trend_up"], "DOWN": cfg["trend_down"]}
        score = base * (1 + adj.get(r["trend_kp"], 0) + adj.get(r["trend_gt"], 0))
        # gates
        feas = m.get("feas") or {}
        feas_score = sum(int(v) for v in feas.values()) if feas else None
        gates = []
        if m.get("platform_risk") == 2:
            gates.append("G3:platform")
        if feas_score is not None and feas_score < 2:
            gates.append("G5:feasibility")
        if r["gate_s5"].startswith("FAIL"):
            gates.append("S5:" + r["gate_s5"].split(":")[1])
        s5 = r["gate_s5"] if not r["gate_s5"].startswith("NA") else ("PASS*" if m.get("supply_manual") else "NA")
        if s5 == "NA":
            gates.append("S5:unmeasured")
        flags = []
        if r["gate_s5"] == "PASS:android":
            flags.append("S5:android")
        if int(r["expertise_flag"] or 0):
            flags.append("G4:expertise")
        if m.get("platform_risk") == 1:
            flags.append("P1:platform-partial")
        if supply_na:
            flags.append("S5:manual")
        if r["_dem_flag"]:
            flags.append(r["_dem_flag"])
        if ent.get(r["niche_id"], {}).get("flag"):
            flags.append(ent[r["niche_id"]]["flag"])
        score = round(score, 1)
        override = m.get("verdict", "")
        if gates:
            verdict, note = "red", "failed gates: " + ", ".join(gates)
        elif override:
            verdict, note = override, m.get("verdict_note") or "verdict set manually in overrides"
        elif score >= green_min:
            verdict, note = "green", f"all gates passed; score {score} >= {green_min:g}"
        else:
            verdict, note = "yellow", f"all gates passed; score {score} < {green_min:g}"
        # ticket tier from the median monthly price of competitors (higher ticket = better retention)
        ticket = f(r["b2c_median_monthly"]) if b2c else f(r["b2b_median_monthly"])
        ticket_tier = "" if ticket is None else ("<50" if ticket < 50 else ("50-250" if ticket < 250 else ">250"))
        out.append({
            "niche_id": r["niche_id"], "tier": r["tier"], "side": r["side"], "geo": r["geo"],
            "score": score, "s_demand": round(s_vol + s_cpc, 1), "s_growth": round(s_gr, 1), "s_frag": round(s_fr, 1),
            "s_deals": round(s_de, 1), "s_switch": round(s_sw, 1), "trend_kp": r["trend_kp"], "trend_gt": r["trend_gt"],
            "gate_s5": s5, "platform_risk": m.get("platform_risk"), "lock_in": lock, "feasibility": feas_score,
            "gates_failed": ";".join(gates), "flags": ";".join(flags), "verdict_manual": override, "verdict": verdict,
            "verdict_note": note,
            "demand_us": r["demand_us"], "demand_eff": round(r["_dem_eff"]), "cpc": r["cpc"], "supply_src": r["supply_src"], "supply_top1": r["supply_top1"],
            "supply_top1_share": r["supply_top1_share"], "supply_players": r["supply_players"],
            "ticket_month": ticket if ticket is None else round(ticket, 2), "ticket_tier": ticket_tier,
        })
    if not out:
        raise SystemExit("supply_deep.csv has no rows - nothing to score")
    out.sort(key=lambda x: (-1 if x["verdict"] != "red" else 1, -x["score"]))
    p = ws.out("score_final.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    for o in out:
        print(f"{o['verdict']:6} {o['score']:5} {o['tier']} {o['niche_id']:34} d={o['s_demand']:4} g={o['s_growth']:4} f={o['s_frag']:4} de={o['s_deals']:4} sw={o['s_switch']:4} | S5={o['gate_s5']:8} P={o['platform_risk']} F={o['feasibility']} {o['gates_failed']} {o['flags']}")
    print("->", p)
