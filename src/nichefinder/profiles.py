"""Run profiles: filtered runs that keep their outputs apart from the full run.

A profile is profiles/<name>/profile.yaml in the workspace:

    markets: [us, ww]          # demand pools; replaces the markets of nf.yaml
    side: [b2b-smb, b2b-mid]   # niche sides in scope
    tier: [A, B, C]            # keep C: control niches calibrate the score
    geo: [global, both]

A missing key means everything (for markets: those of nf.yaml), so the empty spec is the full run and needs no
profile. `niches.in_scope` applies the filter; `Workspace` sends the profile's outputs and reports to profiles/<name>/.
The name is derived from the spec (`west-b2b`, `ru-b2c`), so the same parameters always reuse the same outputs.

A new profile starts from a copy of the full run's data/out/ and data/snapshots/ with the rows of niches outside its
scope dropped. The copy keeps the state of incremental stages (s3_dataforseo requests only keywords its CSV lacks, and a
batch of a different composition would miss the cache and be paid again) and of cumulative histories (s8_freelance),
and it lets a profile rescore (s6, s7) at once without measuring again. Rows are dropped so that report stages, which take
niche ids from these files, never meet a niche the profile does not load.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from nichefinder import niches
from nichefinder.workspace import PROFILE_FILE, PROFILE_NAME, PROFILES, Workspace, WorkspaceError

KEYS = ("markets", "side", "tier", "geo")
MARKETS = ("us", "ww", "ru")
# CSVs whose niche column is not called niche_id
NICHE_COLUMN = {"metrics_quick.csv": "id"}


def universe(ws: Workspace) -> dict[str, list[str]]:
    """Every value a spec can pick: the three demand pools and the sides, tiers and geos present in niches.yaml."""
    all_niches = niches.load_niches(ws, scoped=False)

    def present(key: str, default: str) -> list[str]:
        return sorted({str(n.get(key) or default) for n in all_niches})

    return {"markets": list(MARKETS), "side": present("side", ""), "tier": present("tier", ""),
            "geo": present("geo", "global")}


def normalize(ws: Workspace, spec: dict[str, Any] | None) -> dict[str, list[str]]:
    """Known keys only, values in a stable order; a key that picks everything is dropped, so the full run is {}.
    Raises ValueError when a key picks nothing."""
    spec = spec or {}
    uni = universe(ws)
    base_markets = {str(m) for m in ws.settings.get("markets", ["us"])}
    out: dict[str, list[str]] = {}
    for key in KEYS:
        if key not in spec or spec[key] is None:
            continue
        picked = {str(v) for v in spec[key]}
        unknown = picked - set(uni[key])
        if unknown:
            raise ValueError(f"unknown {key}: {', '.join(sorted(unknown))} (choose from {', '.join(uni[key])})")
        if not picked:
            raise ValueError(f"pick at least one {key}")
        full = base_markets if key == "markets" else set(uni[key])
        if picked != full:
            out[key] = [v for v in uni[key] if v in picked]
    return out


def auto_name(ws: Workspace, spec: dict[str, list[str]]) -> str:
    """A readable name for a normalized spec: west-b2b, ru-b2c, us-tier-ab. Empty for the full run."""
    sides = universe(ws)["side"]
    b2c = [s for s in sides if s in niches.B2C_SIDES]
    b2b = [s for s in sides if s not in niches.B2C_SIDES]
    parts = []
    m = spec.get("markets")
    if m:
        parts.append({("us", "ww"): "west"}.get(tuple(m), "-".join(m)))
    s = spec.get("side")
    if s:
        parts.append("b2b" if s == b2b else "b2c" if s == b2c else "-".join(s))
    if spec.get("tier"):
        parts.append("tier-" + "".join(spec["tier"]).lower())
    if spec.get("geo"):
        parts.append("geo-" + "-".join(spec["geo"]))
    name = "-".join(parts).lower()
    if len(name) > 48:
        name = name[:39].rstrip("-") + "-" + hashlib.sha1(name.encode()).hexdigest()[:8]
    return name


def list_profiles(ws: Workspace) -> list[dict[str, Any]]:
    """[{name, spec, path}] for every profiles/<name>/profile.yaml."""
    base = ws.root / PROFILES
    out = []
    for d in sorted(base.iterdir()) if base.is_dir() else []:
        f = d / PROFILE_FILE
        if f.is_file() and PROFILE_NAME.match(d.name):
            out.append({"name": d.name, "spec": yaml.safe_load(f.read_text(encoding="utf-8")) or {}, "path": d})
    return out


def create(ws: Workspace, spec: dict[str, Any] | None, name: str | None = None) -> Workspace:
    """The workspace for these parameters: the main one for the full run, else profiles/<name>/ (written and seeded on
    first use). An existing profile gets the new spec; its outputs stay until stages run again."""
    root = Workspace(ws.root)
    spec = normalize(root, spec)
    if not spec:
        if name:
            raise WorkspaceError("these parameters select the full run: no profile needed")
        return root
    name = name or auto_name(root, spec)
    if not PROFILE_NAME.match(name):
        raise WorkspaceError(f"bad profile name {name!r}: lower-case letters, digits and dashes")
    d = ws.root / PROFILES / name
    fresh = not (d / "data" / "out").exists()
    d.mkdir(parents=True, exist_ok=True)
    header = ("# Run profile written by nf (nf ui / nf profile). Outputs of this profile live in this folder; nf.yaml, config/,\n"
              "# .env, data/raw/ and data/cache/ are shared with the workspace. A missing key means all values.\n")
    (d / PROFILE_FILE).write_text(header + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
    prof = Workspace(ws.root, profile=name)
    if fresh:
        seed(root, prof)
    return prof


def seed(main: Workspace, prof: Workspace) -> None:
    """Copy the full run's data/out/ and data/snapshots/ into a profile, keeping only the rows of its niches."""
    scope = {n["id"] for n in niches.load_niches(prof) if "id" in n}
    every = {n["id"] for n in niches.load_niches(main, scoped=False) if "id" in n}
    for sub in (("data", "out"), ("data", "snapshots")):
        src, dst = main.root.joinpath(*sub), prof.profile_root.joinpath(*sub)
        if not src.is_dir():
            continue
        for f in src.rglob("*"):
            if f.is_file():
                target = dst / f.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                copy_scoped(f, target, scope, every)


