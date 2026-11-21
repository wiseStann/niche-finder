"""How many target businesses exist: the "who" of a B2B niche counted in official registers instead of guessed.

US: Census County Business Patterns (establishments with employees, by NAICS 2017, all legal forms) for the latest year and
the year before (change), the number of establishments under 20 employees, and Nonemployer Statistics (firms without
employees: sole proprietors such as solo hairdressers). Both are national bulk files, free and keyless
(www2.census.gov/programs-surveys/...; the Census API itself now wants a key, the bulk files do not).
Russia: the per-niche sums of ru_msp_counts (data/out/ru_msp_niches.csv, FNS register of small and medium businesses),
joined here when that file exists.

Input: config/who_counts.yaml (niche -> naics / okved codes, a hand-kept map; only niches whose buyers are businesses of one
industry). Cache: data/cache/census/ (the zip files, ~2 MB in total; the directory listings per month).
Output: data/out/who_counts.csv. Evidence only: it never changes the score. Passports set it beside the path-to-goal
numbers, so "payers needed" can be read as a share of the businesses that exist.

Caveats: CBP counts establishments (locations), not firms, so chains count once per location. A NAICS code can be wider
than the niche; the config note says whether a number is a ceiling or a floor. Russian numbers miss the self-employed.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import zipfile

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "How many target businesses exist: US Census CBP / Nonemployer and the Russian SME register"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

BASE = "https://www2.census.gov/programs-surveys/"
CBP = BASE + "cbp/datasets/"
NONEMP = BASE + "nonemployer-statistics/datasets/"


def _listing(ws: Workspace, url: str) -> str:
    try:
        return http.get_text(url, cache=ws.cache("census"), cache_key=f"ls_{url}_{ws.today:%Y-%m}", ext=".html",
                             min_size=500, raise_for_status=False, tries=2)
    except OSError:
        return ""


def _years(html: str) -> list[int]:
    return sorted({int(y) for y in re.findall(r'href="(\d{4})/"', html)}, reverse=True)


def find_cbp(ws: Workspace) -> list[tuple[int, str]]:
    """[(year, url)] of the national CBP files, newest first."""
    out = []
    for y in _years(_listing(ws, CBP)):
        name = f"cbp{y % 100:02d}us.zip"
        if name in _listing(ws, f"{CBP}{y}/"):
            out.append((y, f"{CBP}{y}/{name}"))
    return out


def find_nonemp(ws: Workspace) -> tuple[int, str] | None:
    for y in _years(_listing(ws, NONEMP)):
        name = f"nonemp{y % 100:02d}us.zip"
        for sub in ("", "historical-datasets/"):
            if name in _listing(ws, f"{NONEMP}{y}/{sub}"):
                return y, f"{NONEMP}{y}/{sub}{name}"
    return None


def _zip_csv(path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith((".txt", ".csv")))
        text = z.read(name).decode("latin-1")
    rows = list(csv.DictReader(io.StringIO(text)))
    return [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in rows]


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def load_cbp(path) -> dict[str, dict]:
    """NAICS code (slashes stripped) -> {est, lt20}, all legal forms."""
    out = {}
    for r in _zip_csv(path):
        if r.get("lfo") != "-":
            continue
        code = r.get("naics", "").replace("/", "").replace("-", "")
        if not code:
            continue
        out[code] = {"est": _int(r.get("est")), "lt20": _int(r.get("n<5")) + _int(r.get("n5_9")) + _int(r.get("n10_19"))}
    return out


def load_nonemp(path) -> dict[str, int]:
    """NAICS code -> nonemployer firms (national, all legal forms, all receipt sizes)."""
    out = {}
    for r in _zip_csv(path):
        if r.get("st") == "00" and r.get("lfo") == "-" and r.get("rcptot_size") == "001":
            out[r.get("naics", "")] = _int(r.get("estab"))
    return out


def nonemp_lookup(nonemp: dict | None, code: str) -> int | None:
    """Nonemployer Statistics publish 452 codes of mixed depth. A 6-digit NAICS code ending in 0 is, by the NAICS
    convention, the same industry as its 5-digit parent, so that parent stands in for it; otherwise exact codes only."""
    if not nonemp:
        return None
    if code in nonemp:
        return nonemp[code]
    if len(code) == 6 and code.endswith("0"):
        return nonemp.get(code[:5])
    return None


def niche_rows(cmap: dict, cur: dict, prev: dict | None, nonemp: dict | None, ru: dict[str, dict]) -> list[dict]:
    rows = []
    for nid, spec in (cmap or {}).items():
        spec = spec or {}
        codes = [str(c) for c in spec.get("naics") or []]
        found = [c for c in codes if c in cur]
        est = sum(cur[c]["est"] for c in found)
        lt20 = sum(cur[c]["lt20"] for c in found)
        p = sum(prev[c]["est"] for c in found if c in prev) if prev else 0
        ne = [v for v in (nonemp_lookup(nonemp, c) for c in codes) if v is not None]
        r = ru.get(nid, {})
        rows.append({"niche_id": nid, "naics": " ".join(codes),
                     "us_est": est if found else "", "us_est_prev": p or "",
                     "us_est_yoy": round(est / p - 1, 3) if p else "",
                     "us_lt20": lt20 if found else "", "us_lt20_share": round(lt20 / est, 2) if est else "",
                     "us_nonemp": sum(ne) if ne else "",
                     "missing": " ".join(c for c in codes if c not in cur),
                     "okved": r.get("okved", " ".join(str(c) for c in spec.get("okved") or [])),
                     "ru_msp": r.get("msp", ""), "ru_msp_yoy": r.get("msp_yoy", ""), "ru_ip_share": r.get("ip_share", ""),
                     "note": spec.get("note", "")})
    return rows


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cmap = ws.load_config("who_counts.yaml", {})
    if not cmap:
        print("config/who_counts.yaml is missing or empty - nothing to count")
        return
    cbp = find_cbp(ws)
    if not cbp:
        raise SystemExit(f"no national CBP file found under {CBP}")
    files = {}
    for y, url in cbp[:2]:
        files[y] = load_cbp(http.download(url, ws.cache("census") / url.rsplit("/", 1)[1], progress=False))
    years = sorted(files, reverse=True)
    cur, prev = files[years[0]], (files[years[1]] if len(years) > 1 else None)
    ne = find_nonemp(ws)
    nonemp = load_nonemp(http.download(ne[1], ws.cache("census") / ne[1].rsplit("/", 1)[1], progress=False)) if ne else None
    ru = {}
    rp = ws.out("ru_msp_niches.csv")
    if rp.is_file():
        ru = {r["niche_id"]: r for r in csv.DictReader(open(rp, encoding="utf-8"))}
    rows = niche_rows(cmap, cur, prev, nonemp, ru)
    for r in rows:
        r["us_year"], r["us_prev_year"], r["nonemp_year"] = years[0], (years[1] if prev else ""), (ne[0] if ne else "")
    with open(ws.out("who_counts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"CBP {years[0]}" + (f" vs {years[1]}" if prev else "") + (f", nonemployers {ne[0]}" if ne else "")
          + (", Russian register joined" if ru else ", Russian register not available yet (run ru_msp_counts)"))
    for r in rows:
        yoy = f"{r['us_est_yoy']:+.1%}" if r["us_est_yoy"] != "" else "   -  "
        print(f"  {r['niche_id']:36} US est {r['us_est'] or '-':>8} {yoy}  <20: {r['us_lt20_share'] or '-':>4}  "
              f"nonemp {r['us_nonemp'] or '-':>8}  RU {r['ru_msp'] or '-':>8}" + (f"  missing {r['missing']}" if r["missing"] else ""))
    print("-> who_counts.csv", len(rows))
