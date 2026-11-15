"""Quick-filter metrics per niche from DataForSEO (Google) and Wordstat (Yandex, when present).

Inputs: data/out/dfs_<pool>.csv (us, ww, ru), data/out/wordstat_ru.csv (optional), niches.yaml, queries/*.yaml,
config/score.yaml. Output: data/out/metrics_quick.csv, one row per niche with demand, CPC, trend, brand
concentration, data-quality flags, gates and a quick score per pool. Percentiles are computed inside each pool.

Keyword Planner history is contaminated after `base_year` (a one-year hump of "X software" queries, then a step-up
of "X app" queries), so a trend verdict (UP/DOWN) needs two periods to agree and `demand_2023` keeps the clean
base-year level. Column and flag names (`*_2023`, `step_2025`, `hump_2024`) are fixed identifiers; the actual years
come from `base_year` and the run date.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict

from nichefinder import niches as nf_niches
from nichefinder.workspace import Workspace

SUMMARY = "Quick-filter metrics per niche: demand, CPC, trend, brand concentration, gates, score"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def load_dfs(ws: Workspace, geo: str) -> dict:
    path = ws.out(f"dfs_{geo}.csv")
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        out[r["keyword"]] = {
            "vol": int(float(r["search_volume"])) if r["search_volume"] else 0,
            "cpc": float(r["cpc"]) if r["cpc"] else None,
            "comp": int(float(r["competition_index"])) if r["competition_index"] else None,
            "monthly": dict(json.loads(r["monthly_json"])),
        }
    return out


def load_wordstat(ws: Workspace) -> dict:
    path = ws.out("wordstat_ru.csv")
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r["total_count"] != "":
            out[r["keyword"]] = {"vol": int(r["total_count"]), "nested": json.loads(r["nested_json"])}
    return out


def pct_rank(values, v):
    vals = [x for x in values if x is not None]
    if v is None or not vals:
        return None
    return sum(1 for x in vals if x <= v) / len(vals)


def month_key(idx: int) -> str:
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def series_metrics(cfg: dict, today, monthly_sum: dict) -> dict:
    """monthly_sum: {YYYY-MM: volume} summed over a niche's category queries.

    Returns: yoy (last 12 months vs the previous 12, on the robust series), yoy_pre (year after base_year vs
    base_year, before the 2025+ contamination), momentum (last 3 months vs the same 3 a year earlier, robust),
    cagr_3y, spike, step_2025, hump_2024, last12, demand_2023.
    Robust series: each month is capped at spike_ratio x the median of the previous 12 months, so single peaks
    do not break the trend.
    """
    if not monthly_sum:
        return {}
    base = int(cfg.get("base_year", 2023))
    months = sorted(monthly_sum)
    v = [monthly_sum[m] for m in months]
    n = len(v)
    r = list(v)
    for i in range(12, n):
        med = statistics.median(v[i - 12:i])
        if med > 0 and r[i] > cfg["spike_ratio"] * med:
            r[i] = cfg["spike_ratio"] * med
    out = {}
    if n >= 24:
        last12, prev12 = sum(r[-12:]), sum(r[-24:-12])
        out["yoy"] = (last12 / prev12 - 1) if prev12 > 0 else None
    if n >= 48:
        last12, old12 = sum(r[-12:]), sum(r[-48:-36])
        out["cagr_3y"] = ((last12 / old12) ** (1 / 3) - 1) if old12 > 0 else None
    if n >= 15:
        last3, ya3 = sum(r[-3:]), sum(r[-15:-12])
        out["momentum"] = (last3 / ya3 - 1) if ya3 > 0 else None
    y23 = sum(monthly_sum.get(f"{base}-{m:02d}", 0) for m in range(1, 13))
    y24 = sum(monthly_sum.get(f"{base + 1}-{m:02d}", 0) for m in range(1, 13))
    out["yoy_pre"] = (y24 / y23 - 1) if y23 > 0 else None
    tail = v[-24:] if n >= 24 else v
    med = statistics.median(tail) if tail else 0
    out["spike"] = int(med > 0 and max(tail) / med > cfg["spike_ratio"])
    # recent window for the step flag: step_window_months months ending step_window_end_lag_months before the run date's month
    end_idx = today.year * 12 + (today.month - 1) - int(cfg.get("step_window_end_lag_months", 3))
    start_idx = end_idx - int(cfg.get("step_window_months", 12)) + 1
    lo, hi = month_key(start_idx), month_key(end_idx)
    recent = [monthly_sum[m] for m in months if lo <= m <= hi]
    out["step_2025"] = int(y24 > 0 and recent and (sum(recent) / len(recent)) / (y24 / 12) > cfg["step_ratio"])
    y26 = [monthly_sum[m] for m in months if m >= f"{today.year}-01"]
    out["hump_2024"] = int(y23 > 0 and y24 / y23 > cfg["hump_ratio"] and y26 and (sum(y26) / len(y26)) / (y24 / 12) < cfg["hump_drop"])
    out["last12"] = sum(v[-12:]) if n >= 12 else sum(v)
    out["demand_2023"] = round(y23 / 12) if y23 else 0  # clean base-year level, before the contamination
    return out


def trend_verdict(cfg: dict, m: dict) -> str:
    """UP/DOWN only when two periods agree (year after base vs base year, and last 12 months vs the previous 12):
    Keyword Planner history after the base year is contaminated (a one-year hump, then a step-up)."""
    a, b = m.get("yoy_pre"), m.get("yoy")
    if a is None or b is None:
        return "NA"
    if a > cfg["trend_up"] and b > cfg["trend_up"]:
        return "UP"
    if a < cfg["trend_down"] and b < cfg["trend_down"]:
        return "DOWN"
    return "FLAT"


def niche_geo_metrics(cfg: dict, today, items: list, data: dict) -> dict:
    """items: a niche's queries for one language; data: {keyword: {...}}."""
    cat = [(it, data.get(it["q"].lower())) for it in items if it["i"] == "category"]
    prob = [(it, data.get(it["q"].lower())) for it in items if it["i"] == "problem"]
    brand = [(it, data.get(it["q"].lower())) for it in items if it["i"] == "brand"]
    vol = lambda d: (d or {}).get("vol") or 0  # noqa: E731
    m = {}
    m["demand_cat"] = sum(vol(d) for _, d in cat)
    m["demand_problem"] = sum(vol(d) for _, d in prob)
    m["n_cat_nonzero"] = sum(1 for _, d in cat if vol(d) > 0)
    m["low_n"] = int(m["n_cat_nonzero"] < cfg["min_cat_nonzero"])
    cpcs = [d["cpc"] for _, d in cat if d and d.get("cpc")]
    m["cpc_med"] = statistics.median(cpcs) if cpcs else None
    comps = [d["comp"] for _, d in cat if d and d.get("comp") is not None]
    m["comp_idx"] = statistics.mean(comps) if comps else None
    # brands: aggregate by b
    bvol = defaultdict(int)
    for it, d in brand:
        bvol[it.get("b", it["q"])] += vol(d)
    m["demand_brand"] = sum(bvol.values())
    m["n_brands"] = len([b for b, v in bvol.items() if v > 0])
    tot = m["demand_brand"] + m["demand_cat"] + m["demand_problem"]
    m["brand_share"] = (m["demand_brand"] / tot) if tot else None
    if m["demand_brand"] > 0:
        shares = [v / m["demand_brand"] for v in bvol.values()]
        m["hhi_brand"] = sum(s * s for s in shares)
        m["top1_brand_share"] = max(shares)
        m["top1_brand"] = max(bvol, key=bvol.get)
    else:
        m["hhi_brand"] = m["top1_brand_share"] = None
        m["top1_brand"] = ""
    # dynamics over category queries
    monthly = defaultdict(int)
    for _, d in cat:
        for mo, val in ((d or {}).get("monthly") or {}).items():
            monthly[mo] += val
    m.update(series_metrics(cfg, today, monthly))
    m["trend"] = trend_verdict(cfg, m) if monthly else "NA"
    return m


