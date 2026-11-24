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
import re
from collections import Counter, defaultdict
from typing import Callable

import yaml

from nichefinder.workspace import Workspace

INTENTS = {"category", "problem", "brand", "info"}
MIN_PER_INTENT = {"category": 3, "problem": 1, "brand": 2}
GEO_LANGS = {"global": ["en"], "ru": ["ru"], "both": ["en", "ru"]}


B2C_SIDES = ("b2c", "prosumer")   # scored in the B2C cohort (s6_score); every other side is B2B
MARKET_LANG = {"us": "en", "ww": "en", "ru": "ru"}


def in_scope(ws: Workspace, niche: dict) -> bool:
    """Whether a niche belongs to the active run profile (always true without one): its side, tier and geo are among the
    profile's, and the profile's markets measure at least one of the languages its geo requires (a global niche has no
    Russian queries, so a Russian-only run has nothing to measure for it)."""
    spec = ws.profile_spec
    if not spec:
        return True
    for key, default in (("side", ""), ("tier", ""), ("geo", "global")):
        allowed = spec.get(key)
        if allowed and str(niche.get(key) or default) not in {str(a) for a in allowed}:
            return False
    langs = {MARKET_LANG[m] for m in spec.get("markets") or () if m in MARKET_LANG}
    return not langs or bool(langs & set(GEO_LANGS.get(niche.get("geo", "global"), ["en"])))


def load_niches(ws: Workspace, scoped: bool = True) -> list[dict]:
    """niches.yaml; under a run profile only the niches in its scope unless `scoped` is False (validation)."""
    items = yaml.safe_load(ws.niches_file.read_text(encoding="utf-8")) or []
    return [n for n in items if in_scope(ws, n)] if scoped and ws.profile_spec else items


def scope_ids(ws: Workspace) -> set[str] | None:
    """Ids of the niches in the run profile's scope, or None without a profile (everything is in scope)."""
    return {n["id"] for n in load_niches(ws) if "id" in n} if ws.profile_spec else None


def load_queries(ws: Workspace) -> dict[str, dict]:
    queries: dict[str, dict] = {}
    for path in sorted(glob.glob(str(ws.queries_dir / "*.yaml"))):
        part = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for nid, langs in part.items():
            if nid in queries:
                raise SystemExit(f"duplicate niche {nid} in {path}")
            queries[nid] = langs
    return queries


def load(ws: Workspace, scoped: bool = True) -> tuple[list[dict], dict[str, dict]]:
    ns, qs = load_niches(ws, scoped), load_queries(ws)
    if scoped and ws.profile_spec:
        ids = {n.get("id") for n in ns}
        qs = {k: v for k, v in qs.items() if k in ids}
    return ns, qs


def niche_names(ws: Workspace) -> dict[str, str]:
    return {n["id"]: n.get("name", n["id"]) for n in load_niches(ws)}


def langs_required(niche: dict) -> list[str]:
    return GEO_LANGS[niche.get("geo", "global")]


def validate(ws: Workspace) -> tuple[list[str], list[str], Counter]:
    """Check niches.yaml and queries/*.yaml (all of them, whatever the run profile). Returns (errors, warnings, stats)."""
    niches, queries = load(ws, scoped=False)
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
    # (lang, words in sorted order) -> [(niche id, intent, query)]. Word order is ignored because Wordstat broad match and
    # Keyword Planner close variants give "коран приложение" and "приложение коран" the same volume. A brand query shared
    # by two niches is fine: brand volume feeds only the concentration metrics, so a competitor present in two overlapping
    # niches belongs to both. A shared category or problem query is not: its volume is summed into the demand of every
    # niche that lists it.
    seen: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
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
                text = it["q"].strip().lower()
                seen[(lang, " ".join(sorted(text.split())))].append((nid, it["i"], text))
                stats[lang] += 1
                stats[f"{lang}/{it['i']}"] += 1
            if anchors != 1:
                errors.append(f"{nid}/{lang}: {anchors} anchors, exactly 1 required")
            for k, m in MIN_PER_INTENT.items():
                if cnt[k] < m and n.get("tier") != "C":
                    warns.append(f"{nid}/{lang}: {k}={cnt[k]} (< {m})")
        for lang in set(q) - set(langs_required(n)):
            warns.append(f"{nid}: has {lang} queries but geo={n.get('geo', 'global')} — measured, not required")
    for (lang, _), uses in seen.items():
        if len(uses) > 1 and any(i != "brand" for _, i, _ in uses):
            texts = " / ".join(dict.fromkeys(t for _, _, t in uses))
            warns.append(f"duplicate query '{texts}' ({lang}) in {[nid for nid, _, _ in uses]}: its demand counts in each; "
                         "keep it in the most specific niche")
    stats["niches"] = len(niches)
    stats["with_queries"] = len(queries)
    return errors, warns, stats


