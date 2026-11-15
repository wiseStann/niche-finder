"""Quick-filter report: leaderboards per demand pool, control niches, shortlist -> reports/S3-quick-filter.md.

Input: data/out/metrics_quick.csv (s3_metrics), config/score.yaml, config/shortlist.yaml.
When config/shortlist.yaml does not exist (or with --rewrite-shortlist) the shortlist is written automatically:
  tier_a = niches that pass gates G0-G2 in the US pool (control niches excluded), best score first;
  tier_b = niches cut only by the top-1 brand gate (G2:top1) with US demand >= shortlist.tier_b_min_demand
           and a top-1 brand share <= shortlist.tier_b_max_top1 (both in config/score.yaml), highest demand first.
Each item is {id, why} with a generated reason. An existing shortlist is never overwritten without the flag;
edit it by hand to add or drop niches, and every later stage reads it (S4, S5, S8, S9 work on the union of its tiers).
"""
from __future__ import annotations

import argparse
import csv
import json

import yaml

from nichefinder.workspace import Workspace

SUMMARY = "Quick-filter report (reports/S3-quick-filter.md) and the automatic shortlist"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

SHORTLIST_HEADER = """\
# Shortlist: niches that go on to deep measurement (S4 trends, S5 supply, S8 off-search demand, S9 supply over time).
# Written by `nf run s3_report` when this file is missing (`--rewrite-shortlist` regenerates it). Edit by hand freely:
# every tier is read (the key `ru` is ignored), `why` is free text.
#
# tier_a: niches that pass gates G0-G2 in the US pool.
# tier_b: niches cut only by the top-1 brand gate, with demand >= {min_demand}/month and top-1 <= {max_top1:.0%}.
#   That gate is sensitive to the 3-5 brands listed per niche, so concentration is re-checked against an independent
#   signal (rating share in the app stores, reviews on directories). A "leader + long tail" market moves to tier_a.
# ru: reserved for the Russian module.
"""


def num(v, fmt="{:.0f}", dash="-"):
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return dash


def pct(v):
    return num(v, "{:+.0%}")


