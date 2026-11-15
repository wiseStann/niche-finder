"""S1: validate niches.yaml and render it as reports/S1-niche-universe.md.

Checks the niche schema (required fields, geo and side values, at least 3 competitors outside tier C, unique ids)
and stops with the list of problems if any. Otherwise writes a Markdown overview: counts by tier, geo, side and
source, and one table per section. Niches are grouped by an optional `section` field (sections keep the order of
first appearance in niches.yaml); without it they are grouped by tier. When data/out/universe.csv exists, the entity
counts per source are included. Edit niches.yaml, not the report. No keys, no network.

Required niche fields: id, name, who, task, product, geo, side, tier. Optional: sources (list), competitors (list),
expertise_flag (0/1), notes, control, section.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter

from nichefinder import niches as nf_niches
from nichefinder.workspace import Workspace

SUMMARY = "Validate niches.yaml and write the niche overview report"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

REQUIRED = ["id", "name", "who", "task", "product", "geo", "side", "tier"]
GEO = {"global", "ru", "both"}
SIDE = {"b2c", "b2b-smb", "b2b-mid", "b2b", "prosumer"}
TIER_TITLES = {"A": "Tier A: measure", "B": "Tier B: candidates", "C": "Tier C: control niches"}


def _universe_line(ws: Workspace) -> str:
    path = ws.out("universe.csv")
    if not path.is_file():
        return ""
    with open(path, encoding="utf-8", newline="") as f:
        counts = Counter(r["source"].split(":")[0] for r in csv.DictReader(f))
    if not counts:
        return ""
    return (f"Universe of entities: `data/out/universe.csv`, {sum(counts.values()):,} rows (" +
            ", ".join(f"{k} {v:,}" for k, v in counts.most_common()) + ").\n")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    niches = nf_niches.load_niches(ws)
    errors = []
    ids = Counter(n.get("id") for n in niches)
    for i, n in enumerate(niches):
        nid = n.get("id", i)
        for k in REQUIRED:
            if k not in n:
                errors.append(f"{nid}: missing field {k}")
        if n.get("geo") not in GEO:
            errors.append(f"{nid}: geo={n.get('geo')}")
        if n.get("side") not in SIDE:
            errors.append(f"{nid}: side={n.get('side')}")
        if len(n.get("competitors") or []) < 3 and n.get("tier") != "C":
            errors.append(f"{nid}: fewer than 3 competitors")
        if ids[n.get("id")] > 1:
            errors.append(f"{nid}: duplicate id")
    if errors:
        print("SCHEMA ERRORS:")
        for e in errors:
            print("  ", e)
        raise SystemExit(1)

    tiers = Counter(n["tier"] for n in niches)
    geos = Counter(n["geo"] for n in niches if n["tier"] != "C")
    sides = Counter(n["side"] for n in niches if n["tier"] != "C")
    src_types: Counter = Counter()
    for n in niches:
        for s in n.get("sources") or []:
            src_types[s] += 1

    L = ["# S1: niche universe\n",
         f"Generated from `niches.yaml` by `nf run s1_niches` (run date {ws.today.isoformat()}). Edit the YAML, not this file.\n",
         f"**{len(niches)} niches:** tier A {tiers['A']} (to measure), tier B {tiers['B']} (candidates), tier C {tiers['C']} (control niches).  ",
         f"Geo (without controls): " + ", ".join(f"{k} {v}" for k, v in geos.most_common()) +
         ". Side: " + ", ".join(f"{k} {v}" for k, v in sides.most_common()) + ".\n"]
    if src_types:
        L.append("Evidence sources (niches relying on each): " + ", ".join(f"{k} {v}" for k, v in src_types.most_common()) + ".\n")
    u = _universe_line(ws)
    if u:
        L.append(u)
    L.append("Legend: **T** tier; **E** expertise_flag (1 = legal or regulated topic that needs domain expertise); "
             "geo `both` = measured in Google (US/WW) and Yandex.\n")

    if any(n.get("section") for n in niches):
        keys = list(dict.fromkeys(n.get("section") or "Other" for n in niches))
        groups = [(k, [n for n in niches if (n.get("section") or "Other") == k]) for k in keys]
    else:
        groups = [(TIER_TITLES.get(t, f"Tier {t}"), [n for n in niches if n["tier"] == t]) for t in sorted(tiers)]

    for title, items in groups:
        L.append(f"\n## {title}\n")
        L.append("| # | id | Niche | Who x task | Geo | Side | T | E | Sources | Competitors (sample) | Notes |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for k, n in enumerate(items, 1):
            who_task = f"{n['who']} × {n['task']}"
            comps = ", ".join(str(c) for c in (n.get("competitors") or [])[:5])
            note = n.get("notes", "") or ""
            if n.get("control"):
                note = f"control={n['control']}. " + note
            L.append(f"| {k} | `{n['id']}` | **{n['name']}** | {who_task} | {n['geo']} | {n['side']} | {n['tier']} | "
                     f"{n.get('expertise_flag', 0)} | {', '.join(n.get('sources') or [])} | {comps} | {note} |")

    out = ws.report("S1-niche-universe.md")
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"OK: {len(niches)} niches -> {out}")
    print("tiers:", dict(tiers), "| geo:", dict(geos), "| side:", dict(sides))
