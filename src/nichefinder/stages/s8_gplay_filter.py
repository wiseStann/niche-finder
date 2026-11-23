"""Relevance filter for Google Play search results (gplay_search.csv), per niche: regex candidates, then an LLM product check.

Candidates. English: config/deal_keywords.yaml (`re` plus an optional `not`, or a bare regex). Russian (and English with
no match): the phrases of config/coverage_keywords.yaml as substrings, without word boundaries (Cyrillic).
Position rule: an app that shows up in two or more queries of the niche, best position 10 or better, is a candidate
unless it matches `not`.
Product check. A shared word or a top position lets in games, apps for the other side of a market and giants, as in
the App Store (s5_appstore), so the candidates pass the LLM product check (appfit.py; name, developer and the store
description, since Google Play search has no genre). An app the model calls "no" leaves the set, so it no longer takes
one of the MAX_APPS places. config/gplay_keep.yaml (niche id -> [appId]) keeps an app the check dropped. Without
LLM_API_KEY the check is skipped with a note. Then at most MAX_APPS apps per (niche, country) are kept, by best
position.

Input: data/out/gplay_search.csv. Outputs: data/out/gplay_match.csv (the list the app-details stage fetches) and
data/out/gplay_fit.csv (every candidate with the check's answer, for an eyeball check). The product check costs LLM
tokens (one call per 60 candidates, cached in data/cache/llm/).
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict

from nichefinder import appfit, keys, niches
from nichefinder.workspace import Workspace

SUMMARY = "Filter Google Play results to relevant apps per niche (regex candidates + LLM product check)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

MAX_APPS = 30
FIELDS = ["niche_id", "country", "appId", "title", "developer", "hits", "best_pos"]
FIT_FIELDS = ["niche_id", "country", "appId", "title", "developer", "hits", "best_pos", "fit", "by", "why"]


def run(ws: Workspace, args: argparse.Namespace) -> None:
    kw = ws.load_config("deal_keywords.yaml", {}) or {}
    cov = ws.load_config("coverage_keywords.yaml", {}) or {}
    keep_cfg = ws.load_config("gplay_keep.yaml", {}) or {}
    all_niches = {x["id"]: x for x in niches.load_niches(ws)}
    use_fit = bool(keys.get("LLM_API_KEY"))
    if not use_fit:
        print("no LLM_API_KEY: the product check is skipped, relevance by regex and position only")
    rx, neg = {}, {}
    for nid, p in kw.items():
        if isinstance(p, dict):
            rx[nid] = re.compile(p["re"], re.I)
            neg[nid] = re.compile(p["not"], re.I) if p.get("not") else None
        else:
            rx[nid] = re.compile(p, re.I)
            neg[nid] = None
    rows = list(csv.DictReader(open(ws.out("gplay_search.csv"), encoding="utf-8-sig")))
    by = defaultdict(dict)
    for r in rows:
        k = (r["niche_id"], r["country"])
        a = by[k].setdefault(r["appId"], {**r, "hits": 0, "best_pos": 999})
        a["hits"] += 1
        a["best_pos"] = min(a["best_pos"], int(r["pos"]))
    out, fit_rows = [], []
    n_cand = n_drop = 0
    for (nid, country), apps in sorted(by.items()):
        cov_terms = [str(t).lower() for t in (cov.get(nid) or [])]
        cands = []
        for a in apps.values():
            text = f"{a['title']} {a['summary']}"
            bad = neg.get(nid) and neg[nid].search(text)
            ok = False
            if not bad:
                if nid in rx and rx[nid].search(text):
                    ok = True
                elif any(t in text.lower() for t in cov_terms):
                    ok = True
                elif a["hits"] >= 2 and a["best_pos"] <= 10:
                    ok = True
            if ok:
                cands.append(a)
        cands.sort(key=lambda a: (a["best_pos"], -a["hits"]))
        fit = [("", "")] * len(cands)
        if use_fit and cands and nid in all_niches:
            fit = appfit.check(ws, all_niches[nid], [{"app": a["title"], "developer": a["developer"], "about": a["summary"]} for a in cands])
        keep_ids = {str(x) for x in (keep_cfg.get(nid) or [])}
        keep = []
        for a, (f_fit, f_why) in zip(cands, fit):
            by_who = "config" if a["appId"] in keep_ids else ("llm" if f_fit else "")
            ok = a["appId"] in keep_ids or f_fit != "no"
            fit_rows.append({"niche_id": nid, "country": country, "appId": a["appId"], "title": a["title"], "developer": a["developer"],
                             "hits": a["hits"], "best_pos": a["best_pos"], "fit": f_fit, "by": by_who, "why": f_why})
            if ok:
                keep.append(a)
        dropped = len(cands) - len(keep)
        n_cand += len(cands) if use_fit else 0
        n_drop += dropped
        for a in keep[:MAX_APPS]:
            out.append({"niche_id": nid, "country": country, "appId": a["appId"], "title": a["title"], "developer": a["developer"], "hits": a["hits"], "best_pos": a["best_pos"]})
        print(f"{nid:36} {country} results={len(apps):>3} candidates={len(cands):>3} relevant={len(keep):>3}"
              + (f" (product check dropped {dropped})" if use_fit else ""))
    if n_cand:
        print(f"product check: {n_drop} of {n_cand} candidates are not products of their niche")
    p = ws.out("gplay_match.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    with open(ws.out("gplay_fit.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIT_FIELDS)
        w.writeheader()
        w.writerows(fit_rows)
    print("->", p, len(out))