def cpc_band_score(cfg: dict, cpc, lang: str) -> float:
    if cpc is None:
        return 0.0
    lo, hi = cfg["cpc_band"][lang]
    if cpc < lo:
        return cfg["cpc_below"]
    if cpc > hi:
        return cfg["cpc_above"]
    return 1.0


def run(ws: Workspace, args: argparse.Namespace | None = None) -> list:
    cfg = ws.load_config("score.yaml")
    niches, queries = nf_niches.load(ws)
    markets = ws.markets
    dfs = {g: load_dfs(ws, g) for g in ["us", "ww", "ru"]}
    wordstat = load_wordstat(ws) if "ru" in markets else {}
    today = ws.today
    rows = []
    for n in niches:
        q = queries.get(n["id"], {})
        row = {"id": n["id"], "name": n.get("name", n["id"]), "tier": n.get("tier", ""), "geo": n.get("geo", "global"),
               "side": n.get("side", ""), "expertise_flag": n.get("expertise_flag", 0), "control": n.get("control") or ""}
        if q.get("en"):
            for g in ["us", "ww"]:
                if g not in markets:
                    continue
                for k, v in niche_geo_metrics(cfg, today, q["en"], dfs[g]).items():
                    row[f"{g}_{k}"] = v
        if q.get("ru") and "ru" in markets:
            for k, v in niche_geo_metrics(cfg, today, q["ru"], dfs["ru"]).items():
                row[f"gru_{k}"] = v
            # Yandex: totalCount (broad match) - the anchor is demand, the sum over brands is brand demand
            ru_items = q["ru"]
            anchor = next((it for it in ru_items if it.get("anchor")), None)
            if wordstat and anchor and anchor["q"].lower() in wordstat:
                row["ya_demand_anchor"] = wordstat[anchor["q"].lower()]["vol"]
                cats = [wordstat[it["q"].lower()]["vol"] for it in ru_items if it["i"] == "category" and it["q"].lower() in wordstat]
                row["ya_demand_cat_max"] = max(cats) if cats else None
                bv = defaultdict(int)
                for it in ru_items:
                    if it["i"] == "brand" and it["q"].lower() in wordstat:
                        bv[it.get("b", it["q"])] += wordstat[it["q"].lower()]["vol"]
                if sum(bv.values()) > 0:
                    sh = [v / sum(bv.values()) for v in bv.values()]
                    row["ya_hhi_brand"] = sum(s * s for s in sh)
                    row["ya_top1_brand_share"] = max(sh)
                    row["ya_top1_brand"] = max(bv, key=bv.get)
                    row["ya_brand_share"] = sum(bv.values()) / (sum(bv.values()) + row["ya_demand_anchor"])
        rows.append(row)

    # ── scoring per pool ────────────────────────────────────────────────
    def cohort(pref, lang):
        members = [r for r in rows if f"{pref}_demand_cat" in r]
        logd = {r["id"]: math.log10(r[f"{pref}_demand_cat"] + 1) for r in members}
        yoy = {r["id"]: r.get(f"{pref}_yoy") for r in members}
        mom = {r["id"]: r.get(f"{pref}_momentum") for r in members}
        cagr = {r["id"]: r.get(f"{pref}_cagr_3y") for r in members}
        comp = {r["id"]: r.get(f"{pref}_comp_idx") for r in members}
        W = cfg["weights"]
        for r in members:
            i = r["id"]
            d = pct_rank(logd.values(), logd[i]) * W["demand_vol"] + cpc_band_score(cfg, r.get(f"{pref}_cpc_med"), lang) * W["demand_cpc"]
            g = 0.0
            for key, w in [(yoy, W["growth_yoy"]), (mom, W["growth_momentum"]), (cagr, W["growth_cagr"])]:
                p = pct_rank(key.values(), key[i])
                g += (p or 0.5) * w
            hhi = r.get(f"{pref}_hhi_brand")
            top1 = r.get(f"{pref}_top1_brand_share")
            f = ((1 - hhi) if hhi is not None else 0.5) * W["frag_hhi"] + ((1 - top1) if top1 is not None else 0.5) * W["frag_top1"]
            pc = pct_rank(comp.values(), comp[i])
            f += (pc if pc is not None else 0.5) * W["frag_comp"]
            r[f"{pref}_score_demand"] = round(d, 1)
            r[f"{pref}_score_growth"] = round(g, 1)
            r[f"{pref}_score_frag"] = round(f, 1)
            total_w = W["demand_vol"] + W["demand_cpc"] + W["growth_yoy"] + W["growth_momentum"] + W["growth_cagr"] + W["frag_hhi"] + W["frag_top1"] + W["frag_comp"]
            r[f"{pref}_quick_score"] = round((d + g + f) / total_w * 100, 1)
            # gates
            gates = []
            if r.get(f"{pref}_low_n"):
                gates.append("G0:low_n")
            if r.get(f"{pref}_trend") == "DOWN":
                gates.append("G1:DOWN")
            if r.get(f"{pref}_spike"):
                gates.append("Q:spike")
            if r.get(f"{pref}_step_2025"):
                gates.append("Q:step2025")
            if r.get(f"{pref}_hump_2024"):
                gates.append("Q:hump2024")
            if r.get(f"{pref}_n_brands", 0) >= 2:
                if (top1 or 0) > cfg["gate_top1_brand_share"]:
                    gates.append("G2:top1")
                if (r.get(f"{pref}_brand_share") or 0) > cfg["gate_brand_share"]:
                    gates.append("I:brand_share")  # informational, not a gate
            if r["expertise_flag"]:
                gates.append("G4:expertise")
            r[f"{pref}_gates"] = ";".join(gates)
            r[f"{pref}_pass"] = int(not [g for g in gates if g[0] == "G" and not g.startswith("G4")])

    if "us" in markets:
        cohort("us", "en")
    if "ww" in markets:
        cohort("ww", "en")
    if "ru" in markets:
        cohort("gru", "ru")

    fields = ["id", "name", "tier", "geo", "side", "expertise_flag", "control"]
    keys = set()
    for r in rows:
        keys.update(r.keys())
    fields += sorted(k for k in keys if k not in fields)
    path = ws.out("metrics_quick.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    print(f"metrics: {len(rows)} niches -> {path}")
    return rows
