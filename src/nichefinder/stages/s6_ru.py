"""S6 (RU): leaderboard of the Russian-language branch -> data/out/score_ru.csv and reports/S6-ru.md.

Demand RU = max(anchor, largest category phrase) + sum of brand phrases (Wordstat, broad match; in Russian B2B a class is searched by brand).
Growth = Wordstat dynamics of the anchor (or of the corrected phrase from `dynamics_phrases`), 36 months: yoy > +15% UP, < -15% DOWN
(a series with fewer than 300 searches in the last 12 months is NA; a Wordstat verdict that disagrees with the Google-RU trend becomes FLAT).
Concentration = App Store RU estimates (only niches listed in config/appstore_ru_reviewed.yaml, where the
results were cleaned by hand) and the share of the top brand in Yandex (when at least 2 brands have volume). Brand
queries are summed per brand name (`b` in queries/*.yaml), as in s3_metrics: three spellings of Gamma are one brand.
Score RU = demand 40 (percentile of log) + growth 20 (percentile of yoy 15 + verdict 5)
         + fragmentation 40 (20 * (1 - top1 App Store | brand) + 10 * percentile of players + 10 * (1 - top brand)).
Gates: demand >= 500; not DOWN; G2 top1: App Store RU top-1 > 50%, otherwise the top brand > 50% when at least 3 brands
have volume, or > 70% when only 2 do and they hold at least 5,000 searches a month (with two brands the leader holds
>= 50% by construction; 70% of >= 5,000 is the monopoly rule of the Russian B2B module, ru_report). For a B2C or
prosumer niche a failed G2 passes as PASS:android when Google Play RU (offsearch.csv, s8) has a leader <= 50% and at least
8 apps above 100k installs - the "second platform" rule of s6_score. G3 platform: `platform: 2` in config/overrides_ru.yaml
(a government service, Yandex, a bank or a dominant free platform); without a Russian entry the global judgment
`platform_risk` of config/overrides.yaml counts (a phone's own scanner covers the task in Russia too).
These G2/G3 rules date from 2026-11-24: until then 8 of 11 control niches got the wrong colour (methodology §7.5).
Verdict: any gate fails -> red; all pass -> a manual `verdict` from config/overrides_ru.yaml if set, else green when
score >= verdict.green_min_score in nf.yaml, else yellow.

Per-niche inputs in config/overrides_ru.yaml (all optional):
  platform: 0|1|2          2 = a government service, Yandex, a bank or a dominant free platform already covers the task (gate G3); 1 = partly
  verdict: green|yellow|red  manual verdict for a niche that passes the gates
  note: free text shown in the report
  trap_anchor: phrase      the anchor is informational or foreign (see the nested phrases); it is excluded from demand
  trap_brands: [phrase]    brand phrases polluted by another meaning; excluded
  dynamics_phrases: [..]   corrected phrases for the dynamics stage; the first one is used for growth instead of the anchor
Inputs (data/out/): wordstat_ru.csv, wordstat_dynamics.csv (optional), appstore_metrics.csv, metrics_quick.csv,
direct_niche.csv (optional, s8_direct_forecast: a Yandex CPC column in the report, not scored).
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict

from nichefinder import niches as nf_niches
from nichefinder.stages.s8_appstore_velocity import reviewed_ru
from nichefinder.workspace import Workspace

SUMMARY = "Russian-language leaderboard (Wordstat + App Store RU)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

TOP1_MAX = 0.5                 # G2: top-1 share in App Store RU, or of Wordstat brand searches with at least 3 brands
TWO_BRANDS_TOP1_MAX = 0.7      # G2 with only 2 brands: the monopoly rule of the Russian B2B module (ru_report: top brand
TWO_BRANDS_MIN_SUM = 5000      # > 70% of brand searches at a total of at least 5,000), one definition within the RU branch
GP_TOP1_MAX, GP_MIN_PLAYERS = 0.5, 8   # second platform: Google Play RU leader share and apps above 100k installs


def pct(vals, v):
    vals = [x for x in vals if x is not None]
    return 0.5 if v is None or not vals else sum(1 for x in vals if x <= v) / len(vals)


def f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def derive_verdict(gates: list[str], score: float, green_min: float, override: str = "") -> str:
    """Gates fail -> red (always, as in s6_score); pass -> a manual override if set, else green if score >= green_min, else yellow."""
    if gates:
        return "red"
    if override:
        return override
    return "green" if score >= green_min else "yellow"


def _read(ws: Workspace, name: str):
    p = ws.out(name)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []


def run(ws: Workspace, args: argparse.Namespace) -> None:
    niches = {x["id"]: x for x in nf_niches.load_niches(ws)}
    manual = nf_niches.overrides(ws, "overrides_ru.yaml")
    world = nf_niches.overrides(ws)            # global judgments: platform_risk is the fallback of the Russian `platform`
    bname = {(r["niche_id"], r["q"]): r["brand"] for r in nf_niches.keyword_rows(ws, "ru") if r["intent"] == "brand"}
    off = {r["niche_id"]: r for r in _read(ws, "offsearch.csv")}   # Google Play RU (s8) for the second-platform rule
    reviewed = reviewed_ru(ws)
    green_min = float(ws.setting("verdict.green_min_score", 70))
    wsd = defaultdict(list)
    for r in _read(ws, "wordstat_ru.csv"):
        wsd[r["niche_id"]].append(r)
    dyn = {(r["niche_id"], r["phrase"]): r for r in _read(ws, "wordstat_dynamics.csv")}
    aps = {r["niche_id"]: r for r in _read(ws, "appstore_metrics.csv") if r["store"] == "ru"}
    gq = {r["id"]: r for r in _read(ws, "metrics_quick.csv")}
    ydir = {r["niche_id"]: r for r in _read(ws, "direct_niche.csv") if r.get("status") == "ok"}   # s8_direct_forecast, shown only

    rows = []
    for nid, rs in wsd.items():
        n = niches[nid]
        m = manual.get(nid) or {}
        trap_anchor = m.get("trap_anchor")
        trap_brands = set(m.get("trap_brands") or [])
        cat = [r for r in rs if r["intent"] == "category"]
        anc = next((r for r in rs if r["anchor"] == "1"), None)
        br = [r for r in rs if r["intent"] == "brand" and int(r["total_count"] or 0) > 0 and r["keyword"] not in trap_brands]
        prob = [r for r in rs if r["intent"] == "problem"]
        anchor = int(anc["total_count"] or 0) if anc and anc["keyword"] != trap_anchor else 0
        if trap_anchor:
            cat = [r for r in cat if r["keyword"] != trap_anchor]
        cat_max = max((int(r["total_count"] or 0) for r in cat), default=0)
        bvol = defaultdict(int)                 # per brand name, as in s3_metrics (several spellings of one brand)
        for r in br:
            bvol[bname.get((nid, r["keyword"])) or r["keyword"]] += int(r["total_count"])
        brand_sum = sum(bvol.values())
        top_name = max(bvol, key=bvol.get) if bvol else ""
        b_top1 = bvol[top_name] / brand_sum if brand_sum else None
        demand = max(anchor, cat_max) + brand_sum
        # dynamics
        corrected = m.get("dynamics_phrases") or []
        phrase = corrected[0] if corrected else (anc["keyword"] if anc else "")
        d = dyn.get((nid, phrase)) or (dyn.get((nid, anc["keyword"])) if anc else None) or {}
        dyn_verdict = d.get("verdict", "NA")
        dyn_last12 = f(d.get("last12"))
        if dyn_last12 is not None and dyn_last12 < 300:
            dyn_verdict = "NA"          # series too small: yoy is noise
        g_trend = gq.get(nid, {}).get("gru_trend", "")
        if dyn_verdict in ("UP", "DOWN") and g_trend in ("UP", "DOWN", "FLAT") and g_trend != dyn_verdict:
            dyn_verdict = "FLAT"        # Wordstat and Google-RU disagree -> FLAT (two sources must agree)
        a = aps.get(nid, {}) if nid in reviewed else {}
        as_top1, as_players = (f(a.get("top1_share")), f(a.get("players_1k"))) if a and a.get("na") != "1" else (None, None)
        rows.append({
            "niche_id": nid, "side": n["side"], "geo": n["geo"], "control": gq.get(nid, {}).get("control", ""),
            "anchor_phrase": anc["keyword"] if anc else "", "ya_anchor": anchor, "ya_cat_max": cat_max, "ya_cat_nonzero": sum(1 for r in cat if int(r["total_count"] or 0) > 0),
            "ya_problem": sum(int(r["total_count"] or 0) for r in prob), "ya_brand_sum": brand_sum, "ya_n_brands": len(bvol),
            "ya_top1_brand": top_name, "ya_top1_share": round(b_top1, 3) if b_top1 is not None else None,
            "demand_ru": demand, "dyn_phrase": d.get("phrase", ""), "dyn_last12": f(d.get("last12")), "dyn_yoy": f(d.get("yoy")),
            "dyn_momentum": f(d.get("momentum")), "dyn_verdict_ws": d.get("verdict", "NA"), "dyn_verdict": dyn_verdict, "g_trend": g_trend,
            "as_ru_players_1k": as_players, "as_ru_top1_share": as_top1, "as_ru_top1": a.get("top1", "") if a else "",
            "platform": int(m["platform"]) if "platform" in m else int((world.get(nid) or {}).get("platform_risk") or 0),
            "platform_src": "ru" if "platform" in m else ("global" if (world.get(nid) or {}).get("platform_risk") is not None else ""),
            "gp_ru_top1_share": f(off.get(nid, {}).get("gp_ru_top1_share")), "gp_ru_players_100k": f(off.get(nid, {}).get("gp_ru_players_100k")),
            "note": m.get("note", ""), "verdict_manual": m.get("verdict", ""),
        })
    if not rows:
        print("no rows in wordstat_ru.csv - run s2_wordstat first")
        return
    cohort = [r for r in rows if not r["control"]]
    dem = [math.log10(r["demand_ru"] + 1) for r in cohort]
    yoys = [r["dyn_yoy"] for r in cohort]
    players = [r["as_ru_players_1k"] for r in cohort if r["as_ru_players_1k"] is not None]
    for r in rows:
        s_dem = 40 * pct(dem, math.log10(r["demand_ru"] + 1))
        s_gr = 15 * pct(yoys, r["dyn_yoy"]) + 5 * {"UP": 1.0, "FLAT": 0.5, "DOWN": 0.0, "NA": 0.5}.get(r["dyn_verdict"], 0.5)
        top1 = r["as_ru_top1_share"] if r["as_ru_top1_share"] is not None else (r["ya_top1_share"] if r["ya_n_brands"] >= 3 else None)
        s_fr = 20 * (1 - (top1 if top1 is not None else 0.5)) + 10 * (pct(players, r["as_ru_players_1k"]) if r["as_ru_players_1k"] is not None else 0.5) \
            + 10 * (1 - (r["ya_top1_share"] if r["ya_n_brands"] >= 2 else 0.5))
        r["score_ru"] = round(s_dem + s_gr + s_fr, 1)
        gates = []
        if r["demand_ru"] < 500:
            gates.append("G0:demand")
        if r["dyn_verdict"] == "DOWN":
            gates.append("G1:down")
        r["flags"] = ""
        if top1 is not None:
            g2 = top1 > TOP1_MAX
        elif r["ya_n_brands"] == 2 and r["ya_brand_sum"] >= TWO_BRANDS_MIN_SUM:
            g2 = r["ya_top1_share"] > TWO_BRANDS_TOP1_MAX
        else:
            g2 = False
        if g2 and r["side"] in ("b2c", "prosumer") and r["gp_ru_top1_share"] is not None \
                and r["gp_ru_top1_share"] <= GP_TOP1_MAX and (r["gp_ru_players_100k"] or 0) >= GP_MIN_PLAYERS:
            g2, r["flags"] = False, "PASS:android"      # second platform: Google Play RU is not a monopoly
        if g2:
            gates.append("G2:top1")
        if r["platform"] == 2:
            gates.append("G3:platform")
        r["gates"] = ";".join(gates)
        r["conc_src"] = "appstore-ru" if r["as_ru_top1_share"] is not None else ("brands" if r["ya_n_brands"] >= 3 else (
            "brands-2" if r["ya_n_brands"] == 2 and r["ya_brand_sum"] >= TWO_BRANDS_MIN_SUM else "NA"))
        r["verdict"] = derive_verdict(gates, r["score_ru"], green_min, r["verdict_manual"])
    rows.sort(key=lambda r: (bool(r["control"]), {"green": 0, "yellow": 1, "red": 2}[r["verdict"]], -r["score_ru"]))
    keys = list(rows[0].keys())
    with open(ws.out("score_ru.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    V = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    num = lambda v: f"{int(v):,}".replace(",", " ")  # noqa: E731
    n_reviewed = sum(1 for r in rows if r["as_ru_top1_share"] is not None)
    L = [f"# S6-RU: Russian-language branch (Yandex Wordstat + App Store RU), {ws.today.isoformat()}", "",
         "Demand RU = max(anchor, largest category phrase) + sum of brand queries (Wordstat, broad match, impressions/month). "
         "Growth: Wordstat dynamics over 36 months for the anchor (or a corrected phrase). Concentration: App Store RU estimates "
         f"({n_reviewed} niches with hand-cleaned results) or the top brand's share (at least 3 brands; with 2 brands the gate "
         "fires above 70% of at least 5,000 brand searches). PASS:android: a B2C/prosumer niche whose top-1 gate is overruled by a "
         "fragmented Google Play RU. G3 uses config/overrides_ru.yaml, otherwise the global platform judgment. "
         "Score RU = demand 40 + growth 20 + fragmentation 40; percentiles inside the RU cohort. Control niches are at the bottom. "
         "Yandex CPC: average click price in the premium / guarantee block from the Direct budget forecast (s8_direct_forecast; "
         "shown, not scored).", "",
         "| # | Niche | Type | Verdict | Score | Demand RU | Anchor | Sum brands | Top brand | Dynamics | App Store RU: >=1k / top 1 | Yandex CPC, RUB | Gates | Note |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in enumerate(rows, 1):
        asr = f"{int(r['as_ru_players_1k'])} / {r['as_ru_top1_share']:.0%} {r['as_ru_top1'][:20]}" if r["as_ru_top1_share"] is not None else "—"
        br = f"{r['ya_top1_share']:.0%} {r['ya_top1_brand'][:16]}" if r["ya_top1_share"] is not None else "—"
        dynv = f"{r['dyn_verdict']} ({r['dyn_yoy']:+.0%})" if r["dyn_yoy"] is not None else r["dyn_verdict"]
        yd = ydir.get(r["niche_id"])
        ycpc = f"{yd['cpc_premium'] or '—'} / {yd['cpc_guarantee'] or '—'}" if yd else "—"
        L.append(f"| {k} | {r['niche_id']}{' (control)' if r['control'] else ''} | {r['side']} | {V[r['verdict']]} | {r['score_ru']} | {num(r['demand_ru'])} | "
                 f"{num(r['ya_anchor'])} «{r['anchor_phrase'][:28]}» | {num(r['ya_brand_sum'])} ({r['ya_n_brands']}) | {br} | {dynv} | {asr} | {ycpc} | {';'.join(x for x in (r['gates'], r['flags']) if x)} | {r['note']} |")
    ws.report("S6-ru.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    for r in rows[:45]:
        print(f"{V[r['verdict']]} {r['score_ru']:5} {r['niche_id']:34} dem={r['demand_ru']:>7} anc={r['ya_anchor']:>6} br={r['ya_brand_sum']:>6}({r['ya_n_brands']}) top1={r['ya_top1_share']} dyn={r['dyn_verdict']}({r['dyn_yoy']}) as={r['as_ru_top1_share']}/{r['as_ru_players_1k']} {r['gates']}")
    print("-> score_ru.csv, reports/S6-ru.md")
