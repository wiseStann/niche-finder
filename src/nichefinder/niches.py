"""Niches and their search queries: loading and validation.

niches.yaml is a list of niches:

    - id: tattoo-pmu-studios          # unique slug, used everywhere as niche_id
      name: Tattoo and PMU studios — booking, consent forms, deposits
      who: tattoo studios and permanent make-up artists, 1–10 people
      task: online booking, digital consent forms, deposits, reminders
      product: web + mobile SaaS, $20–60/month per studio
      geo: global                     # global | ru | both — which query languages are required
      side: b2b-smb                   # b2b-smb | b2b | b2c | prosumer
      tier: A                         # A — measure; B — candidate; C — control niche
      competitors: [Inkzup, Tattoo Pro]

queries/*.yaml map niche id → language → list of queries:

    tattoo-pmu-studios:
      en:
        - {q: "tattoo studio software", i: category, anchor: true}   # exactly one anchor per language
        - {q: "inkzup", i: brand, b: Inkzup}                          # brand queries name the brand
"""
from __future__ import annotations

import glob
from collections import Counter, defaultdict

import yaml

from nichefinder.workspace import Workspace

INTENTS = {"category", "problem", "brand", "info"}
MIN_PER_INTENT = {"category": 3, "problem": 1, "brand": 2}
GEO_LANGS = {"global": ["en"], "ru": ["ru"], "both": ["en", "ru"]}


def load_niches(ws: Workspace) -> list[dict]:
    return yaml.safe_load(ws.niches_file.read_text(encoding="utf-8")) or []


def load_queries(ws: Workspace) -> dict[str, dict]:
    queries: dict[str, dict] = {}
    for path in sorted(glob.glob(str(ws.queries_dir / "*.yaml"))):
        part = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for nid, langs in part.items():
            if nid in queries:
                raise SystemExit(f"duplicate niche {nid} in {path}")
            queries[nid] = langs
    return queries


def load(ws: Workspace) -> tuple[list[dict], dict[str, dict]]:
    return load_niches(ws), load_queries(ws)


def niche_names(ws: Workspace) -> dict[str, str]:
    return {n["id"]: n.get("name", n["id"]) for n in load_niches(ws)}


def langs_required(niche: dict) -> list[str]:
    return GEO_LANGS[niche.get("geo", "global")]


def validate(ws: Workspace) -> tuple[list[str], list[str], Counter]:
    """Check niches.yaml and queries/*.yaml. Returns (errors, warnings, stats)."""
    niches, queries = load(ws)
    errors: list[str] = []
    warns: list[str] = []
    by_id: dict[str, dict] = {}
    for n in niches:
        if "id" not in n:
            errors.append(f"niche without id: {n}")
            continue
        if n["id"] in by_id:
            errors.append(f"{n['id']}: duplicate niche id")
        by_id[n["id"]] = n
        if n.get("geo", "global") not in GEO_LANGS:
            errors.append(f"{n['id']}: geo must be one of {sorted(GEO_LANGS)}")
    for nid in queries:
        if nid not in by_id:
            errors.append(f"{nid}: has queries but no niche in niches.yaml")
    seen: dict[tuple[str, str], list[str]] = defaultdict(list)
    stats: Counter = Counter()
    for nid, n in by_id.items():
        q = queries.get(nid)
        if not q:
            errors.append(f"{nid}: no queries")
            continue
        for lang in langs_required(n):
            items = q.get(lang) or []
            if not items:
                errors.append(f"{nid}/{lang}: no queries for geo={n.get('geo', 'global')}")
                continue
            cnt: Counter = Counter()
            anchors = 0
            for it in items:
                if "q" not in it or "i" not in it:
                    errors.append(f"{nid}/{lang}: entry without q/i: {it}")
                    continue
                if it["i"] not in INTENTS:
                    errors.append(f"{nid}/{lang}: unknown intent {it['i']} for '{it['q']}'")
                if it["i"] == "brand" and not it.get("b"):
                    errors.append(f"{nid}/{lang}: brand query without b: '{it['q']}'")
                cnt[it["i"]] += 1
                anchors += bool(it.get("anchor"))
                seen[(lang, it["q"].strip().lower())].append(nid)
                stats[lang] += 1
                stats[f"{lang}/{it['i']}"] += 1
            if anchors != 1:
                errors.append(f"{nid}/{lang}: {anchors} anchors, exactly 1 required")
            for k, m in MIN_PER_INTENT.items():
                if cnt[k] < m and n.get("tier") != "C":
                    warns.append(f"{nid}/{lang}: {k}={cnt[k]} (< {m})")
        for lang in set(q) - set(langs_required(n)):
            warns.append(f"{nid}: has {lang} queries but geo={n.get('geo', 'global')} — measured, not required")
    for (lang, text), nids in seen.items():
        if len(nids) > 1:
            warns.append(f"duplicate query '{text}' ({lang}) in {nids}")
    stats["niches"] = len(niches)
    stats["with_queries"] = len(queries)
    return errors, warns, stats


def shortlist(ws: Workspace) -> dict[str, list[dict]]:
    """config/shortlist.yaml: tiers (any key except `ru`) → [{id, why}]. Written by s3_report, editable by hand."""
    path = ws.config("shortlist.yaml")
    if not path.is_file():
        raise SystemExit(f"{path} not found — run `nf run s3_report` first (it writes the shortlist), or create it by hand.")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def shortlist_ids(ws: Workspace) -> list[str]:
    """Niches that go through deep measurement (S4, S5, S8, S9): the union of all shortlist tiers, in file order."""
    ids: list[str] = []
    for tier, items in shortlist(ws).items():
        if tier == "ru" or not isinstance(items, list):
            continue
        for it in items:
            nid = it["id"] if isinstance(it, dict) else it
            if nid not in ids:
                ids.append(nid)
    return ids


def overrides(ws: Workspace, name: str = "overrides.yaml") -> dict[str, dict]:
    """Per-niche human judgments (config/overrides.yaml): platform risk, lock-in, feasibility, manual supply notes,
    founder fit, and optional verdict overrides. Missing file → no overrides."""
    path = ws.config(name)
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def keyword_rows(ws: Workspace, lang: str) -> list[dict]:
    """Flat list of queries for one language: niche_id, lang, q, intent, brand, anchor."""
    niches, queries = load(ws)
    rows = []
    for n in niches:
        for it in (queries.get(n["id"], {}).get(lang) or []):
            rows.append({"niche_id": n["id"], "lang": lang, "q": it["q"], "intent": it["i"],
                         "brand": it.get("b", ""), "anchor": int(bool(it.get("anchor")))})
    return rows
