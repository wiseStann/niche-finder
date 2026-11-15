"""S2: Google (EN) and Yandex (RU) search suggestions for every anchor and category query.

For each language it takes the anchor query and all category-intent queries of niches.yaml / queries/*.yaml, asks the
free suggestion endpoints and writes data/out/suggest_<lang>.csv with columns niche_id, keyword, anchor, n,
suggestions (joined by " | "; the query itself is removed). Responses are cached under data/cache/suggest/;
failed lookups are not cached and are retried on the next run. A language without queries is skipped.
Yandex requests go through NF_PROXY_RU when it is set. No keys; one request per query, 0.4 s apart.
"""
from __future__ import annotations

import argparse
import csv

from nichefinder import niches
from nichefinder.sources import suggest
from nichefinder.workspace import Workspace

SUMMARY = "Google/Yandex search suggestions for anchor and category queries"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def run(ws: Workspace, args: argparse.Namespace) -> None:
    for lang in ["en", "ru"]:
        rows = [r for r in niches.keyword_rows(ws, lang) if r["intent"] == "category" or r["anchor"] == 1]
        if not rows:
            print(f"[{lang}] no queries, skipped")
            continue
        res_rows, errs = [], 0
        for i, r in enumerate(rows, 1):
            q = r["q"].strip().lower()
            res = suggest.google(ws, q) if lang == "en" else suggest.yandex(ws, q)
            if "_error" in res:
                errs += 1
                sugg = []
            else:
                sugg = [s for s in res["suggestions"] if s.strip().lower() != q]
            res_rows.append({"niche_id": r["niche_id"], "keyword": q, "anchor": r["anchor"], "n": len(sugg), "suggestions": " | ".join(sugg)})
            if i % 100 == 0:
                print(f"[{lang}] {i}/{len(rows)} (errors {errs})", flush=True)
        path = ws.out(f"suggest_{lang}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(res_rows[0].keys()))
            w.writeheader()
            w.writerows(res_rows)
        print(f"[{lang}] {len(res_rows)} rows, errors {errs} -> {path}")
