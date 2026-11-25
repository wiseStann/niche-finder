"""Russian B2B: public procurement (zakupki.gov.ru) — demand with money (B2B/B2G).

For the `zakupki` phrases of each niche in config/ru_b2b_niches.yaml: number of procurements matching the exact phrase in the
last 12 months and the 12 months before (windows end at the run date), and the sum and median of the initial contract price for
procurements that have the phrase in their title (full-text search also matches attachments, which is noise). "In the title"
means every significant word of the phrase is there (`title_rule`): a word of up to three letters as a whole word, a longer one
as its stem at the start of a word, so "hotel" in the instrumental case finds the genitive but not "boiler room", which contains
the same four letters. Until 2026-11-25 one word was enough, and the hotel phrase "management system of a hotel" counted
boiler-room and radio procurements (124 instead of 2).
Laws 44-FZ and 223-FZ, all statuses. Cache: data/cache/zakupki/. Output: data/out/ru_b2b_zakupki.csv. Free, no key.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import re
import time
from urllib.parse import quote

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Russian B2B: public procurement counts and contract sums"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)


def url(q, d1, d2, page):
    return ("https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=" + quote(f'"{q}"') +
            f"&morphology=on&pageNumber={page}&sortDirection=false&recordsPerPage=_50&showLotsInfoHidden=false&sortBy=UPDATE_DATE"
            f"&fz44=on&fz223=on&af=on&ca=on&pc=on&pa=on&currencyIdGeneral=-1&publishDateFrom={d1:%d.%m.%Y}&publishDateTo={d2:%d.%m.%Y}")


def get(ws: Workspace, u: str) -> str:
    key = hashlib.sha1(u.encode()).hexdigest()
    path = ws.cache("zakupki") / (key + ".html")
    if path.is_file():
        return path.read_text(encoding="utf-8")
    for attempt in range(3):
        try:
            s = http.request(u, backend="curl", timeout=60, tries=1, raise_for_status=False).text
        except OSError:
            s = ""
        if "search-results__total" in s:
            path.write_text(s, encoding="utf-8")
            time.sleep(1.5)
            return s
        time.sleep(6 * (attempt + 1))
    return ""


STOP = {"и", "в", "во", "на", "по", "для", "с", "со", "к", "ко", "от", "из", "о", "об", "при", "за"}


def title_rule(q: str) -> list[re.Pattern]:
    """One pattern per significant word of the phrase. Words of up to three letters (abbreviations such as TMS or CRM) must
    stand whole; a longer word drops its inflection (1 letter at 5, 2 at 6-7, 3 from 8 letters) and must start a word."""
    pats = []
    for w in re.findall(r"[а-яa-z0-9-]+", q.lower().replace("ё", "е")):
        if w in STOP:
            continue
        if len(w) <= 3:
            pats.append(re.compile(rf"(?<!\w){re.escape(w)}(?!\w)"))
        else:
            cut = 3 if len(w) >= 8 else 2 if len(w) >= 6 else 1 if len(w) == 5 else 0
            pats.append(re.compile(rf"(?<!\w){re.escape(w[:len(w) - cut])}"))
    return pats


def in_title(pats: list[re.Pattern], title: str) -> bool:
    t = title.lower().replace("ё", "е")
    return bool(pats) and all(p.search(t) for p in pats)


def parse(s):
    m = re.search(r"search-results__total[^>]*>\s*([\d\s]+)", s)
    total = int(re.sub(r"\D", "", m.group(1))) if m and re.sub(r"\D", "", m.group(1)) else 0
    entries = []
    for blk in re.split(r'class="search-registry-entry-block', s)[1:]:
        title = re.search(r'registry-entry__body-value">(.*?)</div>', blk, flags=re.S)
        t = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else ""
        price = re.search(r"price-block__value[^>]*>\s*([\d\s\xa0]+,\d\d)", blk)
        p = float(re.sub(r"[^\d,]", "", price.group(1)).replace(",", ".")) if price else None
        entries.append((t, p))
    return total, entries


def run(ws: Workspace, args: argparse.Namespace) -> None:
    today = ws.today
    win = [("last12", today - dt.timedelta(days=365), today), ("prev12", today - dt.timedelta(days=730), today - dt.timedelta(days=366))]
    niches = ws.load_config("ru_b2b_niches.yaml")
    rows = []
    for n in niches:
        agg = {w: {"total": 0, "titled": 0, "prices": []} for w, _, _ in win}
        detail = []
        for q in n.get("zakupki") or []:
            pats = title_rule(q)
            for w, d1, d2 in win:
                s = get(ws, url(q, d1, d2, 1))
                if not s:
                    detail.append(f"{q}/{w}=ERR")
                    continue
                total, entries = parse(s)
                page = 2
                while len(entries) < min(total, 150) and page <= 3:
                    t2, e2 = parse(get(ws, url(q, d1, d2, page)) or "")
                    if not e2:
                        break
                    entries += e2
                    page += 1
                titled = [(t, p) for t, p in entries if in_title(pats, t)]
                agg[w]["total"] += total
                agg[w]["titled"] += len(titled)
                agg[w]["prices"] += [p for _, p in titled if p]
                detail.append(f"{q}/{w}={total}({len(titled)})")
        pr = sorted(agg["last12"]["prices"])
        rows.append({"niche_id": n["id"], "last12_total": agg["last12"]["total"], "prev12_total": agg["prev12"]["total"],
                     "last12_titled": agg["last12"]["titled"], "prev12_titled": agg["prev12"]["titled"],
                     "yoy_total": round(agg["last12"]["total"] / agg["prev12"]["total"] - 1, 2) if agg["prev12"]["total"] else "",
                     "last12_sum_rub": round(sum(pr)), "last12_median_rub": round(pr[len(pr) // 2]) if pr else "",
                     "detail": "; ".join(detail)})
        r = rows[-1]
        print(f"{n['id']:32} procurements 12m/prev: {r['last12_total']:4}/{r['prev12_total']:4} (in title {r['last12_titled']}/{r['prev12_titled']}), "
              f"sum {r['last12_sum_rub'] / 1e6:7.1f} M RUB, median {r['last12_median_rub']}", flush=True)
    with open(ws.out("ru_b2b_zakupki.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("-> ru_b2b_zakupki.csv", len(rows))