def table(pref, members, title):
    L = [f"\n### {title}\n",
         "| # | Niche | T | Demand/mo (last 12) | Demand 2023 | CPC $ | 2024/23 | last 12 / prev 12 | Trend | Top-1 brand | Brand share | Score | Gates |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in enumerate(members, 1):
        top1 = f"{num(r.get(f'{pref}_top1_brand_share'), '{:.0%}')} {r.get(f'{pref}_top1_brand', '')}".strip()
        mark = "**" if r.get(f"{pref}_pass") == "1" else ""
        L.append(f"| {k} | {mark}{r['id']}{mark} | {r['tier']} | {num(r.get(f'{pref}_demand_cat'))} | {num(r.get(f'{pref}_demand_2023'))} | {num(r.get(f'{pref}_cpc_med'), '{:.1f}')} | {pct(r.get(f'{pref}_yoy_pre'))} | {pct(r.get(f'{pref}_yoy'))} | {r.get(f'{pref}_trend', '')} | {top1} | {num(r.get(f'{pref}_brand_share'), '{:.0%}')} | {r.get(f'{pref}_quick_score', '')} | {r.get(f'{pref}_gates', '')} |")
    return L


def control_verdict(expected: str, passed: bool) -> str:
    if expected == "green":
        return "as expected: passed" if passed else "expected green, but cut by the gates"
    if passed:
        return f"false positive (expected {expected}): passed the gates, to be caught by supply / platform checks"
    return f"as expected (expected {expected}): cut"


def _brand(r, pref):
    share = num(r.get(f"{pref}_top1_brand_share"), "{:.0%}")
    return f"top-1 {r.get(f'{pref}_top1_brand', '')} {share}".strip()


def _flags(r, pref):
    return [g for g in (r.get(f"{pref}_gates") or "").split(";") if g.startswith("Q:")]


def auto_shortlist(rows, cfg, pref):
    """Build {tier_a: [...], tier_b: [...]} from the metrics rows of one pool."""
    sl = cfg.get("shortlist") or {}
    min_demand = float(sl.get("tier_b_min_demand", 3000))
    max_top1 = float(sl.get("tier_b_max_top1", 0.8))
    members = [r for r in rows if r.get(f"{pref}_quick_score") and not r["control"]]
    a = sorted([r for r in members if r.get(f"{pref}_pass") == "1"], key=lambda r: -float(r[f"{pref}_quick_score"]))
    tier_a = []
    for r in a:
        why = f"score {r[f'{pref}_quick_score']}; {num(r.get(f'{pref}_demand_cat'))}/month, trend {r.get(f'{pref}_trend', '')}, {_brand(r, pref)}"
        if _flags(r, pref):
            why += "; check outside Google: " + ", ".join(_flags(r, pref))
        if r.get("expertise_flag") not in ("", "0", None):
            why += "; needs domain expertise"
        tier_a.append({"id": r["id"], "why": why})

    def only_top1(r):
        hard = [g for g in (r.get(f"{pref}_gates") or "").split(";") if g and g[0] == "G" and not g.startswith("G4")]
        return hard == ["G2:top1"]

    b = [r for r in members if only_top1(r)
         and float(r.get(f"{pref}_demand_cat") or 0) >= min_demand
         and float(r.get(f"{pref}_top1_brand_share") or 0) <= max_top1]
    b.sort(key=lambda r: -float(r[f"{pref}_demand_cat"]))
    tier_b = [{"id": r["id"], "why": f"{num(r.get(f'{pref}_demand_cat'))}/month, trend {r.get(f'{pref}_trend', '')}, {_brand(r, pref)} "
                                      f"(cut by the top-1 brand gate), score {r[f'{pref}_quick_score']}; re-check concentration outside search"}
              for r in b]
    return {"tier_a": tier_a, "tier_b": tier_b}


def write_shortlist(path, sl, cfg):
    s = cfg.get("shortlist") or {}
    out = [SHORTLIST_HEADER.format(min_demand=f"{float(s.get('tier_b_min_demand', 3000)):,.0f}", max_top1=float(s.get("tier_b_max_top1", 0.8)))]
    for tier in ("tier_a", "tier_b"):
        out.append(f"{tier}:")
        for it in sl[tier]:
            out.append(f"  - {{id: {it['id']}, why: {json.dumps(it['why'], ensure_ascii=False)}}}")
        if not sl[tier]:
            out[-1] += " []"
        out.append("")
    out.append("ru: []")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rewrite-shortlist", action="store_true",
                        help="regenerate config/shortlist.yaml from the metrics even when it exists (overwrites manual edits)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    rows = list(csv.DictReader(open(ws.out("metrics_quick.csv"), encoding="utf-8")))
    cfg = ws.load_config("score.yaml")
    markets = ws.markets
    main_pref = "us" if "us" in markets else "ww"

    sl_path = ws.config("shortlist.yaml")
    if not sl_path.exists() or getattr(args, "rewrite_shortlist", False):
        sl_path.parent.mkdir(parents=True, exist_ok=True)
        auto = auto_shortlist(rows, cfg, main_pref)
        write_shortlist(sl_path, auto, cfg)
        print(f"shortlist written: tier_a {len(auto['tier_a'])}, tier_b {len(auto['tier_b'])} -> {sl_path}")
    else:
        print(f"shortlist kept: {sl_path} (use --rewrite-shortlist to regenerate)")

    base = int(cfg.get("base_year", 2023))
    out = [f"# S3: quick filter results ({ws.today})\n",
           "Source: `data/out/metrics_quick.csv` (written by `s3_metrics`, rendered by `s3_report`). "
           "Data: DataForSEO Google Ads search volume with up to 48 months of history, for the pools "
           f"{', '.join(markets)}; Yandex Wordstat figures appear when `wordstat_ru.csv` exists.\n",
           "Niches that pass gates G0-G2 are in bold (G4 is an expertise flag, not a veto; Q:* are data-quality flags, I:* are informational).\n",
           "**Score** is the quick score (demand 30 + growth 20 + fragmentation 25, normalized to 100). It ranks only the niches "
           "that pass the gates; for the others it is for reference.\n"]

    # control niches
    controls = [r for r in rows if r["control"]]
    if controls and main_pref + "_trend" in rows[0]:
        out.append(f"\n## Calibration on control niches ({main_pref.upper()})\n")
        out.append("| Niche | Expected | Trend | Top-1 | Passed? | Gates | Verdict |")
        out.append("|---|---|---|---|---|---|---|")
        for r in controls:
            passed = r.get(f"{main_pref}_pass") == "1"
            out.append(f"| {r['id']} | {r['control']} | {r.get(f'{main_pref}_trend', '')} | {num(r.get(f'{main_pref}_top1_brand_share'), '{:.0%}')} {r.get(f'{main_pref}_top1_brand', '')} | {'yes' if passed else 'no'} | {r.get(f'{main_pref}_gates', '')} | {control_verdict(r['control'], passed)} |")

    # leaderboards
    def board(pref, title, limit=None):
        members = sorted([r for r in rows if r.get(f"{pref}_quick_score") and not r["control"]], key=lambda r: -float(r[f"{pref}_quick_score"]))
        if members:
            out.extend(table(pref, members[:limit] if limit else members, title.format(n=len(members))))

    if "us" in markets:
        board("us", "Global leaderboard (Google US, {n} niches)")
    if "ww" in markets:
        board("ww", "Worldwide (all languages), top 40 for comparison", 40)
    if "ru" in markets:
        board("gru", "Russian-language queries in Google (worldwide), preliminary, before Wordstat")
        if any(r.get("ya_demand_anchor") for r in rows):
            out.append("\n### Yandex Wordstat (anchor, broad match)\n")
            out.append("| Niche | Anchor, impressions/mo | Max category | Top-1 brand | Brand share |")
            out.append("|---|---|---|---|---|")
            for r in sorted([r for r in rows if r.get("ya_demand_anchor")], key=lambda r: -float(r["ya_demand_anchor"])):
                out.append(f"| {r['id']} | {num(r['ya_demand_anchor'])} | {num(r.get('ya_demand_cat_max'))} | {num(r.get('ya_top1_brand_share'), '{:.0%}')} {r.get('ya_top1_brand', '')} | {num(r.get('ya_brand_share'), '{:.0%}')} |")

    # shortlist
    sl = yaml.safe_load(sl_path.read_text(encoding="utf-8")) or {}
    byid = {r["id"]: r for r in rows}
    out.append("\n## Shortlist for S4/S5 (config/shortlist.yaml)\n")
    for sec, items in sl.items():
        items = items or []
        out.append(f"\n### {sec.replace('_', ' ').capitalize()}: {len(items)}\n")
        out.append("| # | Niche | Score | Why |")
        out.append("|---|---|---|---|")
        for k, it in enumerate(items, 1):
            r = byid.get(it["id"], {})
            out.append(f"| {k} | `{it['id']}` | {r.get(f'{main_pref}_quick_score', '')} | {it['why']} |")

    # data quality
    out.append(f"""
## Data quality: Keyword Planner history after {base} can be contaminated

Two artifacts appear in Google Ads history: a one-year hump of "X software" queries in {base + 1} (x3-x8, then a return
to the old level) and a step-up of broad / "X app" queries afterwards (x2-x5). Bot and AI-agent traffic ends up in the
statistics, as it does in Google Trends. What the pipeline does about it:

1. A trend verdict needs two periods to agree ({base + 1} vs {base}, and the last 12 months vs the previous 12); otherwise it is FLAT.
   Flags `Q:hump2024`, `Q:step2025` and `Q:spike` mark suspect series (the flag names are fixed identifiers; the windows come from `base_year` in `config/score.yaml`).
2. Demand is shown as two numbers: the last 12 months and {base} (the clean base level).
3. Growth on the shortlist is triangulated outside Google: Wordstat dynamics (RU), the pace of new apps and ratings in the
   app stores, launches on Product Hunt, Google Trends (S4).
4. The `brand_share > {cfg['gate_brand_share']:.0%}` check is an informational flag, not a gate: it fires on most niches, including ones that look
   healthy, because it measures navigational demand for brands rather than concentration. Concentration is held by
   `top1_brand_share <= {cfg['gate_top1_brand_share']:.0%}`.
""")

    path = ws.report("S3-quick-filter.md")
    path.write_text("\n".join(out), encoding="utf-8")
    print("->", path)
