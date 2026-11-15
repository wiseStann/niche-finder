"""hh.ru vacancies that mention a niche's software brands: an adoption proxy for Russian B2B niches
("administrator wanted, YCLIENTS experience required").

The hh.ru API is closed without OAuth, so the stage reads the HTML search page ("Found N vacancies"). hh.ru
refuses foreign IPs: set NF_PROXY_RU to a Russian HTTP proxy (the request goes through http.request(proxy="ru")).
Brands are the Russian `brand` queries from queries/*.yaml of niches with side b2b* and geo both/ru. The search is
an exact phrase in quotes, area=113 (Russia), in vacancy names and descriptions. Horizontal platforms (1C,
Bitrix24, amoCRM, big banks) and brand queries that are really phrases are skipped.

Output: data/out/hh_vacancies.csv (per brand) and data/out/hh_niche.csv (per niche). Cache: data/cache/hh/<brand>.txt.
Cost: free, no key; about 1 s per new brand.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections import defaultdict
from urllib.parse import quote

from nichefinder import http, keys, niches
from nichefinder.workspace import Workspace

SUMMARY = "hh.ru vacancies mentioning niche brands (Russian adoption proxy)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

# Horizontal products: not a niche signal.
SKIP = {"1с", "1c", "битрикс24", "битрикс 24", "амосрм", "amocrm", "мой склад", "мойсклад", "тинькофф", "сбер", "яндекс", "госуслуги"}
PHRASE = r"приложени|программ|график|сервис|саммари"   # a phrase, not a brand: hh searches by words


def parse_count(txt: str) -> str:
    """Vacancy count from a cached value, or from the <h1> of a search page / the empty-result marker."""
    txt = txt.strip()
    if re.fullmatch(r"\d*", txt):
        return txt
    m = re.search(r"<h1[^>]*><span>[^<]*</span>|empty-vacancy-search-block", txt)
    txt = m.group(0) if m else ""
    m = re.search(r"<span>([^<]*)</span>", txt)
    digits = re.sub(r"\D", "", m.group(1) if m else "")
    return digits if digits else ("0" if "empty-vacancy-search-block" in txt else "")


def count(cache, brand):
    key = re.sub(r"[^\w]+", "_", brand.lower())
    path = cache / f"{key}.txt"
    if path.exists():
        return parse_count(path.read_text(encoding="utf-8"))
    url = f"https://hh.ru/search/vacancy?text=%22{quote(brand)}%22&area=113&search_field=name&search_field=description"
    val = ""
    for attempt in range(2):
        try:
            val = parse_count(http.request(url, proxy="ru", timeout=25, tries=1, raise_for_status=False).text)
        except OSError:
            val = ""
        if val:
            break
        time.sleep(3)
    if val:   # a failed fetch is not cached
        path.write_text(val, encoding="utf-8")
    time.sleep(1.0)
    return val


def run(ws: Workspace, args: argparse.Namespace) -> None:
    if not keys.get("NF_PROXY_RU"):
        sys.stderr.write("warning: NF_PROXY_RU is not set; hh.ru usually refuses non-Russian IPs\n")
    cache = ws.cache("hh")
    q = niches.load_queries(ws)
    rows, agg = [], defaultdict(list)
    for n in niches.load_niches(ws):
        nid = n["id"]
        if not n["side"].startswith("b2b") or n["geo"] not in ("both", "ru"):
            continue
        brands = [e["q"] for e in (q.get(nid, {}).get("ru") or []) if e.get("i") == "brand"]
        for b in brands:
            if b.lower().strip() in SKIP or re.search(PHRASE, b.lower()):
                continue
            v = count(cache, b)
            rows.append({"niche_id": nid, "brand": b, "vacancies": v})
            if v != "":
                agg[nid].append((b, int(v)))
            print(f"{nid:36} {b[:28]:28} {v}", flush=True)
    p = ws.out("hh_vacancies.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "brand", "vacancies"])
        w.writeheader()
        w.writerows(rows)
    p2 = ws.out("hh_niche.csv")
    with open(p2, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "brands", "vacancies_sum", "top_brand", "top_vacancies", "top_share"])
        w.writeheader()
        for nid, lst in agg.items():
            tot = sum(v for _, v in lst)
            top = max(lst, key=lambda x: x[1])
            w.writerow({"niche_id": nid, "brands": len(lst), "vacancies_sum": tot, "top_brand": top[0], "top_vacancies": top[1], "top_share": round(top[1] / tot, 2) if tot else ""})
    print("->", p, len(rows), "|", p2, len(agg))