def copy_scoped(src: Path, dst: Path, scope: set[str], every: set[str]) -> None:
    """Copy one output file; drop the rows (CSV, JSON lines, JSON lists and niche-keyed JSON maps) of niches out of scope.
    Rows without a niche (unmatched entities in coverage.csv) and files without a niche column are copied as they are."""
    if src.suffix == ".csv":
        _copy_csv(src, dst, scope)
    elif src.suffix == ".jsonl":
        with open(src, encoding="utf-8") as fi, open(dst, "w", encoding="utf-8", newline="") as fo:
            for line in fi:
                try:
                    nid = json.loads(line).get("niche_id") if line.strip() else None
                except (ValueError, AttributeError):
                    nid = None
                if not nid or nid in scope:
                    fo.write(line)
    elif src.suffix == ".json":
        _copy_json(src, dst, scope, every)
    else:
        shutil.copy2(src, dst)


def _copy_csv(src: Path, dst: Path, scope: set[str]) -> None:
    with open(src, "rb") as f:
        bom = f.read(3) == b"\xef\xbb\xbf"
    col = NICHE_COLUMN.get(src.name, "niche_id")
    with open(src, newline="", encoding="utf-8-sig", errors="replace") as fi:
        reader = csv.reader(fi)
        head = next(reader, None)
        if not head or col not in head:
            fi.close()
            shutil.copy2(src, dst)
            return
        i = head.index(col)
        with open(dst, "w", newline="", encoding="utf-8-sig" if bom else "utf-8") as fo:
            w = csv.writer(fo)
            w.writerow(head)
            w.writerows(r for r in reader if len(r) <= i or not r[i] or r[i] in scope)


def _copy_json(src: Path, dst: Path, scope: set[str], every: set[str]) -> None:
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError:
        shutil.copy2(src, dst)
        return
    if isinstance(data, dict) and data and set(data) <= every:
        data = {k: v for k, v in data.items() if k in scope}
    elif isinstance(data, list) and data and all(isinstance(x, dict) and "niche_id" in x for x in data):
        data = [x for x in data if x["niche_id"] in scope]
    else:
        shutil.copy2(src, dst)
        return
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
