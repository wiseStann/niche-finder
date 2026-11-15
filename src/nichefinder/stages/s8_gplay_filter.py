"""Relevance filter for Google Play search results (gplay_search.csv), per niche, by regex.

English: config/deal_keywords.yaml (`re` plus an optional `not`, or a bare regex). Russian (and English with no
match): the phrases of config/coverage_keywords.yaml as substrings, without word boundaries (Cyrillic).
Position rule: an app that shows up in two or more queries of the niche, best position 10 or better, counts as
relevant unless it matches `not`. At most 30 apps per (niche, country) are kept.

Input: data/out/gplay_search.csv. Output: data/out/gplay_match.csv (the list the app-details stage fetches).
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict

from nichefinder.workspace import Workspace

SUMMARY = "Filter Google Play results to relevant apps per niche"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

MAX_APPS = 30
FIELDS = ["niche_id", "country", "appId", "title", "developer", "hits", "best_pos"]


def run(ws: Workspace, args: argparse.Namespace) -> None:
    kw = ws.load_config("deal_keywords.yaml")
    cov = ws.load_config("coverage_keywords.yaml")
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
    out = []
    for (nid, country), apps in sorted(by.items()):
        cov_terms = [str(t).lower() for t in (cov.get(nid) or [])]
        keep = []
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
                keep.append(a)
        keep.sort(key=lambda a: (a["best_pos"], -a["hits"]))
        for a in keep[:MAX_APPS]:
            out.append({"niche_id": nid, "country": country, "appId": a["appId"], "title": a["title"], "developer": a["developer"], "hits": a["hits"], "best_pos": a["best_pos"]})
        print(f"{nid:36} {country} results={len(apps):>3} relevant={len(keep):>3}")
    p = ws.out("gplay_match.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print("->", p, len(out))
