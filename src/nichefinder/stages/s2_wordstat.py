"""Yandex Wordstat topRequests for every Russian query (totalCount = Yandex demand, nested top phrases for anchors).

Order: anchors, brands, categories, problems. The quota is about 100 requests per hour, so a first run takes hours;
the cache makes re-runs free. Queries come from queries/*.yaml (language `ru`).
Output: data/out/wordstat_ru.csv (keyword, niche_id, intent, anchor, total_count, nested_json);
progress log: data/out/wordstat_progress.log. Key: YANDEX_API_KEY (only for requests not yet cached).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json

from nichefinder import niches
from nichefinder.sources import wordstat
from nichefinder.workspace import Workspace

SUMMARY = "Yandex Wordstat demand for all Russian queries"
KEYS: tuple[str, ...] = ("YANDEX_API_KEY",)
NEEDS: tuple[str, ...] = ()


def run(ws: Workspace, args: argparse.Namespace) -> None:
    csv_path = ws.out("wordstat_ru.csv")
    log_path = ws.out("wordstat_progress.log")

    def log(msg):
        line = f"{dt.datetime.now():%H:%M:%S} {msg}"
        print(line, flush=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def write(results):
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            w.writerows(results)

    rows = [{"niche_id": r["niche_id"], "q": r["q"], "intent": r["intent"], "anchor": str(r["anchor"])}
            for r in niches.keyword_rows(ws, "ru")]
    prio = {"category": 2, "brand": 1, "problem": 3}
    rows.sort(key=lambda r: (0 if r["anchor"] == "1" else prio.get(r["intent"], 4)))
    seen, todo = set(), []
    for r in rows:
        q = r["q"].strip().lower()
        if q in seen:
            continue
        seen.add(q)
        todo.append(r)
    log(f"unique Russian queries: {len(todo)}")
    if not todo:
        return

    results = []
    hits = 0
    for i, r in enumerate(todo, 1):
        q = r["q"].strip().lower()
        num = 50 if r["anchor"] == "1" else 10
        res, from_cache = wordstat.top_requests(ws, q, num, log=log)
        hits += from_cache
        if "_error" in res:
            log(f"  ! {q!r}: {res['_error']} {res.get('_body', '')[:120]}")
            results.append({"keyword": q, "niche_id": r["niche_id"], "intent": r["intent"], "anchor": r["anchor"], "total_count": "", "nested_json": "[]"})
            continue
        nested = [(x["phrase"], int(x.get("count", 0))) for x in res.get("results", [])]
        results.append({"keyword": q, "niche_id": r["niche_id"], "intent": r["intent"], "anchor": r["anchor"],
                        "total_count": int(res.get("totalCount", 0)), "nested_json": json.dumps(nested, ensure_ascii=False)})
        if i % 20 == 0 or not from_cache and i % 5 == 0:
            log(f"  {i}/{len(todo)} (from cache {hits}) — {q!r}: {res.get('totalCount', 0)}")
            write(results)

    write(results)
    log(f"done: {len(results)} rows -> {csv_path}")
