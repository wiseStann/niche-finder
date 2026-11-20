"""Russian app-review voice: the verdict per niche (data/out/ru_reviews_verdict.csv) and the report reports/S10-ru-reviews.md.

Input: ru_reviews_apps.csv, ru_reviews_docs.jsonl (s10_ru_reviews_fetch), ru_reviews_llm.csv, ru_reviews_themes.json
(s10_ru_reviews_classify), score_final.csv (S6, optional), config/ru_reviews.yaml (`verdict`, `sample`, `status`).

The verdict is a rule, not a score, and it does not change the S6 verdict (see reviews_verdicts()). It is relative:
written reviews lean negative, since the unhappy user is the one who writes, so an absolute complaint threshold such as
the Reddit rule's 20 % would pass nearly every niche. A share must be in the top of the cohort (mid-rank percentile among
the niches measured in this run) and above an absolute floor. With fewer than `verdict.min_cohort` measured niches the
floors alone decide. While config/ru_reviews.yaml has `status: draft` the report says so at the top.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict

from nichefinder import niches
from nichefinder.stages.info_score import pct
from nichefinder.stages.s10_ru_reviews_fetch import APPS, DOCS, STORE_NAME, config_status, settings
from nichefinder.workspace import Workspace

SUMMARY = "Report: Russian app-review voice per niche (verdict rule, pain themes, switches)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

VERD = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
VERDICT_COLS = ["niche_id", "verdict", "reason", "about_app", "apps", "unmet_share", "unmet_pct", "quality_share", "quality_pct",
                "praise_share", "cohort", "status"]


def f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def pc(x) -> str:
    v = f(x)
    return "-" if v is None else f"{v:.0%}"


def reviews_verdicts(llm_rows: dict[str, dict], cfg: dict) -> dict[str, dict]:
    """niche_id -> {verdict, reason, unmet_pct, quality_pct, cohort}. Labels: 🟢 gap, 🟡 quality, 🟡 content, 🟡 mixed, ⚪ quiet.
    `llm_rows` are rows of ru_reviews_llm.csv; `cfg` is the `verdict` block of config/ru_reviews.yaml."""
    measured = {nid: r for nid, r in llm_rows.items()
                if (f(r.get("about_app"), 0) or 0) >= cfg["min_app_reviews"] and (f(r.get("apps"), 0) or 0) >= cfg["min_apps"]}
    floors_only = len(measured) < cfg["min_cohort"]
    un = [f(r["unmet_share"], 0) for r in measured.values()]
    qu = [f(r["quality_share"], 0) for r in measured.values()]
    out = {}
    for nid, r in llm_rows.items():
        if nid not in measured:
            out[nid] = {"verdict": "⚪ quiet", "unmet_pct": "", "quality_pct": "", "cohort": len(measured),
                        "reason": f"{int(f(r.get('about_app'), 0) or 0)} labeled reviews about the app from {int(f(r.get('apps'), 0) or 0)} apps "
                                  f"(needs {cfg['min_app_reviews']} and {cfg['min_apps']}) - the Russian stores say too little about this niche"}
            continue
        u, q, p = f(r["unmet_share"], 0), f(r["quality_share"], 0), f(r["praise_share"], 0)
        pu, pq = pct(un, u), pct(qu, q)
        top_u = floors_only or pu >= cfg["gap_pct"]
        top_q = floors_only or pq >= cfg["quality_pct"]
        rank = "" if floors_only else f", percentile {pu:.0%} of {len(measured)} niches"
        if u >= cfg["gap_floor"] and top_u:
            v, why = "🟢 gap", (f"{u:.0%} of reviews about the app ask for a missing feature, complain about price or switch "
                                f"(features {pc(r['missing_feature_share'])}, price {pc(r['pricing_share'])}, switching {pc(r['switching_share'])}){rank}")
        elif q >= cfg["quality_floor"] and top_q:
            v, why = "🟡 quality", (f"{q:.0%} complain about bugs, UX, ads or support of existing apps{'' if floors_only else f', percentile {pq:.0%}'}, "
                                    f"but unmet needs are {u:.0%}: the wedge is doing the same job better, not a new job")
        elif p >= cfg["content_praise"]:
            v, why = "🟡 content", f"praise {p:.0%}, unmet needs {u:.0%}, quality complaints {q:.0%} - users are broadly happy with what exists"
        else:
            v, why = "🟡 mixed", f"unmet needs {u:.0%}, quality complaints {q:.0%}, praise {p:.0%} - no share stands out against the cohort"
        out[nid] = {"verdict": v, "reason": why, "unmet_pct": round(pu, 3), "quality_pct": round(pq, 3), "cohort": len(measured)}
    return out


def docs_stats(ws: Workspace, min_chars: int) -> tuple[dict, dict]:
    """(per niche, per (niche, store, app_id)) counts over the fetched reviews: total, substantive, low (1-2 stars), stars sum."""
    per_n, per_a = defaultdict(Counter), defaultdict(Counter)
    p = ws.out(DOCS)
    if p.is_file():
        for line in open(p, encoding="utf-8"):
            d = json.loads(line)
            for c in (per_n[d["niche_id"]], per_a[(d["niche_id"], d["store"], d["app_id"])]):
                c["n"] += 1
                c["subst"] += len(d.get("text") or "") >= min_chars
                c["low"] += d["rating"] <= 2
                c["stars"] += d["rating"]
                c[d["store"]] += 1
    return per_n, per_a


def run(ws: Workspace, args: argparse.Namespace) -> None:
    def rd(name):
        p = ws.out(name)
        return list(csv.DictReader(open(p, encoding="utf-8"))) if p.is_file() else []

    apps = rd(APPS)
    if not apps:
        print(f"{ws.out(APPS)} not found - run s10_ru_reviews_fetch first")
        return
    vcfg, scfg, fcfg = settings(ws, "verdict"), settings(ws, "sample"), settings(ws, "fetch")
    status = config_status(ws)
    names = niches.niche_names(ws)
    by_app = defaultdict(list)
    for r in apps:
        by_app[r["niche_id"]].append(r)
    llm = {r["niche_id"]: r for r in rd("ru_reviews_llm.csv")}
    tp = ws.out("ru_reviews_themes.json")
    themes = json.loads(tp.read_text(encoding="utf-8")) if tp.is_file() else {}
    score = {r["niche_id"]: r for r in rd("score_final.csv")}
    per_n, per_a = docs_stats(ws, int(scfg["min_chars"]))
    verdicts = reviews_verdicts(llm, vcfg)
    with open(ws.out("ru_reviews_verdict.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=VERDICT_COLS)
        w.writeheader()
        for nid, v in verdicts.items():
            r = llm[nid]
            w.writerow({"niche_id": nid, **{k: v[k] for k in ("verdict", "reason", "unmet_pct", "quality_pct", "cohort")},
                        **{k: r.get(k, "") for k in ("about_app", "apps", "unmet_share", "quality_share", "praise_share")}, "status": status})

    ids = list(dict.fromkeys(r["niche_id"] for r in apps))
    ids.sort(key=lambda x: -(f(score.get(x, {}).get("score"), 0) or 0))
    cohort = next((v["cohort"] for v in verdicts.values()), 0)
    n_rev = sum(per_n[x]["n"] for x in ids)
    L = [f"# S10: buyer voice - Russian app reviews (updated {ws.today.isoformat()})", ""]
    if status != "fixed":
        L += ["> **DRAFT.** The thresholds in `config/ru_reviews.yaml` are not fixed yet (`status: draft`). Fix them before reading "
              "the verdicts below as a decision, then change them only with a written reason.", ""]
    n_lab = sum(int(f(r["classified"], 0) or 0) for r in llm.values())
    L += [f"{len(ids)} niches, {len(apps)} apps, {n_rev:,} reviews from the last {fcfg['window_months']} months; {n_lab:,} labeled by an LLM.", "",
          "**How it was collected.** For each shortlisted niche whose geo includes Russia: the relevant apps with the most ratings in the Russian "
          f"App Store (`s5_appstore`) and Google Play (`s8_gplay_*`), up to {fcfg['apps_per_store']} per store with at least {fcfg['min_ratings']} ratings. "
          f"App Store: the public reviews RSS, the {50 * int(fcfg['appstore_pages'])} newest reviews at most. Google Play: the {fcfg['gplay_reviews']} newest "
          "Russian reviews (google-play-scraper). No keys.", "",
          f"**What is measured.** A sample of up to {scfg['max_reviews']} reviews per niche with at least {scfg['min_chars']} characters, drawn evenly "
          "across apps, is labeled by an LLM: whether the review is about the app or the service behind it, the intent (bug, UX, missing feature, price, "
          "ads, support, switching, praise), the pain, the switch \"from -> to\", willingness to pay and a quote. Shares are over reviews about the app: "
          "**unmet needs** = missing feature + price + switching (what a new product could offer), **quality** = bugs + UX + ads + support "
          "(the incumbents do the job badly). Pains are then clustered into themes.", "",
          "**Limits.** Reviews come from users of existing apps: they show what is missing in what people already use, not demand from people "
          "who have no app yet. Stores bias the sample (apps ask happy users for ratings; angry users write). RuStore and web services are not "
          "covered, so B2B niches without mobile apps are quiet here. App Store RSS serves at most 500 newest reviews per app, so for big apps the "
          "window is days or weeks, not a year. LLM labels and themes are not hand-validated.", "",
          "**Verdict (a rule, not a score; it does not change S6):** 🟢 \"gap\" - unmet needs >= "
          f"{vcfg['gap_floor']:.0%} and in the top of the cohort (percentile >= {vcfg['gap_pct']:.0%}); 🟡 \"quality\" - not a gap, but bug/UX/ads/support "
          f"complaints >= {vcfg['quality_floor']:.0%} and percentile >= {vcfg['quality_pct']:.0%}; 🟡 \"content\" - praise >= {vcfg['content_praise']:.0%}; "
          f"🟡 \"mixed\" - the rest; ⚪ \"quiet\" - fewer than {vcfg['min_app_reviews']} labeled reviews about the app or fewer than {vcfg['min_apps']} apps. "
          "Written reviews lean negative, so an absolute complaint threshold would pass nearly every niche; the rule compares niches with each other. "
          + (f"**This run has {cohort} measured niches (< {vcfg['min_cohort']}): percentiles are not used, the floors alone decide.**"
             if cohort < vcfg["min_cohort"] else f"Cohort: {cohort} measured niches."), "",
          "## 1. Summary", "",
          "| # | Niche | S6 | Score | Reviews verdict | Apps AS / GP | Reviews (substantive) | 1-2 stars | Unmet: feature / price / switch | Quality | Praise | Pain theme #1 | Switch #1 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, nid in enumerate(ids, 1):
        s, c, l, v = score.get(nid, {}), per_n[nid], llm.get(nid), verdicts.get(nid)
        n_as = sum(1 for r in by_app[nid] if r["store"] == "appstore")
        n_gp = sum(1 for r in by_app[nid] if r["store"] == "gplay")
        low = f"{c['low'] / c['n']:.0%}" if c["n"] else "-"
        if l:
            unmet = f"**{pc(l['unmet_share'])}**: {pc(l['missing_feature_share'])} / {pc(l['pricing_share'])} / {pc(l['switching_share'])}"
            rest = f"{pc(l['quality_share'])} | {pc(l['praise_share'])} | {l['top_theme'] or '-'} ({l['top_theme_count']}) | {l['top_switch'] or '-'}"
        else:
            unmet, rest = "-", "- | - | - | -"
        L.append(f"| {k} | {names.get(nid, nid)} | {VERD.get(s.get('verdict'), '')} | {s.get('score', '')} | {v['verdict'] if v else '- (no LLM labels)'} | "
                 f"{n_as} / {n_gp} | {c['n']} ({c['subst']}) | {low} | {unmet} | {rest} |")
    groups = defaultdict(list)
    for nid in ids:
        if nid in verdicts:
            groups[verdicts[nid]["verdict"]].append(nid)
    by_unmet = lambda xs: sorted(xs, key=lambda x: -(f(llm[x]["unmet_share"], 0) or 0))  # noqa: E731
    L += ["", "## 2. What this says", "",
          f"- **🟢 gap ({len(groups['🟢 gap'])})**: " + (", ".join(f"{names.get(x, x)} ({pc(llm[x]['unmet_share'])})" for x in by_unmet(groups["🟢 gap"])) or "-")
          + ". Users of the existing apps ask for what is missing, argue about price or move between apps more than in other niches: a concrete wedge for "
          "a new product. Read the unmet themes below before believing it.",
          f"- **🟡 quality ({len(groups['🟡 quality'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 quality"]) or "-")
          + ". The apps do the job, but badly (crashes, clumsy UX, ads, silent support): entering means out-executing incumbents.",
          f"- **🟡 content ({len(groups['🟡 content'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 content"]) or "-") + ".",
          f"- **🟡 mixed ({len(groups['🟡 mixed'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 mixed"]) or "-") + ".",
          f"- **⚪ quiet ({len(groups['⚪ quiet'])})**: " + (", ".join(names.get(x, x) for x in groups["⚪ quiet"]) or "-")
          + ". Few reviews are not a signal against the niche: the audience may use web services, RuStore or no app at all.", "",
          "## 3. By niche", ""]
    for k, nid in enumerate(ids, 1):
        s, c, l, v, t = score.get(nid, {}), per_n[nid], llm.get(nid), verdicts.get(nid), themes.get(nid) or {}
        L += [f"### {k}. {names.get(nid, nid)} - {v['verdict'] if v else 'no LLM labels'}", "",
              f"S6: {VERD.get(s.get('verdict'), '')} score {s.get('score', '-')}." + (f" Reviews verdict: {v['reason']}." if v else ""), "",
              "| Store | App | Ratings | Stars | Reviews kept | 1-2 stars | Oldest kept | LLM: unmet / quality / praise |", "|---|---|---|---|---|---|---|---|"]
        for r in sorted(by_app[nid], key=lambda r: (r["store"], -(f(r["ratings"], 0) or 0))):
            a = per_a[(nid, r["store"], r["app_id"])]
            la = (t.get("apps") or {}).get(f"{r['store']}:{r['app']}") or {}
            lab = f"{la['unmet'] / la['n']:.0%} / {la['quality'] / la['n']:.0%} / {la['praise'] / la['n']:.0%} (n={la['n']})" if la.get("n") else "-"
            st = "" if r["status"] == "ok" else f" ({r['status']})"
            low_a = f"{a['low'] / a['n']:.0%}" if a["n"] else "-"
            L.append(f"| {STORE_NAME.get(r['store'], r['store'])} | {r['app'][:50]} | {int(f(r['ratings'], 0) or 0):,} | {f(r['rating'], 0):.1f} | "
                     f"{r['kept']}{st} | {low_a} | {r['oldest'] or '-'} | {lab} |")
        if l:
            L += ["", f"- **LLM labels** ({l['classified']} reviews, {l['about_app']} about the app, {pc(l['app_share'])}): missing feature {pc(l['missing_feature_share'])}, "
                      f"price {pc(l['pricing_share'])}, switching {pc(l['switching_share'])}, bugs {pc(l['bug_share'])}, UX {pc(l['ux_share'])}, ads {pc(l['ads_share'])}, "
                      f"support {pc(l['support_share'])}, praise {pc(l['praise_share'])}; willingness to pay: \"too expensive\" {l['too_expensive']}, "
                      f"\"worth the money\" {l['worth_it']}, \"want it free\" {l['wants_free']}, \"cancelled\" {l['cancelled']}."]
        if t.get("themes"):
            L += ["", "**Pain themes** (LLM clustering, descending):", ""]
            for th in t["themes"][:10]:
                qs = "; ".join(f"\"{str(q)[:150]}\"" for q in (th.get("quotes") or [])[:2])
                L.append(f"- **{th.get('theme', '')}** [{th.get('kind', '')}] ({th.get('count', '')}) - {th.get('description', '')}" + (f" Quotes: {qs}" if qs else ""))
        sw = [(a, n) for a, n in (t.get("switching") or []) if "?" not in a]
        if sw:
            L += ["", "**Switches \"from -> to\":** " + "; ".join(f"{a} ({n})" for a, n in sw[:10]) + "."]
        L.append("")
    L += ["---", "", "_Stages: `s10_ru_reviews_fetch`, `s10_ru_reviews_classify` (LLM), `s10_ru_reviews_report`. Settings: `config/ru_reviews.yaml`. "
          "Data: `data/out/ru_reviews_docs.jsonl`, `ru_reviews_apps.csv`, `ru_reviews_items.jsonl`, `ru_reviews_llm.csv`, `ru_reviews_themes.json`, "
          "`ru_reviews_verdict.csv`._", ""]
    ws.report("S10-ru-reviews.md").write_text("\n".join(L), encoding="utf-8")
    print(f"-> reports/S10-ru-reviews.md, ru_reviews_verdict.csv: {len(ids)} niches;", dict(Counter(v["verdict"] for v in verdicts.values())))
