"""Russian B2B: Wordstat demand for brand and category phrases, plus 36-month dynamics.

Reads `ws_brands`, `ws_cat` and `ws_dyn` for each niche in config/ru_b2b_niches.yaml. In Russian B2B the demand lives
in brand searches, so the sum of brand counts is the size of the category; category phrases are often close to zero.
Quota is about 100 requests per hour; the cache is shared with the other Wordstat stages (data/cache/wordstat).
Output: data/out/ru_b2b_wordstat.csv, ru_b2b_wordstat_dyn.csv, ru_b2b_wordstat_progress.log. Key: YANDEX_API_KEY.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt

from nichefinder.sources import wordstat
from nichefinder.stages.s4_wordstat_dynamics import parse, pre_period, series_metrics
from nichefinder.workspace import Workspace

SUMMARY = "Russian B2B: Wordstat brands, categories and dynamics"
KEYS: tuple[str, ...] = ("YANDEX_API_KEY",)
NEEDS: tuple[str, ...] = ()


def run(ws: Workspace, args: argparse.Namespace) -> None:
    log_path = ws.out("ru_b2b_wordstat_progress.log")

    def log(msg):
        line = f"{dt.datetime.now():%H:%M:%S} {msg}"
        print(line, flush=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    base_year, compare_year = pre_period(ws)
    niches = ws.load_config("ru_b2b_niches.yaml")
    rows, dyn = [], []
    todo = [(n["id"], kind, q) for n in niches for kind in ("ws_brands", "ws_cat") for q in n.get(kind) or []]
    log(f"phrases: {len(todo)} + dynamics {len(niches)}")
    for k, (nid, kind, q) in enumerate(todo, 1):
        res, cached = wordstat.top_requests(ws, q, 20, log=log)
        tc = int(res.get("totalCount", 0)) if "_error" not in res else -1
        top = "; ".join(f"{x.get('phrase')}={x.get('count')}" for x in (res.get("topRequests") or [])[:5]) if "_error" not in res else res.get("_body", "")[:80]
        rows.append({"niche_id": nid, "kind": kind, "phrase": q, "total_count": tc, "top5": top})
        log(f"  {k}/{len(todo)} {'cache' if cached else 'api'} {nid:30} {kind:9} {q!r}: {tc}")
        with open(ws.out("ru_b2b_wordstat.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["niche_id", "kind", "phrase", "total_count", "top5"])
            w.writeheader()
            w.writerows(rows)
    keys = ["niche_id", "phrase", "status", "last12", "prev12", "yoy", "yoy_pre", "momentum", "spike", "verdict", "series"]
    for n in niches:
        q = n.get("ws_dyn")
        if not q:
            continue
        res, cached = wordstat.dynamics(ws, q, months=36, log=log)
        m = series_metrics(parse(res), base_year, compare_year) if "_error" not in res else {}
        dyn.append({"niche_id": n["id"], "phrase": q, "status": "ok" if m else "ERR", **m})
        log(f"  dyn {'cache' if cached else 'api'} {n['id']:30} {q!r}: last12={m.get('last12', '')} yoy={m.get('yoy', '')} pre={m.get('yoy_pre', '')} -> {m.get('verdict', '')}")
        with open(ws.out("ru_b2b_wordstat_dyn.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(dyn)
    log("done")
