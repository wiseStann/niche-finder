"""Russian SME register (FNS open data): how many small and medium businesses exist per main activity code (OKVED2),
and how that number moved over a year. This counts the "who" of a Russian B2B niche instead of guessing it.

Source: the monthly dump of the Unified register of small and medium businesses, https://www.nalog.gov.ru/opendata/7707329152-rsmp/
(free, no key; about 2.2 GB of zipped XML per month, ~6.5 million records). The stage takes the latest dump dated on or
before ws.today and, unless --no-compare, the dump about 12 months earlier. Each record gives the kind (legal entity /
individual entrepreneur), the size category (micro / small / medium), a "newly created" flag and the main OKVED code.
Counting happens while the zip is read, member by member; nothing is extracted to disk.

Cache: the per-dump aggregate data/out/ru_msp/okved_<date>.csv is the cache. The zip itself goes to data/cache/rmsp/ and is
deleted after aggregation unless --keep-dumps, so a re-run costs nothing and a first run downloads ~4.4 GB (about 15 minutes
at 6 MB/s, plus a few minutes of parsing).
Outputs: data/out/ru_msp_okved.csv (every code: total, legal entities, entrepreneurs, micro/small/medium, newly created,
the count a year earlier and the change) and data/out/ru_msp_niches.csv (per niche of config/who_counts.yaml: the sum over
its codes, each code also matching its sub-codes: 43.2 counts 43.21, 43.22.1 ...).

Caveats: the register holds businesses, not the self-employed on the professional income tax (NPD), so trades dominated
by self-employed people (beauty masters, tutors) are undercounted. The main code is self-declared and often generic.
Non-profit and religious organisations are not in the register.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import zipfile
from collections import defaultdict
from pathlib import Path

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Russian SME register (FNS open data): businesses per OKVED code and their yearly growth"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

INDEX = "https://www.nalog.gov.ru/opendata/7707329152-rsmp/"
FILES = "https://file.nalog.ru/opendata/7707329152-rsmp/"
DUMP_RE = re.compile(r"data-(\d{2})(\d{2})(\d{4})-structure-\d{8}\.zip")
DOC_TAG = "<Документ "                       # one register record
A_KIND = re.compile(r'ВидСубМСП="(\d)"')      # 1 legal entity, 2 individual entrepreneur
A_CAT = re.compile(r'КатСубМСП="(\d)"')       # 1 micro, 2 small, 3 medium
A_NEW = re.compile(r'ПризНовМСП="(\d)"')      # 1 newly created
MAIN = re.compile(r'<СвОКВЭДОсн\s+КодОКВЭД="([^"]+)"\s+НаимОКВЭД="([^"]*)"')
AGG_FIELDS = ["code", "name", "kind", "cat", "new", "n"]


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--no-compare", action="store_true", help="only the latest dump, no year-earlier comparison")
    p.add_argument("--keep-dumps", action="store_true", help="keep the 2.2 GB zip files in data/cache/rmsp/")
    p.add_argument("--date", help="use the dump of this date (YYYY-MM-DD) as the latest")


def list_dumps(ws: Workspace) -> dict[dt.date, str]:
    """Dump date -> file name, from the open-data page (cached per month)."""
    html = http.get_text(INDEX, cache=ws.cache("rmsp"), cache_key=f"index_{ws.today:%Y-%m}", ext=".html", min_size=20_000)
    out = {}
    for m in DUMP_RE.finditer(html):
        d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        out[d] = m.group(0)
    return out


def pick(dumps: dict[dt.date, str], today: dt.date, compare: bool, want: dt.date | None = None):
    """The latest dump on or before `want` (default today) and the one closest to 12 months earlier."""
    ok = sorted(d for d in dumps if d <= (want or today))
    if not ok:
        return None, None
    last = ok[-1]
    if not compare:
        return last, None
    target = last - dt.timedelta(days=365)
    prev = min((d for d in ok if d < last - dt.timedelta(days=300)), key=lambda d: abs((d - target).days), default=None)
    return last, prev


def aggregate_text(text: str, acc: dict, names: dict) -> int:
    """Count the records of one XML member into acc[(code, kind, cat)] = [n, new]."""
    n = 0
    for chunk in text.split(DOC_TAG)[1:]:
        head = chunk[:chunk.find(">")]
        m = MAIN.search(chunk)
        code = m.group(1) if m else ""
        if m and code not in names:
            names[code] = m.group(2)
        k = A_KIND.search(head)
        c = A_CAT.search(head)
        nw = A_NEW.search(head)
        cell = acc[(code, "UL" if k and k.group(1) == "1" else "IP", c.group(1) if c else "")]
        cell[0] += 1
        cell[1] += int(bool(nw and nw.group(1) == "1"))
        n += 1
    return n


def aggregate_zip(path: Path) -> tuple[dict, dict, int]:
    acc: dict = defaultdict(lambda: [0, 0])
    names: dict = {}
    total = 0
    with zipfile.ZipFile(path) as z:
        members = [i for i in z.infolist() if i.filename.lower().endswith(".xml")]
        for i, info in enumerate(members, 1):
            total += aggregate_text(z.read(info).decode("utf-8", errors="replace"), acc, names)
            if i % 1000 == 0 or i == len(members):
                print(f"    {i}/{len(members)} files, {total:,} records", flush=True)
    return acc, names, total


def dump_counts(ws: Workspace, day: dt.date, fname: str, keep: bool) -> list[dict]:
    """Per-dump aggregate rows, from data/out/ru_msp/okved_<date>.csv or by downloading and counting the dump."""
    agg = ws.out(f"ru_msp/okved_{day:%Y-%m-%d}.csv")
    if agg.is_file():
        return list(csv.DictReader(open(agg, encoding="utf-8")))
    zpath = ws.cache("rmsp") / fname
    print(f"  downloading {fname} (~2.2 GB) ...", flush=True)
    http.download(FILES + fname, zpath, timeout=300)
    print(f"  counting {fname} ...", flush=True)
    acc, names, total = aggregate_zip(zpath)
    rows = [{"code": code, "name": names.get(code, ""), "kind": kind, "cat": cat, "new": v[1], "n": v[0]}
            for (code, kind, cat), v in sorted(acc.items())]
    tmp = agg.with_suffix(".part")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=AGG_FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(agg)
    print(f"  {day}: {total:,} records, {len({r['code'] for r in rows}):,} codes -> {agg}")
    if not keep:
        zpath.unlink(missing_ok=True)
    return [{k: str(v) for k, v in r.items()} for r in rows]


def by_code(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(r["code"], {"code": r["code"], "name": r["name"], "total": 0, "ul": 0, "ip": 0,
                                       "micro": 0, "small": 0, "medium": 0, "new": 0})
        n = int(r["n"])
        d["total"] += n
        d["ul" if r["kind"] == "UL" else "ip"] += n
        d[{"1": "micro", "2": "small", "3": "medium"}.get(r["cat"], "micro")] += n
        d["new"] += int(r["new"])
        d["name"] = d["name"] or r["name"]
    return out


def matches(code: str, wanted: str) -> bool:
    """OKVED codes are hierarchical by characters: group 43.2 -> subgroups 43.21, 43.22 -> types 43.21.1, so a plain prefix
    is the subtree (every code starts with a two-digit class, so "01.1" never matches "11.1")."""
    return code.startswith(wanted)


def niche_rows(cmap: dict, now: dict[str, dict], prev: dict[str, dict] | None) -> list[dict]:
    out = []
    for nid, spec in (cmap or {}).items():
        codes = [str(c) for c in (spec or {}).get("okved") or []]
        if not codes:
            continue
        hit = [d for c, d in now.items() if any(matches(c, w) for w in codes)]
        tot = sum(d["total"] for d in hit)
        prev_tot = sum(d["total"] for c, d in (prev or {}).items() if any(matches(c, w) for w in codes)) if prev else None
        out.append({"niche_id": nid, "okved": " ".join(codes), "msp": tot,
                    "msp_prev": prev_tot if prev_tot is not None else "",
                    "msp_yoy": round(tot / prev_tot - 1, 3) if prev_tot else "",
                    "ip_share": round(sum(d["ip"] for d in hit) / tot, 2) if tot else "",
                    "micro_share": round(sum(d["micro"] for d in hit) / tot, 2) if tot else "",
                    "new_share": round(sum(d["new"] for d in hit) / tot, 3) if tot else "",
                    "codes_found": len(hit)})
    return out


def run(ws: Workspace, args: argparse.Namespace) -> None:
    compare = not getattr(args, "no_compare", False)
    want = dt.date.fromisoformat(args.date) if getattr(args, "date", None) else None
    dumps = list_dumps(ws)
    last, prev = pick(dumps, ws.today, compare, want)
    if not last:
        print(f"no register dump dated on or before {want or ws.today} on {INDEX}; skipping")
        return
    print(f"latest dump {last}" + (f", compared with {prev}" if prev else ""))
    keep = getattr(args, "keep_dumps", False)
    now = by_code(dump_counts(ws, last, dumps[last], keep))
    before = by_code(dump_counts(ws, prev, dumps[prev], keep)) if prev else None
    rows = []
    for code, d in sorted(now.items(), key=lambda kv: -kv[1]["total"]):
        p = (before or {}).get(code, {}).get("total")
        rows.append({**d, "date": last.isoformat(), "total_prev": p if p is not None else "",
                     "yoy": round(d["total"] / p - 1, 3) if p else ""})
    with open(ws.out("ru_msp_okved.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "date", "total", "total_prev", "yoy", "ul", "ip",
                                          "micro", "small", "medium", "new"])
        w.writeheader()
        w.writerows(rows)
    print(f"-> ru_msp_okved.csv: {len(rows):,} codes, {sum(d['total'] for d in now.values()):,} businesses")
    nrows = niche_rows(ws.load_config("who_counts.yaml", {}), now, before)
    if not nrows:
        print("config/who_counts.yaml has no okved codes - niche table not written")
        return
    with open(ws.out("ru_msp_niches.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(nrows[0].keys()))
        w.writeheader()
        w.writerows(nrows)
    for r in sorted(nrows, key=lambda r: -r["msp"]):
        yoy = f"{r['msp_yoy']:+.1%}" if r["msp_yoy"] != "" else "-"
        print(f"  {r['niche_id']:36} {r['okved']:22} {r['msp']:>9,}  yoy {yoy:>7}  IP {r['ip_share']}")
    print("-> ru_msp_niches.csv", len(nrows))
