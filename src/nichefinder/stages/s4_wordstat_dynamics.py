"""Wordstat dynamics for the Russian anchor of every niche with geo both/ru: 36 months, monthly.

Metrics as in the global trend stage: yoy (last 12 / previous 12 months, last-12 values capped at 3x the previous-year
median), yoy_pre (compare year / base year averages, see config/wordstat.yaml), momentum (last 3 months / the same 3 months
a year earlier). Verdict UP/DOWN only when yoy and yoy_pre agree. Extra phrases (corrected anchors) are listed per niche in
config/overrides_ru.yaml under `dynamics_phrases`.
Output: data/out/wordstat_dynamics.csv. Key: YANDEX_API_KEY (only for requests not yet cached).

config/wordstat.yaml (optional):
    pre_period: {base_year: 2023, compare_year: 2024}   # the clean pre-contamination years used for yoy_pre
"""
from __future__ import annotations

import argparse
import csv

from nichefinder import keys, niches
from nichefinder.sources import wordstat
from nichefinder.workspace import Workspace

SUMMARY = "Yandex Wordstat 36-month dynamics for Russian anchors"
KEYS: tuple[str, ...] = ("YANDEX_API_KEY",)
NEEDS: tuple[str, ...] = ()

DEFAULT_PRE_PERIOD = {"base_year": 2023, "compare_year": 2024}


def pre_period(ws: Workspace) -> tuple[str, str]:
    cfg = (ws.load_config("wordstat.yaml", {}) or {}).get("pre_period", {}) or {}
    return str(cfg.get("base_year", DEFAULT_PRE_PERIOD["base_year"])), str(cfg.get("compare_year", DEFAULT_PRE_PERIOD["compare_year"]))


def series_metrics(vals, base_year="2023", compare_year="2024"):
    """vals: list of (month, value) in ascending date order, at least 24 points."""
    v = [x for _, x in vals]
    if len(v) < 24:
        return {}
    last12, prev12 = v[-12:], v[-24:-12]
    med = sorted(prev12)[len(prev12) // 2] or 1
    robust = [min(x, 3 * med) for x in last12]
    yoy = (sum(robust) / sum(prev12) - 1) if sum(prev12) else None
    mom = (sum(v[-3:]) / sum(v[-15:-12]) - 1) if sum(v[-15:-12]) else None
    by_year = {}
    for (m, x) in vals:
        by_year.setdefault(m[:4], []).append(x)
    y_base, y_cmp = by_year.get(base_year, []), by_year.get(compare_year, [])
    yoy_pre = (sum(y_cmp) / len(y_cmp)) / (sum(y_base) / len(y_base)) - 1 if len(y_base) >= 10 and len(y_cmp) >= 10 and sum(y_base) else None
    spike = max(last12) / (sorted(last12)[6] or 1) > 3
    if yoy is not None and yoy_pre is not None and yoy > 0.05 and yoy_pre > 0.05:
        verdict = "UP"
    elif yoy is not None and yoy_pre is not None and yoy < -0.05 and yoy_pre < -0.05:
        verdict = "DOWN"
    elif yoy is not None and yoy_pre is None:
        verdict = "UP" if yoy > 0.15 else ("DOWN" if yoy < -0.15 else "FLAT")
    else:
        verdict = "FLAT"
    return {"last12": sum(last12), "prev12": sum(prev12), "yoy": round(yoy, 3) if yoy is not None else "", "yoy_pre": round(yoy_pre, 3) if yoy_pre is not None else "",
            "momentum": round(mom, 3) if mom is not None else "", "spike": int(spike), "verdict": verdict,
            "series": " ".join(str(x) for x in v[-24:])}


def parse(res):
    # API v2 answer: {"dynamics":[{"date":"2024-01-01","count":..., ...}]}; several shapes are accepted
    items = res.get("results") or res.get("dynamics") or res.get("items") or []
    out = []
    for it in items:
        d = it.get("date") or it.get("period") or it.get("month") or ""
        c = it.get("count") if it.get("count") is not None else (it.get("totalCount") if it.get("totalCount") is not None else it.get("value", 0))
        out.append((str(d)[:7], int(float(c or 0))))
    return sorted(out)


def run(ws: Workspace, args: argparse.Namespace) -> None:
    base_year, compare_year = pre_period(ws)
    nich = {x["id"]: x for x in niches.load_niches(ws)}
    queries = niches.load_queries(ws)
    extra = {nid: (o.get("dynamics_phrases") or []) for nid, o in niches.overrides(ws, "overrides_ru.yaml").items() if isinstance(o, dict)}
    logf = open(ws.out("wordstat_dyn_progress.log"), "a", encoding="utf-8")

    def log(msg):
        print(msg)
        logf.write(msg + "\n")
        logf.flush()
    rows = []
    todo = []
    for nid, n in nich.items():
        if n.get("geo", "global") not in ("both", "ru"):
            continue
        anchor = next((e["q"] for e in (queries.get(nid, {}).get("ru") or []) if e.get("anchor")), None)
        if anchor:
            todo.append((nid, anchor, "anchor"))
        for q in extra.get(nid, []):
            todo.append((nid, q, "extra"))
    print(len(todo), "phrases")
    for k, (nid, phrase, kind) in enumerate(todo, 1):
        try:
            res, _ = wordstat.dynamics(ws, phrase, months=36, log=log)
        except keys.MissingKey:
            raise
        except Exception as e:  # noqa: BLE001
            print("  !!", phrase, e)
            rows.append({"niche_id": nid, "phrase": phrase, "kind": kind, "status": "ERR"})
            continue
        vals = parse(res)
        m = series_metrics(vals, base_year, compare_year)
        rows.append({"niche_id": nid, "phrase": phrase, "kind": kind, "status": "ok" if m else f"short:{len(vals)}", **m})
        print(f"{k:3}/{len(todo)} {nid:34} {kind:6} {phrase[:34]:34} last12={m.get('last12', '')} yoy={m.get('yoy', '')} pre={m.get('yoy_pre', '')} -> {m.get('verdict', '')}")
    cols = ["niche_id", "phrase", "kind", "status", "last12", "prev12", "yoy", "yoy_pre", "momentum", "spike", "verdict", "series"]
    path = ws.out("wordstat_dynamics.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    print("->", path, len(rows))
    logf.close()