def shortlist(ws: Workspace) -> dict[str, list[dict]]:
    """config/shortlist.yaml: tiers (any key except `ru`) → [{id, why}]. Written by s3_report, editable by hand."""
    path = ws.config("shortlist.yaml")
    if not path.is_file():
        raise SystemExit(f"{path} not found — run `nf run s3_report` first (it writes the shortlist), or create it by hand.")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def shortlist_ids(ws: Workspace, ru: bool = False) -> list[str]:
    """Niches that go through deep measurement (S4, S5, S8, S9): the union of all shortlist tiers, in file order,
    limited to the run profile's scope. ru=True adds the tier `ru`: niches with geo both/ru that the Russian deep
    stages measure (the Russian App Store and Google Play, Russian reviews, Telegram, YouTube comments, VK, Yandex
    Direct) although the US-pool shortlist left them out. The US stages and s5_merge never see that tier."""
    scope = scope_ids(ws)
    ids: list[str] = []
    for tier, items in shortlist(ws).items():
        if (tier == "ru" and not ru) or not isinstance(items, list):
            continue
        for it in items:
            nid = it["id"] if isinstance(it, dict) else it
            if nid not in ids and (scope is None or nid in scope):
                ids.append(nid)
    return ids


def ru_only_ids(ws: Workspace) -> set[str]:
    """Niches of the shortlist tier `ru` that no other tier holds: stages that measure both markets skip their US side."""
    return set(shortlist_ids(ws, ru=True)) - set(shortlist_ids(ws))


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


def phrase_regex(terms) -> str:
    """Coverage phrases as one regex source: any of the phrases (lower case), with a word boundary on the left."""
    return r"(?<![a-zа-яё0-9])(" + "|".join(re.escape(str(t).lower()) for t in terms) + ")"


def text_matchers(ws: Workspace, ids: list[str] | None = None, *, with_coverage: bool = False) -> dict[str, Callable[[str], bool]]:
    """Predicates that tie free text (launch taglines, project blurbs, job postings, HN titles) to niches.

    config/deal_keywords.yaml gives a case-insensitive regex per niche, or {re, not} where `not` drops a neighbouring
    category. Niches in `ids` (default: the shortlist) without an entry fall back to their phrases in
    config/coverage_keywords.yaml. with_coverage=True also accepts the coverage phrases of every niche that has them:
    the deal regexes are English, so Russian-language text needs the phrases."""
    kw = dict(ws.load_config("deal_keywords.yaml", {}) or {})
    scope = scope_ids(ws)
    if scope is not None:
        kw = {k: v for k, v in kw.items() if k in scope}
    cov = ws.load_config("coverage_keywords.yaml", {}) or {}
    fallback = set()
    for nid in (shortlist_ids(ws) if ids is None else ids):
        if nid not in kw and cov.get(nid):
            kw[nid] = phrase_regex(cov[nid])
            fallback.add(nid)
    out: dict[str, Callable[[str], bool]] = {}
    for nid, p in kw.items():
        pos, neg = (p["re"], p.get("not")) if isinstance(p, dict) else (p, None)
        if with_coverage and cov.get(nid) and nid not in fallback:
            pos = f"(?:{pos})|{phrase_regex(cov[nid])}"
        out[nid] = _matcher(re.compile(pos, re.I), re.compile(neg, re.I) if neg else None)
    return out


def _matcher(pos: re.Pattern, neg: re.Pattern | None) -> Callable[[str], bool]:
    return lambda text: bool(pos.search(text)) and not (neg is not None and neg.search(text))
