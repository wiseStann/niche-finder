"""S1: how much of the universe do the niches cover, and what is left uncovered.

Matches phrases from config/coverage_keywords.yaml plus the competitor names in niches.yaml (case-insensitive,
at word boundaries) against "entity + one_liner + category" of every row in data/out/universe.csv.
Outputs data/out/coverage.csv (universe rows with the matched niche ids in niche_id, joined by |) and
reports/S1-coverage.md: coverage by source, the most frequent words among uncovered entities, uncovered top-grossing
apps per genre, uncovered YC / Product Hunt / Empire Flippers / TinySeed / BetaList / Product Radar / Kickstarter entities
(Kickstarter grouped by category, largest pledges first), and uncovered category taxonomy entries or
regional-ranking companies when those optional sources were imported. These lists point at niches you may have missed.

Optional: config/coverage_notes.md (your own conclusions) is inserted verbatim after the coverage table.
Matching is coarse: false hits are possible in both directions, but the order of magnitude holds. No keys, no network.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict

from nichefinder import niches as nf_niches
from nichefinder.workspace import Workspace

SUMMARY = "Universe coverage by niches and uncovered clusters"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

STOP = set("""the a an and or for of to in on with your you our by from at is are it its this that app apps ai
software platform tool tools online free best new all any get make your more one first every business businesses
service services solution solutions management system systems data help helps using use easy simple smart pro plus
и в на с для по из от до как что это или не при без про ваш ваша ваши все всё для лучший приложение приложения сервис
программа онлайн бесплатно новый новая удобный простой умный про плюс""".split())

# competitor names too generic to use as coverage terms
GENERIC_COMPETITORS = {"apple notes", "notion", "google translate", "copilot", "vagaro", "buffer", "later", "loom", "maze", "trim",
                       "payout", "greg", "bend", "torque", "parcel", "waitlist", "gather", "spiro", "whale", "tango", "scribe",
                       "pitch", "tome"}


def term_re(t):
    raw = str(t).lower()
    t = re.escape(raw).replace(r"\ ", r"\s+")
    # word boundary on the left always; on the right only for short terms (crm, asl, obd...), otherwise plurals are lost
    right = r"(?![a-zа-яё0-9])" if len(raw) <= 4 else ""
    return re.compile(r"(?<![a-zа-яё0-9])" + t + right, re.I)


def run(ws: Workspace, args: argparse.Namespace) -> None:
    niches = nf_niches.load_niches(ws)
    kw = ws.load_config("coverage_keywords.yaml", default={})
    pats = {}
    for x in niches:
        terms = list(kw.get(x["id"], []))
        for c in x.get("competitors") or []:
            c = re.sub(r"\s*\(.*?\)", "", str(c)).strip()
            if len(c) >= 4 and c.lower() not in GENERIC_COMPETITORS:
                terms.append(c)
        pats[x["id"]] = [term_re(t) for t in terms if t]
    upath = ws.out("universe.csv")
    if not upath.is_file():
        raise SystemExit(f"{upath} not found: run `nf run s0` first")
    rows = list(csv.DictReader(open(upath, encoding="utf-8")))
    if not rows:
        raise SystemExit(f"{upath} is empty")
    out, by_src, unmatched = [], defaultdict(lambda: [0, 0]), []
    for r in rows:
        text = f"{r['entity']} {r['one_liner']} {r['category']}"
        hits = [nid for nid, ps in pats.items() if any(p.search(text) for p in ps)]
        src = r["source"].split(":")[0] + (":" + r["source"].split(":")[1] if r["source"].startswith("appstore") else "")
        by_src[src][1] += 1
        if hits:
            by_src[src][0] += 1
        else:
            unmatched.append(r)
        out.append({**r, "niche_id": "|".join(hits)})
    cpath = ws.out("coverage.csv")
    with open(cpath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    covered = len(rows) - len(unmatched)
    L = [f"# S1 coverage: how much of the universe the niches cover ({ws.today.isoformat()})", "",
         f"Entities: {len(rows)}; covered by at least one of {len(pats)} niches: **{covered} ({covered / len(rows):.0%})**; uncovered: {len(unmatched)}. "
         "Matching uses the phrases in `config/coverage_keywords.yaml` plus competitor names: it is coarse, false hits are "
         "possible in both directions, but the order of magnitude holds.", "",
         "## Coverage by source", "", "| Source | Total | Covered | Share |", "|---|---|---|---|"]
    for src, (c, t) in sorted(by_src.items(), key=lambda x: -x[1][1]):
        L.append(f"| {src} | {t} | {c} | {c / t:.0%} |")
    notes = ws.config("coverage_notes.md")   # your own conclusions; kept in a separate file so regeneration does not lose them
    if notes.is_file():
        L += ["", notes.read_text(encoding="utf-8").rstrip(), ""]
    # frequent words among uncovered entities (category taxonomy and regional-ranking rows have no descriptions)
    words: Counter = Counter()
    for r in unmatched:
        if r["source"].startswith(("g2", "smartranking")):
            continue
        for wd in re.findall(r"[a-zа-яё]{4,}", f"{r['entity']} {r['one_liner']}".lower()):
            if wd not in STOP:
                words[wd] += 1
    L += ["", "## Most frequent words in descriptions of uncovered entities (every source with descriptions)", "",
          ", ".join(f"{w} ({c})" for w, c in words.most_common(120)), ""]
    # uncovered top-grossing apps by genre
    L += ["## Uncovered top-grossing App Store apps (people pay, but no niche)", ""]
    g = defaultdict(list)
    for r in unmatched:
        if r["source"].startswith("appstore"):
            g[r["source"]].append(r)
    for src in sorted(g):
        items = g[src]
        L.append(f"**{src}** ({len(items)}): " + "; ".join(f"{r['entity'][:40]}" for r in items[:40]) + ("…" if len(items) > 40 else ""))
        L.append("")
    # uncovered YC / PH / Empire Flippers / TinySeed, and the optional launch / crowdfunding sources
    for src_prefix, title in (("yc", "YC"), ("ph", "Product Hunt"), ("ef", "Empire Flippers (software and digital businesses with a verified P&L)"), ("tinyseed", "TinySeed"),
                              ("betalist", "BetaList (pre-launch)"), ("productradar", "Product Radar (Russian-language launches)"),
                              ("kickstarter", "Kickstarter (successful, >= 200 backers; paid in advance)")):
        items = [r for r in unmatched if r["source"].split(":")[0] == src_prefix]
        if src_prefix == "kickstarter":
            items.sort(key=lambda r: (r["category"], -int(re.sub(r"\D", "", r["signal"].split(";")[0]) or 0)))
        if not items and src_prefix in ("betalist", "productradar", "kickstarter"):   # optional sources: no empty sections
            continue
        L.append(f"## Uncovered: {title} ({len(items)})")
        L.append("")
        for r in items[:400]:
            sig = r["signal"][:40]
            L.append(f"- {r['entity'][:50]} — {r['one_liner'][:110]}" + (f" _[{sig}]_" if sig else ""))
        L.append("")
    # uncovered category taxonomy entries and regional-ranking companies (only when imported)
    for src_prefix, title in (("g2", "Category taxonomy entries without a niche"), ("smartranking", "Regional-ranking companies without a niche")):
        items = [r for r in unmatched if r["source"].startswith(src_prefix)]
        if not items:
            continue
        L.append(f"## {title} ({len(items)})")
        L.append("")
        L.append("; ".join(f"{r['entity'][:45]}" + (f" ({r['category'][:30]})" if r["category"] and src_prefix == "g2" else "") for r in items))
        L.append("")
    rpath = ws.report("S1-coverage.md")
    rpath.write_text("\n".join(L), encoding="utf-8")
    print(f"covered {covered}/{len(rows)} = {covered / len(rows):.0%}")
    for src, (c, t) in sorted(by_src.items(), key=lambda x: -x[1][1]):
        print(f"  {src:24} {c:5}/{t:5} {c / t:.0%}")
    print(f"-> {cpath}, {rpath}")
