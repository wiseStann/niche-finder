"""Russian review voice (App Store, Google Play, Startpack): the verdict per niche (data/out/ru_reviews_verdict.csv) and
the report reports/S10-ru-reviews.md.

Input: ru_reviews_apps.csv, ru_reviews_docs.jsonl (s10_ru_reviews_fetch), ru_reviews_llm.csv, ru_reviews_items.jsonl,
ru_reviews_themes.json (s10_ru_reviews_classify), score_final.csv (S6, optional), niches.yaml (side), config/ru_reviews.yaml (`verdict`,
`sample`, `status`).

The verdict is a rule, not a score, and it does not change the S6 verdict (see reviews_verdicts()). It is relative:
written reviews lean negative, since the unhappy user is the one who writes, so an absolute complaint threshold such as
the Reddit rule's 20 % would pass nearly every niche. A share must be in the top of the cohort (mid-rank percentile among
the niches of the same segment measured in this run: B2C + prosumer, or B2B) and above an absolute floor. Segments are
separate because their sources differ: app stores for B2C, mostly Startpack for B2B, which leans positive. With fewer
than `verdict.min_cohort` measured niches in a segment the floors alone decide. While config/ru_reviews.yaml has
`status: draft` the report says so at the top.

The gap counts a missing feature or a switch only in a review rated `verdict.low_rating` stars or lower (counted from
ru_reviews_items.jsonl): a feature wish in a five-star review is a wishlist, not an unmet need. A niche with fewer than
`verdict.min_low_reviews` such reviews is "unmeasured" rather than "content", since few unhappy reviews on Startpack say
more about the source than about the market. Price complaints are not part of the gap: in unhappy app store reviews they
are mostly anger at a paywall, and the hardest paywalls are in saturated clone markets (the controls ctrl-document-scanner
and ctrl-ai-song-generator topped the gap when price counted). They get a separate mark, "💰 paywall", by the same
percentile + floor rule (`paywall_pct`, `paywall_floor`), which never changes the verdict. Reasons: methodology,
"Russian buyer voice: reviews".
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

SUMMARY = "Report: Russian review voice per niche (verdict rule within B2C/B2B, gap from unhappy reviews, paywall mark, pain themes)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

VERD = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
GAP_INTENTS = ("missing_feature", "switching")   # price is not a gap: see the module docstring
PAYWALL = "💰 paywall"
VERDICT_COLS = ["niche_id", "verdict", "paywall", "reason", "about_app", "apps", "unmet_share", "low_reviews", "unmet_low_share",
                "unmet_pct", "price_low_share", "price_pct", "quality_share", "quality_pct", "praise_share", "segment", "cohort",
                "gap_cohort", "status"]


def f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def pc(x) -> str:
    v = f(x)
    return "-" if v is None else f"{v:.0%}"


def segment(side: str) -> str:
    """Cohort of a niche: B2C (b2c, prosumer) or B2B, as in s6_score. Sources differ by segment (app stores vs Startpack)."""
    return "B2C" if side in ("b2c", "prosumer") else "B2B"


def unhappy_unmet(ws: Workspace, low_rating: int) -> dict[str, dict]:
    """niche_id -> {low_reviews, unmet_low_share, price_low_share} from ru_reviews_items.jsonl: reviews about the app rated
    `low_rating` stars or lower, and the shares of all reviews about the app that are such a review asking for a missing
    feature or switching (the gap), or complaining about price (the paywall mark)."""
    c = defaultdict(Counter)
    p = ws.out("ru_reviews_items.jsonl")
    if p.is_file():
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if r.get("about") != "app":
                continue
            k = c[r["niche_id"]]
            k["app"] += 1
            stars = f(r.get("rating"))
            if stars is not None and stars <= low_rating:
                k["low"] += 1
                k["unmet_low"] += r.get("intent") in GAP_INTENTS
                k["price_low"] += r.get("intent") == "pricing"
    return {nid: {"low_reviews": k["low"], "unmet_low_share": round(k["unmet_low"] / k["app"], 3),
                  "price_low_share": round(k["price_low"] / k["app"], 3)} for nid, k in c.items() if k["app"]}


def reviews_verdicts(llm_rows: dict[str, dict], cfg: dict, segments: dict[str, str] | None = None) -> dict[str, dict]:
    """niche_id -> {verdict, paywall, reason, unmet_pct, price_pct, quality_pct, segment, cohort, gap_cohort}. Labels: 🟢 gap,
    🟡 quality, 🟡 content, 🟡 mixed, ⚪ unmeasured, ⚪ quiet; `paywall` is PAYWALL or "", a mark beside any measured verdict.
    `llm_rows` are rows of ru_reviews_llm.csv plus `low_reviews`, `unmet_low_share` and `price_low_share` (unhappy_unmet());
    `cfg` is the `verdict` block of config/ru_reviews.yaml; `segments` maps niche_id to its cohort (percentiles are taken
    within it; one cohort when omitted).
    The gap share is unmet_low_share: a missing feature or a switch counts only in a review rated cfg["low_rating"] or lower.
    It is ranked among the niches of the segment where it can be read (at least cfg["min_low_reviews"] such reviews);
    elsewhere the gap is unmeasured, and a niche that is not "quality" gets "unmeasured" instead of "content" or "mixed".
    The paywall mark ranks price_low_share the same way (paywall_pct, paywall_floor)."""
    seg = {nid: (segments or {}).get(nid, "all") for nid in llm_rows}
    measured = {nid: r for nid, r in llm_rows.items()
                if (f(r.get("about_app"), 0) or 0) >= cfg["min_app_reviews"] and (f(r.get("apps"), 0) or 0) >= cfg["min_apps"]}
    readable = {nid for nid, r in measured.items() if (f(r.get("low_reviews"), 0) or 0) >= cfg["min_low_reviews"]}
    out = {}
    for nid, r in llm_rows.items():
        peers = [m for m in measured if seg[m] == seg[nid]]
        if nid not in measured:
            out[nid] = {"verdict": "⚪ quiet", "paywall": "", "unmet_pct": "", "price_pct": "", "quality_pct": "", "segment": seg[nid], "cohort": len(peers),
                        "gap_cohort": sum(1 for m in peers if m in readable),
                        "reason": f"{int(f(r.get('about_app'), 0) or 0)} labeled reviews about the app from {int(f(r.get('apps'), 0) or 0)} apps "
                                  f"(needs {cfg['min_app_reviews']} and {cfg['min_apps']}) - Russian reviews say too little about this niche"}
            continue
        gap_peers = [m for m in peers if m in readable]
        q_floors_only = len(peers) < cfg["min_cohort"]
        u_floors_only = len(gap_peers) < cfg["min_cohort"]
        qu = [f(measured[m]["quality_share"], 0) for m in peers]
        un = [f(measured[m].get("unmet_low_share"), 0) for m in gap_peers]
        pr = [f(measured[m].get("price_low_share"), 0) for m in gap_peers]
        ul, q, p = f(r.get("unmet_low_share"), 0), f(r["quality_share"], 0), f(r["praise_share"], 0)
        pl = f(r.get("price_low_share"), 0)
        low, stars = int(f(r.get("low_reviews"), 0) or 0), cfg["low_rating"]
        pu = pct(un, ul) if nid in readable else None
        pp = pct(pr, pl) if nid in readable else None
        pq = pct(qu, q)
        top_u = nid in readable and (u_floors_only or pu >= cfg["gap_pct"])
        top_q = q_floors_only or pq >= cfg["quality_pct"]
        rank = "" if u_floors_only or pu is None else f", percentile {pu:.0%} of {len(gap_peers)} {seg[nid]} niches where the gap can be read"
        unread = (f"only {low} of {int(f(r['about_app'], 0) or 0)} reviews about the app are rated {stars} stars or lower (needs "
                  f"{cfg['min_low_reviews']}), and an unmet need counts only in such a review, so a gap cannot be read here")
        if top_u and ul >= cfg["gap_floor"]:
            v, why = "🟢 gap", (f"{ul:.0%} of reviews about the app are rated {stars} stars or lower and ask for a missing feature or "
                                f"switch (in all reviews: features {pc(r['missing_feature_share'])}, switching {pc(r['switching_share'])}){rank}")
        elif q >= cfg["quality_floor"] and top_q:
            v, why = "🟡 quality", (f"{q:.0%} complain about bugs, UX, ads or support of existing apps{'' if q_floors_only else f', percentile {pq:.0%}'}, "
                                    + (f"but unmet needs in reviews of {stars} stars or lower are {ul:.0%}: the wedge is doing the same job better, not a new job"
                                       if nid in readable else f"while {unread}"))
        elif nid not in readable:
            v, why = "⚪ unmeasured", f"{unread}; praise {p:.0%}, quality complaints {q:.0%}"
        elif p >= cfg["content_praise"]:
            v, why = "🟡 content", (f"praise {p:.0%}, unmet needs in reviews of {stars} stars or lower {ul:.0%}, quality complaints {q:.0%} - "
                                    "users are broadly happy with what exists")
        else:
            v, why = "🟡 mixed", (f"unmet needs in reviews of {stars} stars or lower {ul:.0%}, quality complaints {q:.0%}, praise {p:.0%} - "
                                  "no share stands out against the cohort")
        paywall = nid in readable and pl >= cfg["paywall_floor"] and (u_floors_only or pp >= cfg["paywall_pct"])
        if paywall:
            why += (f"; {PAYWALL}: {pl:.0%} of reviews about the app are rated {stars} stars or lower and complain about price or the paywall"
                    + ("" if u_floors_only else f" (percentile {pp:.0%})") + " - a mark, not a gap: hard paywalls are common in saturated clone markets")
        top = f(r.get("top_app_share"), 0) or 0
        if top > cfg["top_app_warn"]:
            why += f"; caution: {top:.0%} of these reviews are about one product ({str(r.get('top_app', '')).split(':', 1)[-1]}), so this is mostly its users' voice"
        out[nid] = {"verdict": v, "paywall": PAYWALL if paywall else "", "reason": why, "unmet_pct": "" if pu is None else round(pu, 3),
                    "price_pct": "" if pp is None else round(pp, 3), "quality_pct": round(pq, 3),
                    "segment": seg[nid], "cohort": len(peers), "gap_cohort": len(gap_peers)}
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
    unhappy = unhappy_unmet(ws, int(vcfg["low_rating"]))
    for nid, r in llm.items():
        r.update(unhappy.get(nid) or {"low_reviews": "", "unmet_low_share": "", "price_low_share": ""})
    if llm and not unhappy:
        print(f"{ws.out('ru_reviews_items.jsonl')} not found - the gap cannot be read; re-run s10_ru_reviews_classify (cached, free)")
    tp = ws.out("ru_reviews_themes.json")
    themes = json.loads(tp.read_text(encoding="utf-8")) if tp.is_file() else {}
    score = {r["niche_id"]: r for r in rd("score_final.csv")}
    per_n, per_a = docs_stats(ws, int(scfg["min_chars"]))
    segments = {n["id"]: segment(n.get("side", "")) for n in niches.load_niches(ws)}
    verdicts = reviews_verdicts(llm, vcfg, segments)
    with open(ws.out("ru_reviews_verdict.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=VERDICT_COLS)
        w.writeheader()
        for nid, v in verdicts.items():
            r = llm[nid]
            w.writerow({"niche_id": nid, **{k: v[k] for k in ("verdict", "paywall", "reason", "unmet_pct", "price_pct", "quality_pct", "segment",
                                                                "cohort", "gap_cohort")},
                        **{k: r.get(k, "") for k in ("about_app", "apps", "unmet_share", "low_reviews", "unmet_low_share", "price_low_share",
                                                     "quality_share", "praise_share")},
                        "status": status})

    ids = list(dict.fromkeys(r["niche_id"] for r in apps))
    ids.sort(key=lambda x: -(f(score.get(x, {}).get("score"), 0) or 0))
    cohorts = {v["segment"]: (v["cohort"], v["gap_cohort"]) for v in verdicts.values()}
    mc = vcfg["min_cohort"]
    cohort_note = "; ".join(f"{s} {c} measured niches" + (f" (< {mc}: the floors alone decide)" if c < mc else "")
                            + f", the gap readable in {g}" + (f" (< {mc}: the gap floor alone decides)" if g < mc <= c else "")
                            for s, (c, g) in sorted(cohorts.items()))
    stars = vcfg["low_rating"]
    n_rev = sum(per_n[x]["n"] for x in ids)
    L = [f"# S10: buyer voice - Russian reviews: App Store, Google Play, Startpack (updated {ws.today.isoformat()})", ""]
    if status != "fixed":
        L += ["> **DRAFT.** The thresholds in `config/ru_reviews.yaml` are not fixed yet (`status: draft`). Fix them before reading "
              "the verdicts below as a decision, then change them only with a written reason.", ""]
    n_lab = sum(int(f(r["classified"], 0) or 0) for r in llm.values())
    L += [f"{len(ids)} niches, {len(apps)} products, {n_rev:,} reviews (app stores: the last {fcfg['window_months']} months, Startpack: the last "
          f"{fcfg['startpack_window_months']}); {n_lab:,} labeled by an LLM.", "",
          "**How it was collected.** For each shortlisted niche whose geo includes Russia: the relevant apps with the most ratings in the Russian "
          f"App Store (`s5_appstore`) and Google Play (`s8_gplay_*`), up to {fcfg['apps_per_store']} per store with at least {fcfg['min_ratings']} ratings. "
          f"App Store: the public reviews RSS, the {50 * int(fcfg['appstore_pages'])} newest reviews at most. Google Play: the {fcfg['gplay_reviews']} newest "
          "Russian reviews (google-play-scraper). Startpack (a catalogue of business software, the B2B voice): the products listed for the niche in "
          f"`config/startpack_map.yaml`, up to {50 * int(fcfg['startpack_pages'])} newest reviews each (pros, cons, text). No keys.", "",
          f"**What is measured.** A sample of up to {scfg['max_reviews']} reviews per niche with at least {scfg['min_chars']} characters, drawn evenly "
          "across apps, is labeled by an LLM: whether the review is about the app or the service behind it, the intent (bug, UX, missing feature, price, "
          "ads, support, switching, praise), the pain, the switch \"from -> to\", willingness to pay and a quote. Shares are over reviews about the app: "
          "**unmet needs** = missing feature + price + switching, **quality** = bugs + UX + ads + support (the incumbents do the job badly). "
          f"**The gap** counts a missing feature or a switch only in a review rated {stars} stars or lower: a feature wish in a five-star review is a "
          "wishlist (Startpack asks every reviewer for cons), and a switch in a happy review is usually an arrival from a competitor, a sign that "
          f"substitutes exist. **Price** is not part of the gap: in unhappy reviews it is mostly anger at a paywall, and the hardest paywalls are in "
          "saturated clone markets (the document-scanner and AI-song controls topped the gap while price counted), so it gets its own mark. "
          "Pains are then clustered into themes.", "",
          "**Limits.** Reviews come from users of existing apps: they show what is missing in what people already use, not demand from people "
          "who have no app yet. Stores bias the sample (apps ask happy users for ratings; angry users write). Startpack leans positive: vendors run "
          "review campaigns (bursts of same-day five-star reviews from new accounts), which is why B2B niches form their own cohort. RuStore is not "
          "covered, and a B2B niche without mobile apps or Startpack products is quiet here. App Store RSS serves at most 500 newest reviews per app, so "
          "for big apps the window is days or weeks, not a year. LLM labels and themes are not hand-validated.", "",
          f"**Verdict (a rule, not a score; it does not change S6):** 🟢 \"gap\" - missing features and switches in reviews of {stars} stars or lower >= "
          f"{vcfg['gap_floor']:.0%} of reviews about the app and in the top of the cohort (percentile >= {vcfg['gap_pct']:.0%}); 🟡 \"quality\" - not a gap, "
          f"but bug/UX/ads/support complaints >= {vcfg['quality_floor']:.0%} and percentile >= {vcfg['quality_pct']:.0%}; ⚪ \"unmeasured\" - not quality, "
          f"and fewer than {vcfg['min_low_reviews']} reviews of {stars} stars or lower, so the gap cannot be read (not a signal either way); "
          f"🟡 \"content\" - praise >= {vcfg['content_praise']:.0%}; 🟡 \"mixed\" - the rest; ⚪ \"quiet\" - fewer than {vcfg['min_app_reviews']} labeled "
          f"reviews about the app or fewer than {vcfg['min_apps']} apps. A separate mark, {PAYWALL}, beside any measured verdict: price complaints "
          f"in reviews of {stars} stars or lower >= {vcfg['paywall_floor']:.0%} of reviews about the app and percentile >= {vcfg['paywall_pct']:.0%}. "
          "Written reviews lean negative, so an absolute complaint threshold would pass nearly every niche; the rule compares niches with each other, "
          f"within their segment (B2C + prosumer, B2B - the sources and their biases differ). **Cohorts: {cohort_note or 'none'}.**", "",
          "## 1. Summary", "",
          f"| # | Niche | S6 | Score | Reviews verdict | Products AS / GP / SP | Reviews (substantive) | 1-2 stars | Unmet, all reviews: feature / price / switch | Gap: feature + switch in <= {stars} stars (n) | Price in <= {stars} stars | Quality | Praise | Pain theme #1 | Switch #1 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, nid in enumerate(ids, 1):
        s, c, l, v = score.get(nid, {}), per_n[nid], llm.get(nid), verdicts.get(nid)
        n_as, n_gp, n_sp = (sum(1 for r in by_app[nid] if r["store"] == st) for st in ("appstore", "gplay", "startpack"))
        low = f"{c['low'] / c['n']:.0%}" if c["n"] else "-"
        if l:
            unmet = (f"{pc(l['unmet_share'])}: {pc(l['missing_feature_share'])} / {pc(l['pricing_share'])} / {pc(l['switching_share'])} | "
                     f"**{pc(l['unmet_low_share'])}** ({l['low_reviews'] if l['low_reviews'] != '' else '-'}) | {pc(l['price_low_share'])}")
            rest = f"{pc(l['quality_share'])} | {pc(l['praise_share'])} | {l['top_theme'] or '-'} ({l['top_theme_count']}) | {l['top_switch'] or '-'}"
        else:
            unmet, rest = "- | - | -", "- | - | - | -"
        shown = (v["verdict"] + (f" · {v['paywall']}" if v["paywall"] else "")) if v else "- (no LLM labels)"
        L.append(f"| {k} | {names.get(nid, nid)} | {VERD.get(s.get('verdict'), '')} | {s.get('score', '')} | {shown} | "
                 f"{n_as} / {n_gp} / {n_sp} | {c['n']} ({c['subst']}) | {low} | {unmet} | {rest} |")
    groups = defaultdict(list)
    for nid in ids:
        if nid in verdicts:
            groups[verdicts[nid]["verdict"]].append(nid)
    by_unmet = lambda xs: sorted(xs, key=lambda x: -(f(llm[x]["unmet_low_share"], 0) or 0))  # noqa: E731
    paywalled = sorted((x for x in ids if (verdicts.get(x) or {}).get("paywall")), key=lambda x: -(f(llm[x]["price_low_share"], 0) or 0))
    L += ["", "## 2. What this says", "",
          f"- **🟢 gap ({len(groups['🟢 gap'])})**: " + (", ".join(f"{names.get(x, x)} ({pc(llm[x]['unmet_low_share'])})" for x in by_unmet(groups["🟢 gap"])) or "-")
          + ". Unhappy users of the existing apps ask for what is missing or leave more than in other niches: a concrete wedge for "
          "a new product. Read the unmet themes below before believing it.",
          f"- **{PAYWALL} ({len(paywalled)})**: " + (", ".join(f"{names.get(x, x)} ({pc(llm[x]['price_low_share'])})" for x in paywalled) or "-")
          + ". Unhappy users complain about price or the paywall more than in other niches. A mark, not a wedge by itself: hard paywalls are "
          "common in saturated clone markets (document scanners, AI songs). A cheaper or fairer model helps only if the product is not a commodity.",
          f"- **🟡 quality ({len(groups['🟡 quality'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 quality"]) or "-")
          + ". The apps do the job, but badly (crashes, clumsy UX, ads, silent support): entering means out-executing incumbents.",
          f"- **⚪ unmeasured ({len(groups['⚪ unmeasured'])})**: " + (", ".join(names.get(x, x) for x in groups["⚪ unmeasured"]) or "-")
          + f". Too few reviews of {stars} stars or lower to read a gap: a satisfied market or a positively biased source (most Startpack reviews are "
          "five-star). Read the pain themes as interview material, not as a verdict.",
          f"- **🟡 content ({len(groups['🟡 content'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 content"]) or "-") + ".",
          f"- **🟡 mixed ({len(groups['🟡 mixed'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 mixed"]) or "-") + ".",
          f"- **⚪ quiet ({len(groups['⚪ quiet'])})**: " + (", ".join(names.get(x, x) for x in groups["⚪ quiet"]) or "-")
          + ". Few reviews are not a signal against the niche: the audience may use web services, RuStore or no app at all.", "",
          "## 3. By niche", ""]
    for k, nid in enumerate(ids, 1):
        s, c, l, v, t = score.get(nid, {}), per_n[nid], llm.get(nid), verdicts.get(nid), themes.get(nid) or {}
        L += [f"### {k}. {names.get(nid, nid)} - {(v['verdict'] + (f' · {PAYWALL}' if v['paywall'] else '')) if v else 'no LLM labels'}", "",
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
                      f"\"worth the money\" {l['worth_it']}, \"want it free\" {l['wants_free']}, \"cancelled\" {l['cancelled']}. "
                      f"Rated {stars} stars or lower: {l['low_reviews'] if l['low_reviews'] != '' else '-'} reviews about the app; missing features and "
                      f"switches among them make {pc(l['unmet_low_share'])} of all reviews about the app (the gap share), price complaints "
                      f"{pc(l['price_low_share'])} (the paywall share)."]
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
    print(f"-> reports/S10-ru-reviews.md, ru_reviews_verdict.csv: {len(ids)} niches;", dict(Counter(v["verdict"] for v in verdicts.values())),
          f"{PAYWALL}: {len(paywalled)}")
