"""Russian B2B: combine the five measures into a score and a report.

Inputs (data/out/): ru_b2b_wordstat.csv, ru_b2b_wordstat_dyn.csv, ru_b2b_hh.csv, ru_b2b_zakupki.csv, ru_b2b_reestr.csv,
ru_b2b_bitrix.csv, optionally ru_b2b_reestr_classes.csv, ru_vendor_revenue.csv (vendor income from FNS open data) and
ru_ecosystems.csv (YCLIENTS / MoySklad / amoCRM apps) - both shown per niche, not in the score;
configs: config/ru_b2b_niches.yaml, config/ru_b2b_traps.yaml.
Output: data/out/ru_b2b_score.csv and reports/S0-ru-b2b.md.

Score (percentiles are taken inside the RU B2B cohort; weights follow the spirit of the global score):
  demand 35        = 15 * pct(sum of Wordstat brand + category phrases; trap phrases from ru_b2b_traps.yaml excluded)
                     + 10 * pct(sum of hh.ru vacancies for the roles) + 10 * pct(procurements with the phrase in the title, 12 months)
  growth 20        = 10 * pct(yoy of Wordstat dynamics) + 5 * pct(yoy of procurements) + 5 * pct(share of 2025-26 products in the register)
  fragmentation 25 = 10 * (1 - top brand share in Wordstat) + 5 * pct(owners in the register)
                     + 5 * (1 - Bitrix24 Market leader share) + 5 * (1 - largest register owner share)
  money/adoption 20 = 10 * pct(sum of initial contract prices, 12 months) + 10 * pct(vacancies mentioning a brand)
`stack_fit` (0-3, set per niche in the niches config) is NOT part of the score; it is shown beside it.
Flags: C:brand-leader (top brand > 60% of brand searches), C:bitrix-leader (> 60% of installs),
Z:noisy (procurements: < 30% have the phrase in the title), W:low (Wordstat sum < 500).
Verdict (a rule, not manual): red "monopoly" - top brand > 70% of brand searches with a brand sum of at least 5,000;
yellow - top brand 50-70% or score below the cohort median; green - the rest.
"""
from __future__ import annotations

import argparse
import csv

from nichefinder.workspace import Workspace

SUMMARY = "Russian B2B: score and report from the five measures"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def pct(values, v):
    vals = [x for x in values if x is not None]
    if v is None or not vals:
        return 0.5
    return sum(1 for x in vals if x <= v) / len(vals)


def vendor_lines(v: dict | None) -> list[str]:
    """Income of the register's right holders (ru_vendor_revenue): evidence, not in the score."""
    if not v or not f(v.get("owners")):
        return []
    g = f(v.get("income_growth"))
    return [f"- **Vendor income** (FNS open data, statements for {v.get('year') or '-'}; not in the score): {v['matched']} of {v['owners']} register owners "
            f"matched by name ({v['ambiguous']} ambiguous, {v['diversified']} large groups left out); total {f(v['income_sum'], 0) / 1e6:,.0f} M RUB, "
            f"median {f(v.get('income_median'), 0) / 1e6:,.1f} M RUB, {v['vendors_100m']} vendors with 100 M RUB or more, "
            f"largest «{v['top_vendor']}» {f(v.get('top_share'), 0):.0%}" + (f"; income growth of vendors matched in both years {g:+.0%}" if g is not None else "") + "."]


def eco_lines(rows: list[dict] | None) -> list[str]:
    """Apps in Russian SMB marketplaces (ru_ecosystems): evidence, not in the score."""
    out = []
    for r in rows or []:
        if not f(r.get("apps")):
            continue
        name = {"moysklad": "MoySklad apps", "amocrm": "amoCRM widgets (public showcase)"}.get(r.get("marketplace", ""), r.get("marketplace", ""))
        lead = f", largest developer «{r['top_developer']}» {f(r.get('top_developer_share'), 0):.0%} of the apps" if r.get("top_developer") else ""
        paid = f(r.get("paid_share"))
        out.append(f"- **{name}:** {r['apps']} of {r.get('catalog', '?')} apps from {r.get('developers') or '?'} developers{lead}"
                   + (f", paid {paid:.0%}" if paid is not None else "") + " (no installs published; not in the score).")
    return out


