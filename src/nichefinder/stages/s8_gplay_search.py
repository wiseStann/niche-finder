"""Google Play search for the category queries of every shortlisted niche.

Builds a search plan (data/out/gplay_search_plan.json): for each shortlisted niche, its English category queries
against the US store, and, for niches with geo both/ru, its Russian category queries against the RU store.
The Node helper then runs the searches (up to 4 queries per niche and store, 50 results each) and writes
data/out/gplay_search.csv. Relevance is filtered later by s8_gplay_filter.

Input: shortlist, queries/*.yaml. Output: data/out/gplay_search_plan.json, data/out/gplay_search.csv.
Cache: data/cache/gplay_search/. Cost: free, no key (google-play-scraper, about 1.2 s per new query).
"""
from __future__ import annotations

import argparse
import json
import os

from nichefinder import niches, tools
from nichefinder.workspace import Workspace

SUMMARY = "Google Play search results for category queries"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("node",)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: the whole shortlist)")
    parser.add_argument("--keep-plan", action="store_true",
                        help="reuse an existing data/out/gplay_search_plan.json (edit it by hand to restrict the search)")


def build_plan(ws: Workspace, ids: list[str]) -> list[dict]:
    by_id = {n["id"]: n for n in niches.load_niches(ws)}
    queries = niches.load_queries(ws)
    plan = []
    for nid in ids:
        n = by_id.get(nid)
        if not n:
            continue
        for lang, country in (("en", "us"), ("ru", "ru")):
            if country == "ru" and n.get("geo", "global") not in ("both", "ru"):
                continue
            cat = [e["q"] for e in (queries.get(nid, {}).get(lang) or []) if e.get("i") == "category"]
            if cat:
                plan.append({"niche_id": nid, "country": country, "lang": lang, "queries": cat[:4]})
    return plan


def run(ws: Workspace, args: argparse.Namespace) -> None:
    plan_path = ws.out("gplay_search_plan.json")
    if args.keep_plan and plan_path.is_file():
        print("using existing plan", plan_path)
    else:
        ids = niches.shortlist_ids(ws)
        if args.niches:
            wanted = {x.strip() for x in args.niches.split(",") if x.strip()}
            ids = [i for i in ids if i in wanted]
        plan = build_plan(ws, ids)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"plan: {len(plan)} niche/store searches -> {plan_path}")
    os.environ["NF_CACHE_DIR"] = str(ws.cache_root)
    tools.run_node(ws, "gplay_search.mjs")
