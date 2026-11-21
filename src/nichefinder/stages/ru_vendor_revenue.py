"""Russian B2B: income of the software vendors in each niche, from public financial statements (FNS open data).

The vendors are the right holders that ru_reestr found in the domestic software register for the niche
(data/out/ru_b2b_reestr_items.csv, column `owner`). Their income and expenses come from the FNS open dataset
"income and expenses from the financial statements of organisations" (https://www.nalog.gov.ru/opendata/7707329152-revexp/,
free, no key, ~100 MB zip of XML per yearly release: legal name, INN, income, expenses). The latest release on or before
ws.today is compared with the previous one (the page lists only the latest, so the previous one is the zip kept in the cache
by an earlier run): vendors matched in both give a revenue growth figure that does not come from search. The interactive statements site (bo.nalog.ru) is not used: it answers scripts with an empty application shell.

Matching is by normalised legal name (legal form, quotes and case removed). A name shared by several companies is
`ambiguous` and left out of the sums; individual entrepreneurs do not file statements and stay unmatched. A vendor with
income above --max-income (default 20 bn RUB) is `diversified` (a large group whose income is not this niche's money):
it is listed but left out of the sums.
Outputs: data/out/ru_vendor_revenue.csv (per niche), ru_vendor_revenue_vendors.csv (per niche and vendor).
Cache: the release zips in data/cache/revexp/ (kept: they are small). Evidence only, not in any score.
Caveats: income is the whole company's, not the product's; a small vendor's statement may be missing or published late.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import re
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Revenue of Russian software vendors from public financial statements (FNS open data)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

INDEX = "https://www.nalog.gov.ru/opendata/7707329152-revexp/"
FILES = "https://file.nalog.ru/opendata/7707329152-revexp/"
REL_RE = re.compile(r"data-(\d{4})(\d{2})(\d{2})-structure-\d{8}\.zip")
DOC = re.compile(r'НаимОрг="([^"]*)"\s+ИННЮЛ="(\d+)"')
INC = re.compile(r'СумДоход="([\d.]+)"')
EXP = re.compile(r'СумРасход="([\d.]+)"')
YEAR = re.compile(r'ДатаСост="\d\d\.\d\d\.(\d{4})"')
LEGAL_FORMS = [
    "общество с ограниченной ответственностью", "непубличное акционерное общество", "публичное акционерное общество",
    "закрытое акционерное общество", "открытое акционерное общество", "акционерное общество",
    "автономная некоммерческая организация", "федеральное государственное унитарное предприятие",
    "государственное унитарное предприятие", "индивидуальный предприниматель",
    "ооо", "пао", "зао", "оао", "нао", "ао", "ано", "фгуп", "гуп", "ип",
]
_FORMS = re.compile(r"(?<![а-яa-z0-9])(" + "|".join(re.escape(f) for f in LEGAL_FORMS) + r")(?![а-яa-z0-9])")


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-income", type=float, default=20e9, help="RUB; above it a vendor is 'diversified' (default 20e9)")


_FORMS_I = re.compile(_FORMS.pattern, re.I)


def short(name: str) -> str:
    """A display name: the legal form and quotes removed, case kept."""
    s = _FORMS_I.sub(" ", html.unescape(name or ""))
    return " ".join(re.sub(r"[\"'«»“”„]", " ", s).split()) or (name or "")


def norm(name: str) -> str:
    s = html.unescape(name or "").lower().replace("ё", "е")
    s = _FORMS.sub(" ", s)
    s = re.sub(r"[\"'«»“”„()]", " ", s)
    s = re.sub(r"[^\w\s-]", " ", s)
    return " ".join(s.split())


def list_releases(ws: Workspace) -> dict[dt.date, str]:
    """Releases listed on the page plus those already in the cache: the page lists only the latest release, so the
    year-on-year comparison relies on the zip kept from an earlier run."""
    page = http.get_text(INDEX, cache=ws.cache("revexp"), cache_key=f"index_{ws.today:%Y-%m}", ext=".html", min_size=20_000)
    names = [m.group(0) for m in REL_RE.finditer(page)] + [p.name for p in ws.cache("revexp").glob("data-*.zip")]
    out = {}
    for name in names:
        m = REL_RE.fullmatch(name)
        if m:
            out[dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = name
    return out


def pick(rel: dict[dt.date, str], today: dt.date) -> tuple[dt.date | None, dt.date | None]:
    ok = sorted(d for d in rel if d <= today)
    if not ok:
        return None, None
    last = ok[-1]
    prev = [d for d in ok if d <= last - dt.timedelta(days=300)]
    return last, (prev[-1] if prev else None)


def scan(path: Path, wanted: set[str]) -> tuple[dict[str, list[dict]], str]:
    """Normalised name -> [{inn, name, income, expense}] for the wanted names only; plus the reporting year."""
    out: dict[str, list[dict]] = defaultdict(list)
    year = ""
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".xml"):
                continue
            text = z.read(info).decode("utf-8", errors="replace")
            if not year:
                m = YEAR.search(text)
                year = m.group(1) if m else ""
            for chunk in text.split("<Документ ")[1:]:
                m = DOC.search(chunk)
                if not m:
                    continue
                key = norm(m.group(1))
                if key not in wanted:
                    continue
                inc, exp = INC.search(chunk), EXP.search(chunk)
                out[key].append({"inn": m.group(2), "name": html.unescape(m.group(1)),
                                 "income": float(inc.group(1)) if inc else 0.0, "expense": float(exp.group(1)) if exp else 0.0})
    return out, year


def owners_by_niche(ws: Workspace) -> dict[str, set[str]]:
    p = ws.out("ru_b2b_reestr_items.csv")
    out: dict[str, set[str]] = defaultdict(set)
    if p.is_file():
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if r.get("owner"):
                out[r["niche_id"]].add(r["owner"].strip())
    return out


def summarize(owners: dict[str, set[str]], now: dict, prev: dict | None, cap: float):
    rows, vend = [], []
    for nid, names in sorted(owners.items()):
        matched, amb, unmatched, div = [], 0, 0, []
        for o in sorted(names):
            hits = now.get(norm(o), [])
            uniq = {h["inn"]: h for h in hits}
            if not uniq:
                unmatched += 1
                status, h = "unmatched", None
            elif len(uniq) > 1:
                amb += 1
                status, h = "ambiguous", None
            else:
                h = dict(next(iter(uniq.values())), owner=o)
                status = "diversified" if h["income"] > cap else "matched"
                (div if status == "diversified" else matched).append(h)
            p = None
            if h and prev is not None:
                ph = {x["inn"]: x for x in prev.get(norm(o), [])}.get(h["inn"])
                p = ph["income"] if ph else None
            vend.append({"niche_id": nid, "owner": o, "status": status, "inn": h["inn"] if h else "",
                         "income": round(h["income"]) if h else "", "expense": round(h["expense"]) if h else "",
                         "income_prev": round(p) if p is not None else ""})
        inc = sorted((h["income"] for h in matched), reverse=True)
        both = [v for v in vend if v["niche_id"] == nid and v["status"] == "matched" and v["income_prev"] not in ("", 0)]
        g_now, g_prev = sum(v["income"] for v in both), sum(v["income_prev"] for v in both)
        top = max(matched, key=lambda h: h["income"], default=None)
        rows.append({"niche_id": nid, "owners": len(names), "matched": len(matched), "ambiguous": amb,
                     "unmatched": unmatched, "diversified": len(div),
                     "income_sum": round(sum(inc)), "income_median": round(statistics.median(inc)) if inc else "",
                     "vendors_100m": sum(1 for x in inc if x >= 1e8), "vendors_1bn": sum(1 for x in inc if x >= 1e9),
                     "top_vendor": short(top["owner"]) if top else "", "top_income": round(top["income"]) if top else "",
                     "top_share": round(top["income"] / sum(inc), 2) if top and sum(inc) else "",
                     "growth_matched": len(both), "income_growth": round(g_now / g_prev - 1, 3) if g_prev else ""})
    return rows, vend


def run(ws: Workspace, args: argparse.Namespace) -> None:
    owners = owners_by_niche(ws)
    if not owners:
        print("data/out/ru_b2b_reestr_items.csv not found or empty - run ru_reestr first; skipping")
        return
    rel = list_releases(ws)
    last, prev = pick(rel, ws.today)
    if not last:
        print(f"no release on or before {ws.today} on {INDEX}; skipping")
        return
    wanted = {norm(o) for names in owners.values() for o in names}
    data = {}
    for d in (last, prev):
        if not d:
            continue
        path = http.download(FILES + rel[d], ws.cache("revexp") / rel[d], timeout=300, progress=False)
        data[d] = scan(path, wanted)
        print(f"release {d}: statements for {data[d][1]}, {sum(len(v) for v in data[d][0].values())} name hits")
    now, year = data[last]
    before = data[prev][0] if prev else None
    rows, vend = summarize(owners, now, before, args.max_income)
    for r in rows:
        r["year"] = year
        r["year_prev"] = data[prev][1] if prev else ""
    with open(ws.out("ru_vendor_revenue.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("ru_vendor_revenue_vendors.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(vend[0].keys()))
        w.writeheader()
        w.writerows(vend)
    for r in sorted(rows, key=lambda r: -r["income_sum"]):
        g = f"{r['income_growth']:+.0%}" if r["income_growth"] != "" else "  -"
        print(f"  {r['niche_id']:32} owners {r['owners']:3} matched {r['matched']:3} amb {r['ambiguous']:2} "
              f"income {r['income_sum'] / 1e6:9,.0f}M RUB  >=100M {r['vendors_100m']:2}  growth {g:>5}  top {r['top_vendor'][:40]}")
    print(f"-> ru_vendor_revenue.csv {len(rows)}, ru_vendor_revenue_vendors.csv {len(vend)}")