def _by_niche(ws: Workspace, name: str, key: str = "niche_id") -> dict[str, dict]:
    """Rows of data/out/<name> keyed by `key`; an empty dict when the file is missing."""
    p = ws.out(name)
    return {r[key]: r for r in csv.DictReader(open(p, encoding="utf-8"))} if p.exists() else {}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    def rd(name):
        return _by_niche(ws, name)

    niches = ws.load_config("ru_b2b_niches.yaml")
    reestr, bitrix, zak, hh = rd("ru_b2b_reestr.csv"), rd("ru_b2b_bitrix.csv"), rd("ru_b2b_zakupki.csv"), rd("ru_b2b_hh.csv")
    dyn = rd("ru_b2b_wordstat_dyn.csv")
    traps = (ws.load_config("ru_b2b_traps.yaml", {}) or {}).get("ws_traps", {}) or {}
    wsd = {}
    p = ws.out("ru_b2b_wordstat.csv")
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if r["kind"] == "ws_brands" and r["phrase"] in traps:
                wsd.setdefault(r["niche_id"], {"brands": [], "cat": [], "trapped": []})["trapped"].append(f"{r['phrase']}={int(f(r['total_count'], 0) or 0)} ({traps[r['phrase']]})")
                continue
            wsd.setdefault(r["niche_id"], {"brands": [], "cat": [], "trapped": []})[("brands" if r["kind"] == "ws_brands" else "cat")].append((r["phrase"], f(r["total_count"], 0) or 0))
    rows = []
    for n in niches:
        nid = n["id"]
        w = wsd.get(nid, {"brands": [], "cat": [], "trapped": []})
        bsum = sum(c for _, c in w["brands"] if c > 0)
        csum = sum(c for _, c in w["cat"] if c > 0)
        btop = max(w["brands"], key=lambda x: x[1]) if w["brands"] else ("", 0)
        r, b, z, h, d = reestr.get(nid, {}), bitrix.get(nid, {}), zak.get(nid, {}), hh.get(nid, {}), dyn.get(nid, {})
        prod = f(r.get("products"), 0) or 0
        rows.append({
            "niche_id": nid, "name": n["name"], "stack_fit": n.get("stack_fit", 1),
            "ws_brands_sum": bsum, "ws_top_brand": btop[0], "ws_top_share": round(btop[1] / bsum, 2) if bsum else None, "ws_cat_sum": csum,
            "ws_brands_detail": "; ".join(f"{p}={int(c)}" for p, c in sorted(w["brands"], key=lambda x: -x[1])) + (("; excluded: " + "; ".join(w["trapped"])) if w["trapped"] else ""),
            "ws_dyn_yoy": f(d.get("yoy")), "ws_dyn_verdict": d.get("verdict", ""), "ws_dyn_phrase": d.get("phrase", ""), "ws_dyn_last12": f(d.get("last12")),
            "hh_roles": f(h.get("roles_sum")), "hh_roles_detail": h.get("roles_detail", ""), "hh_brands": f(h.get("brands_sum")), "hh_brands_detail": h.get("brands_detail", ""),
            "zak_last12": f(z.get("last12_titled")), "zak_prev12": f(z.get("prev12_titled")), "zak_total_last12": f(z.get("last12_total")),
            "zak_yoy": (f(z.get("last12_titled"), 0) / f(z.get("prev12_titled"), 0) - 1) if f(z.get("prev12_titled"), 0) else None,
            "zak_sum_rub": f(z.get("last12_sum_rub")), "zak_median_rub": f(z.get("last12_median_rub")),
            "reestr_products": prod, "reestr_ai": f(r.get("ai_products"), 0) or 0, "reestr_owners": f(r.get("owners")), "reestr_top_owner_share": f(r.get("top_owner_share")),
            "reestr_new_25_26": (f(r.get("new_2025"), 0) or 0) + (f(r.get("new_2026"), 0) or 0), "reestr_new_share": ((f(r.get("new_2025"), 0) or 0) + (f(r.get("new_2026"), 0) or 0)) / prod if prod else None,
            "reestr_classes": r.get("top_classes", ""), "reestr_detail": r.get("per_keyword", ""),
            "bitrix_apps_100": f(b.get("apps_100")), "bitrix_top1_share": f(b.get("top1_share")), "bitrix_top1": b.get("top1", ""),
        })
    if not rows:
        print("no niches in config/ru_b2b_niches.yaml")
        return
    for x in rows:
        x["ws_demand"] = x["ws_brands_sum"] + x["ws_cat_sum"]
    keys = ["ws_demand", "hh_roles", "zak_last12", "ws_dyn_yoy", "zak_yoy", "reestr_new_share", "reestr_owners", "zak_sum_rub", "hh_brands"]
    coh = {k: [x[k] for x in rows] for k in keys}
    for x in rows:
        s_dem = 15 * pct(coh["ws_demand"], x["ws_demand"]) + 10 * pct(coh["hh_roles"], x["hh_roles"]) + 10 * pct(coh["zak_last12"], x["zak_last12"])
        s_gr = 10 * pct(coh["ws_dyn_yoy"], x["ws_dyn_yoy"]) + 5 * pct(coh["zak_yoy"], x["zak_yoy"]) + 5 * pct(coh["reestr_new_share"], x["reestr_new_share"])
        s_fr = 10 * (1 - (x["ws_top_share"] if x["ws_top_share"] is not None else 0.5)) + 5 * pct(coh["reestr_owners"], x["reestr_owners"]) \
            + 5 * (1 - (x["bitrix_top1_share"] if x["bitrix_top1_share"] is not None else 0.5)) + 5 * (1 - (x["reestr_top_owner_share"] if x["reestr_top_owner_share"] is not None else 0.5))
        s_mo = 10 * pct(coh["zak_sum_rub"], x["zak_sum_rub"]) + 10 * pct(coh["hh_brands"], x["hh_brands"])
        x.update({"s_demand": round(s_dem, 1), "s_growth": round(s_gr, 1), "s_frag": round(s_fr, 1), "s_money": round(s_mo, 1), "score": round(s_dem + s_gr + s_fr + s_mo, 1)})
        flags = []
        if x["ws_top_share"] is not None and x["ws_top_share"] > 0.6:
            flags.append("C:brand-leader")
        if x["bitrix_top1_share"] is not None and x["bitrix_top1_share"] > 0.6:
            flags.append("C:bitrix-leader")
        if x["zak_total_last12"] and x["zak_last12"] is not None and x["zak_last12"] / x["zak_total_last12"] < 0.3:
            flags.append("Z:noisy")
        if x["ws_demand"] < 500:
            flags.append("W:low")
        x["flags"] = ";".join(flags)
    med = sorted(x["score"] for x in rows)[len(rows) // 2]
    for x in rows:
        top = x["ws_top_share"] if x["ws_top_share"] is not None else 0
        if top > 0.7 and x["ws_brands_sum"] >= 5000:
            x["verdict"] = "🔴 monopoly"
        elif top > 0.5 or x["score"] < med:
            x["verdict"] = "🟡"
        else:
            x["verdict"] = "🟢"
    rows.sort(key=lambda x: ({"🟢": 0, "🟡": 1}.get(x["verdict"], 2), -x["score"]))
    with open(ws.out("ru_b2b_score.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("-> ru_b2b_score.csv")
    write_report(ws, rows, niches)


def write_report(ws: Workspace, rows, niches) -> None:
    nm = lambda v, fmt="{:,.0f}": (fmt.format(v).replace(",", " ") if v is not None else "—")  # noqa: E731
    pc = lambda v: (f"{v:+.0%}" if v is not None else "—")  # noqa: E731
    sh = lambda v: (f"{v:.0%}" if v is not None else "—")  # noqa: E731
    L = [f"# S0 RU B2B — {len(rows)} niches across five measures ({ws.today.isoformat()})", "",
         "A separate Russian branch of the pipeline: the global tools (Keyword Planner, App Store, Capterra) do not see Russian B2B, and Wordstat category phrases are close to zero. "
         "Demand is measured here by the sum of brand queries (Wordstat), vacancies for automatable roles (hh.ru) and procurements with the phrase in the title (zakupki.gov.ru, 44-FZ/223-FZ); "
         "supply by the domestic software register (search by name) and Bitrix24 Market; adoption by vacancies that name a brand and by the sum of initial contract prices. "
         "The score formula is in the docstring of `nichefinder/stages/ru_report.py`; `stack_fit` is not part of the score. Data: `data/out/ru_b2b_*.csv`; keys: `config/ru_b2b_niches.yaml`.", "",
         "**Limits.** The register is searched by product name, so branded products without a category word (\"YCLIENTS\") are missed; Bitrix search is fuzzy (neighbouring topics appear) and is only a rough signal; "
         "procurements are B2G/large B2B rather than SMB, and full-text search matches attachments (the \"in title\" column is cleaner); hh roles show how many businesses hire a person for the task, not demand for software; "
         "Wordstat brands are only the ones listed by hand (3-6 per niche), so the \"category size\" is understated for niches with a long tail.", "",
         "## 1. Leaderboard", "",
         "| # | Verdict | Niche | Score | Demand | Growth | Fragm. | Money | Stack | Wordstat sum brands + category (top brand, share) | Dynamics (36 mo) | hh: roles / brands | Procurements 12 mo (title) · yoy · sum RUB | Register: products / owners / new 25-26 | Bitrix: >=100 installs / leader | Flags |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, x in enumerate(rows, 1):
        L.append(f"| {i} | {x['verdict']} | **{x['name']}** (`{x['niche_id']}`) | **{x['score']}** | {x['s_demand']} | {x['s_growth']} | {x['s_frag']} | {x['s_money']} | {x['stack_fit']} | "
                 f"{nm(x['ws_brands_sum'])} + {nm(x['ws_cat_sum'])} ({x['ws_top_brand'] or '—'} {sh(x['ws_top_share'])}) | {x['ws_dyn_verdict'] or '—'} {pc(x['ws_dyn_yoy'])} «{x['ws_dyn_phrase']}» | "
                 f"{nm(x['hh_roles'])} / {nm(x['hh_brands'])} | {nm(x['zak_last12'])} · {pc(x['zak_yoy'])} · {nm((x['zak_sum_rub'] or 0) / 1e6, '{:,.0f}')} M | "
                 f"{nm(x['reestr_products'])} / {nm(x['reestr_owners'])} / {nm(x['reestr_new_25_26'])} | {nm(x['bitrix_apps_100'])} / {sh(x['bitrix_top1_share'])} | {x['flags']} |")
    L += ["", "## 2. By niche (measurement details)", ""]
    vrev = _by_niche(ws, "ru_vendor_revenue.csv")     # evidence, not in the score
    eco: dict[str, list[dict]] = {}
    if ws.out("ru_ecosystems.csv").exists():
        for r in csv.DictReader(open(ws.out("ru_ecosystems.csv"), encoding="utf-8")):
            eco.setdefault(r["niche_id"], []).append(r)
    for x in rows:
        n = next(y for y in niches if y["id"] == x["niche_id"])
        L += [f"### {x['name']}", "",
              f"`{x['niche_id']}` · {x['verdict']} · score **{x['score']}** · stack {x['stack_fit']}/3 · {n.get('product', '')} · who: {n.get('who', '')}", "",
              f"- **Wordstat, brands:** {x['ws_brands_detail'] or '—'}; category phrases sum {nm(x['ws_cat_sum'])}. Dynamics «{x['ws_dyn_phrase']}»: {x['ws_dyn_verdict'] or '—'}, yoy {pc(x['ws_dyn_yoy'])}, 12 months {nm(x['ws_dyn_last12'])}.",
              f"- **hh.ru:** roles — {x['hh_roles_detail'] or '—'}; brands — {x['hh_brands_detail'] or '—'}.",
              f"- **Procurements:** with the phrase in the title {nm(x['zak_last12'])} (previous 12 months {nm(x['zak_prev12'])}; all full-text matches {nm(x['zak_total_last12'])}); sum of initial prices {nm((x['zak_sum_rub'] or 0) / 1e6, '{:,.1f}')} M RUB, median {nm((x['zak_median_rub'] or 0) / 1e3, '{:,.0f}')} k RUB.",
              f"- **Software register:** {nm(x['reestr_products'])} products ({x['reestr_detail']}), of which flagged AI {nm(x['reestr_ai'])}; owners {nm(x['reestr_owners'])}, largest {sh(x['reestr_top_owner_share'])}; new in 2025-26: {nm(x['reestr_new_25_26'])}; classes: {x['reestr_classes'] or '—'}.",
              f"- **Bitrix24 Market:** apps with at least 100 installs {nm(x['bitrix_apps_100'])}, leader «{x['bitrix_top1']}» {sh(x['bitrix_top1_share'])} (fuzzy search).",
              *vendor_lines(vrev.get(x["niche_id"])), *eco_lines(eco.get(x["niche_id"])),
              f"- Note: {n.get('notes') or ''}", ""]
    cp = ws.out("ru_b2b_reestr_classes.csv")
    if cp.exists():
        cl = [r for r in csv.DictReader(open(cp, encoding="utf-8"))]
        for r in cl:
            r["products"] = int(r["products"] or 0)
            r["ai_products"] = int(r["ai_products"] or 0)
        tot = sum(r["products"] for r in cl)
        tai = sum(r["ai_products"] for r in cl)
        L += ["## 3. Domestic software register by class (classifier 486)", "",
              f"The register holds {tot:,} entries across {len(cl)} classes (one entry can sit in several classes), {tai:,} of them flagged AI. Top 25 classes by number of products and their AI share - where Russian vendors already compete and where AI is going:".replace(",", " "), "",
              "| Code | Class | Products | AI flagged | AI share |", "|---|---|---|---|---|"]
        for r in sorted(cl, key=lambda r: -r["products"])[:25]:
            L.append(f"| {r['code']} | {r['name']} | {r['products']:,} | {r['ai_products']} | {r['ai_products'] / r['products']:.0%} |".replace(",", " "))
        L += ["", "Classes with the highest AI share (at least 20 products):", "", "| Code | Class | Products | AI | Share |", "|---|---|---|---|---|"]
        for r in sorted([r for r in cl if r["products"] >= 20], key=lambda r: -(r["ai_products"] / r["products"]))[:12]:
            L.append(f"| {r['code']} | {r['name']} | {r['products']} | {r['ai_products']} | {r['ai_products'] / r['products']:.0%} |")
        L.append("")
    p = ws.report("S0-ru-b2b.md")
    p.write_text("\n".join(L), encoding="utf-8")
    print("->", p)
