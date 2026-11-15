"""Russian B2B: hh.ru vacancy counts per niche (job-market signals).

hh.ru refuses foreign IPs, so live requests go through the Russian proxy: set NF_PROXY_RU (a proxy URL) in .env or the
environment, or run from a machine with a Russian IP. Cached answers need no network.

Two signals per niche from config/ru_b2b_niches.yaml:
  hh_roles  - vacancies with the role in the TITLE (exact phrase, area=113 = Russia): the labour the product would automate;
  hh_brands - vacancies mentioning a brand in the title or description: software that companies hire people to run.
Cache: data/cache/hh/ (one text file per term and search field). Output: data/out/ru_b2b_hh.csv, ru_b2b_hh_terms.csv.
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from urllib.parse import quote

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Russian B2B: hh.ru vacancies on automatable roles and brands"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)

_warned = [False]


def count(ws: Workspace, term: str, fields: str):
    key = re.sub(r"[^\w]+", "_", term.lower()) + ("" if fields == "both" else "__" + fields)
    path = ws.cache("hh") / f"{key}.txt"
    if path.is_file():
        txt = path.read_text(encoding="utf-8").strip()
    else:
        f = "search_field=name&search_field=description" if fields == "both" else "search_field=name"
        url = f"https://hh.ru/search/vacancy?text=%22{quote(term)}%22&area=113&{f}"
        txt = ""
        for attempt in range(3):
            try:
                page = http.request(url, backend="curl", proxy="ru", timeout=25, tries=1, raise_for_status=False)
                m = re.search(r"<h1[^>]*><span>[^<]*</span>|empty-vacancy-search-block", page.text) if page.status == 200 else None
                txt = m.group(0) if m else ""
            except OSError:
                txt = ""
            if txt:
                break
            time.sleep(4)
        if txt:
            path.write_text(txt, encoding="utf-8")
        elif not _warned[0]:
            _warned[0] = True
            print("  ! hh.ru gave no usable answer (foreign IP?); set NF_PROXY_RU to a Russian proxy")
        time.sleep(1.0)
    if "empty-vacancy" in txt:
        return 0
    if txt.strip().isdigit():   # a cached plain number
        return int(txt.strip())
    m = re.search(r"<span>[^<]*?(\d[\d\s\xa0 ]*)", txt)   # "Found 655 vacancies"
    return int(re.sub(r"\D", "", m.group(1))) if m and re.sub(r"\D", "", m.group(1)) else None


def run(ws: Workspace, args: argparse.Namespace) -> None:
    niches = ws.load_config("ru_b2b_niches.yaml")
    rows, terms = [], []
    for n in niches:
        roles, brands = {}, {}
        for t in n.get("hh_roles") or []:
            roles[t] = count(ws, t, "name")
            terms.append({"niche_id": n["id"], "kind": "role", "term": t, "vacancies": roles[t]})
        for t in n.get("hh_brands") or []:
            brands[t] = count(ws, t, "both")
            terms.append({"niche_id": n["id"], "kind": "brand", "term": t, "vacancies": brands[t]})
        rv = [v for v in roles.values() if v is not None]
        bv = [v for v in brands.values() if v is not None]
        rows.append({"niche_id": n["id"], "roles_sum": sum(rv), "roles_max": max(rv) if rv else "", "roles_detail": "; ".join(f"{k}={v}" for k, v in roles.items()),
                     "brands_sum": sum(bv), "brands_detail": "; ".join(f"{k}={v}" for k, v in brands.items())})
        print(f"{n['id']:32} roles={rows[-1]['roles_sum']:6} [{rows[-1]['roles_detail']}] brands={rows[-1]['brands_sum']:5} [{rows[-1]['brands_detail']}]", flush=True)
    with open(ws.out("ru_b2b_hh.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("ru_b2b_hh_terms.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "kind", "term", "vacancies"])
        w.writeheader()
        w.writerows(terms)
    print("-> ru_b2b_hh.csv", len(rows))
