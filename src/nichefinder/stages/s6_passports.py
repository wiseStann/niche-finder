"""Niche passports: one Markdown page per niche plus a leaderboard summary.

Output: reports/passports/<niche_id>.md and reports/S6-passports.md (leaderboard, gates, cut niches).
Required inputs: niches.yaml, data/out/score_final.csv, supply_deep.csv, metrics_quick.csv.
Optional inputs (the matching passport block is skipped when a file is missing): trends_deep.csv, appstore_metrics.csv,
capterra_categories_stats.csv, shopify_metrics.csv, pricing_b2b.csv, pricing_b2c.csv, deals.csv, deals_matches.csv
(with BetaList / Product Radar / Kickstarter launches), path_to_goal.csv (s6_ceiling), entrant_survival.csv (S9),
offsearch.csv (S8, with Hacker News), reddit_voice.csv, reddit_brands.csv,
reddit_voice_llm.csv, reddit_voice_themes.json, ru_reviews_verdict.csv, ru_reviews_llm.csv, ru_reviews_themes.json (S10),
ai_substitute.csv (s5_ai_substitute); the evidence-only sources rendered by nichefinder.evidence (who_counts.csv,
switch_intent.csv, serp_ownership.csv, advertisers.csv, ecosystems_metrics.csv, oss_substitutes.csv, wayback.csv, freelance.csv,
yt_comments_voice.csv, tg_voice.csv, vk_audience.csv, the TrustMRR columns of deals.csv);
config/overrides.yaml (notes, lens, manual supply estimates).
"""
from __future__ import annotations

import argparse
import csv
import json
import os

from nichefinder import niches as nf_niches
from nichefinder.evidence import Evidence
from nichefinder.workspace import Workspace

SUMMARY = "Per-niche passports (Markdown) and the leaderboard summary"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

V = {"green": "🟢 green", "yellow": "🟡 yellow", "red": "🔴 red"}


def n(v, fmt="{:,.0f}", dash="—"):
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return dash


def p(v):
    return n(v, "{:.0%}")


def _rows(path, key):
    if not os.path.exists(path):
        return {}
    return {r[key]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def _group(path, key):
    d = {}
    if os.path.exists(path):
        for r in csv.DictReader(open(path, encoding="utf-8")):
            d.setdefault(r[key], []).append(r)
    return d


def _reddit_verdict():
    """The S10 verdict rule, when that stage module is available."""
    try:
        from nichefinder.stages.s10_reddit_report import reddit_verdict
        return reddit_verdict
    except ImportError:
        return None


def run(ws: Workspace, args: argparse.Namespace) -> None:
    out = lambda name: str(ws.out(name))  # noqa: E731
    niches = {x["id"]: x for x in nf_niches.load_niches(ws)}
    manual = nf_niches.overrides(ws)
    for need in ("score_final.csv", "supply_deep.csv", "metrics_quick.csv"):
        if not os.path.exists(out(need)):
            raise SystemExit(f"{out(need)} not found - run the earlier stages (s6_score needs S3 and S5) first")
    supply = _rows(out("supply_deep.csv"), "niche_id")
    score = _rows(out("score_final.csv"), "niche_id")
    quick = _rows(out("metrics_quick.csv"), "id")
    trends = {}
    tbrands = {}   # brand anchors (kind=brand): shown as a cross-check, the verdict comes from supply_deep (s5_merge)
    tp = out("trends_deep.csv")
    if os.path.exists(tp):
        for r in csv.DictReader(open(tp, encoding="utf-8")):
            if r["kind"] == "brand":
                if r.get("status") == "ok" and r.get("verdict") not in ("NA", ""):
                    tbrands.setdefault((r["niche_id"], r["lang"]), []).append(f"{r['anchor']} {n(r.get('mean_2022'), '{:.0f}')}→{n(r.get('mean_2024'), '{:.0f}')} {r['verdict']}")
                continue
            k = (r["niche_id"], r["lang"])
            cur = trends.get(k)
            if cur is None or (cur.get("verdict") in ("NA", "") and r.get("verdict") not in ("NA", "")):
                trends[k] = r
    apps = {}
    if os.path.exists(out("appstore_metrics.csv")):
        for r in csv.DictReader(open(out("appstore_metrics.csv"), encoding="utf-8")):
            apps[(r["niche_id"], r["store"])] = r
    cap = _group(out("capterra_categories_stats.csv"), "niche_id")
    shop = _group(out("shopify_metrics.csv"), "niche_id")
    pb2b = {}
    if os.path.exists(out("pricing_b2b.csv")):
        for r in csv.DictReader(open(out("pricing_b2b.csv"), encoding="utf-8")):
            pb2b.setdefault(r["niche_id"], {}).setdefault(r["product"], r)
    pb2c = _group(out("pricing_b2c.csv"), "niche_id")
    deals = _rows(out("deals.csv"), "niche_id")
    ptg = _rows(out("path_to_goal.csv"), "niche_id")
    ent = _rows(out("entrant_survival.csv"), "niche_id")
    dm = {}
    if os.path.exists(out("deals_matches.csv")):
        for r in csv.DictReader(open(out("deals_matches.csv"), encoding="utf-8")):
            dm.setdefault((r["niche_id"], r["source"]), []).append(r)
    off = _rows(out("offsearch.csv"), "niche_id")
    # S10 buyer voice (Reddit): metrics, brand share of voice, pain themes (LLM)
    rv = _rows(out("reddit_voice.csv"), "niche_id")
    rb = _group(out("reddit_brands.csv"), "niche_id")
    rl = _rows(out("reddit_voice_llm.csv"), "niche_id")
    rt = json.load(open(out("reddit_voice_themes.json"), encoding="utf-8")) if os.path.exists(out("reddit_voice_themes.json")) else {}
    reddit_verdict = _reddit_verdict()
    # S10 buyer voice in Russian: app-review verdict (s10_ru_reviews_report), shares and pain themes (s10_ru_reviews_classify)
    ais = _rows(out("ai_substitute.csv"), "niche_id")   # S5 AI substitute probe (s5_ai_substitute)
    qv = _rows(out("ru_reviews_verdict.csv"), "niche_id")
    ql = _rows(out("ru_reviews_llm.csv"), "niche_id")
    qt = json.load(open(out("ru_reviews_themes.json"), encoding="utf-8")) if os.path.exists(out("ru_reviews_themes.json")) else {}
    ev = Evidence(ws)   # evidence-only sources: who counts, switching intent, SERP, ecosystems, OSS, Wayback, freelance, YouTube
    pdir = ws.report("passports")
    pdir.mkdir(parents=True, exist_ok=True)

    ordered = sorted(score.values(), key=lambda s: ({"green": 0, "yellow": 1, "red": 2}[s["verdict"]], -float(s["score"])))
    for s in ordered:
        nid = s["niche_id"]
        x, m, sp, q = niches[nid], manual.get(nid) or {}, supply[nid], quick[nid]
        t = trends.get((nid, "en"), {})
        a = apps.get((nid, "us"), {})
        cl = cap.get(nid, [])
        d = deals.get(nid, {})
        L = [f"# {x['name']}", "",
             f"`{nid}` · {x['side']} · geo {x['geo']} · tier {s['tier']} · **{V[s['verdict']]}** · score {s['score']}",
             "", f"**Who:** {x['who']}  ", f"**Task:** {x['task']}  ", f"**Product:** {x['product']}  ",
             f"**S0 sources:** {', '.join(x.get('sources', []))} — {x.get('evidence', '')}", ""]
        if s["gates_failed"] or s["flags"]:
            L.append(f"**Gates:** {s['gates_failed'] or 'all passed'} · **Flags:** {s['flags'] or '—'}")
            L.append("")
        L.append(f"> **Verdict.** {s.get('verdict_note') or m.get('verdict_note', '')}")
        L.append("")
        # demand
        L += ["## Demand (Google Keyword Planner, US, category queries)", "",
              "| Demand/month (last 12) | Demand 2023 (clean) | CPC | 2024/2023 | last 12 / prior 12 | KP verdict | S3 flags |",
              "|---|---|---|---|---|---|---|",
              f"| {n(sp['demand_us'])} | {n(sp['demand_2023'])} | ${n(sp['cpc'], '{:.2f}')} | {n(sp['yoy_pre'], '{:+.0%}')} | {n(sp['yoy'], '{:+.0%}')} | {sp['trend_kp']} | {sp['gates_s3'] or '—'} |", ""]
        if t or (nid, "en") in tbrands:
            L += [f"Google Trends 2021–24 (anchor \"{t.get('anchor', '')}\", US): mean index 2021→2024 = {n(t.get('mean_2021'), '{:.0f}')} → {n(t.get('mean_2022'), '{:.0f}')} → {n(t.get('mean_2023'), '{:.0f}')} → {n(t.get('mean_2024'), '{:.0f}')}; verdict **{t.get('verdict', 'NA')}**"
                  + (f"; brand cross-check: {'; '.join(tbrands[(nid, 'en')])} → **{sp.get('trend_gt')}**" if (nid, 'en') in tbrands and sp.get('trend_gt') != t.get('verdict', 'NA') else "")
                  + (" (signal too weak for a B2B query)" if t.get("verdict") == "NA" else "") + ".", ""]
        L += [f"Brand queries: top-1 brand **{sp['brand_top1']}** = {p(sp['brand_top1_share'])} of brand demand (HHI {n(sp['hhi_brand'], '{:.2f}')}); competition_index {n(sp['comp_idx'])}.", ""]
        L += ev.serp_lines(nid)
        L += ev.ads_lines(nid)
        # supply
        L += ["## Supply (independent of search)", ""]
        if a and a.get("na") != "1":
            L += [f"**App Store US** (iTunes Search, relevant set after manual cleaning - `config/appstore_relevance.yaml`): {a['apps']} apps, "
                  f"**{a['players_1k']} with ≥ 1k ratings**, {a['players_10k']} with ≥ 10k; top-1 by ratings **{a['top1']}** = {p(a['top1_share'])}, top-3 = {p(a['top3_share'])}, HHI {n(a['hhi'], '{:.2f}')}; "
                  f"new in 12 months: {a['new_12m']} (of which already ≥ 1k ratings: {a['new_12m_1k']}); free apps in the top 20: {p(a['free_share_top20'])}; largest developer {a['top_seller']} - {p(a['top_seller_share'])} of ratings.", "",
                  f"Top 5: {a['top5']}", ""]
        elif a and a.get("na") == "1":
            L += ["App Store: not a sales channel for this niche (web product) - iTunes results are irrelevant, metrics were not computed.", ""]
        for c in cl:
            L += [f"**Capterra `{c['slug']}`**: {c['products_total']} products in the category, {c['products_10plus']} with ≥ 10 reviews, **{c['products_100plus']} with ≥ 100**; "
                  f"excluding horizontal substitutes top-1 **{c['top1']}** = {p(c['top1_share'])} of reviews, top-3 = {p(c['top3_share'])}, HHI {n(c['hhi'], '{:.2f}')}"
                  + (f"; horizontal substitutes in the category: {c['generic_present']}" if c['generic_present'] else "") + (f". _{c['note']}_" if c['note'] else "."), ""]
        for c in shop.get(nid, []):
            L += [f"**Shopify App Store `{c['category']}`**{' (primary)' if c['primary'] == '1' else ''}: {c['apps']} apps in the subcategory (crawled, excluding horizontal apps - `config/shopify_generic.yaml`), "
                  f"**{c['players_100']} with ≥ 100 reviews**, {c['players_1k']} with ≥ 1k; top-1 by reviews **{c['top1']}** = {p(c['top1_share'])}, top-3 = {p(c['top3_share'])}, HHI {n(c['hhi'], '{:.2f}')}; with a free plan/install - {p(c['free_share'])}. Top 3: {c['top3']}.", ""]
        L += ev.supply_lines(nid)
        if m.get("supply_manual"):
            L += [f"**Manual supply estimate** (no proxy category): {m['supply_manual']}", ""]
        L += [f"S5 gate (top-1 ≤ 50% and ≥ 8 players by an independent signal): **{s['gate_s5']}**." + (" \"Second platform\" rule: the iOS leader holds > 50%, but the Google Play US leader holds ≤ 50% with ≥ 8 players above 100k installs - the market is not a monopoly, entry through Android (see \"Demand outside search\")." if s['gate_s5'] == 'PASS:android' else ''), ""]
        e = ent.get(nid)
        if e and int(e["cohort_12_24m"] or 0) > 0:   # new-entrant survival (s9_entrants)
            L += [f"**New-entrant survival, App Store US** (released 12–24 months ago: {e['cohort_12_24m']}): updated within 180 days - {float(e['upd_180d']):.0%}, within 90 - {float(e['upd_90d']):.0%}; reached ≥ 1k ratings - {float(e['share_1k']):.0%}" + (f" → **{e['flag']}**" if e['flag'] else '') + ". (E:churn - newcomers die, a sign of a wrapper factory; E:traction - newcomers get traction, the market is open.)", ""]
        # pricing
        L += ["## Pricing and switching", ""]
        if nid in pb2b:
            ps = list(pb2b[nid].values())
            L += ["| Product | Reviews (Capterra) | Starting price | Period | Free trial | Free version |", "|---|---|---|---|---|---|"]
            for r in sorted(ps, key=lambda r: -int(r["reviews"]))[:8]:
                L.append(f"| {r['product']} | {r['reviews']} | {('$' + r['price']) if r['price'] not in ('', 'None') else '—'} | {r['period'] or '—'} {r['model']} | {'yes' if r['free_trial']=='1' else ('no' if r['free_trial']=='0' else '—')} | {'yes' if r['free_version']=='1' else ('no' if r['free_version']=='0' else '—')} |")
            L += ["", f"Median starting price **${n(sp['b2b_median_monthly'])}/month**, {p(sp['b2b_price_public'])} of products publish a price, plans under $100/month - {p(sp['b2b_under100'])}, free trial at {p(sp['b2b_trial'])}, free version at {p(sp['b2b_free'])} (GetApp).", ""]
        if nid in pb2c:
            L += ["| App | Ratings | IAP | Monthly | Yearly | Weekly | Lifetime | IAP examples |", "|---|---|---|---|---|---|---|---|"]
            for r in pb2c[nid]:
                L.append(f"| {r['name']} | {n(r['ratings'])} | {'yes' if r['has_iap']=='1' else 'no'} | {('$'+r['min_monthly']) if r['min_monthly'] else '—'} | {('$'+r['min_yearly']) if r['min_yearly'] else '—'} | {('$'+r['min_weekly']) if r['min_weekly'] else '—'} | {('$'+r['min_lifetime']) if r['min_lifetime'] else '—'} | {r['iap_sample'][:70]} |")
            L += ["", f"{p(sp['b2c_monetized'])} of the top 8 are monetized; median monthly subscription **${n(sp['b2c_median_monthly'], '{:.2f}')}**, yearly ${n(sp['b2c_median_yearly'], '{:.2f}')}.", ""]
        L += [f"Lock-in (manual): {m.get('lock_in', '—')} of 2. Platform risk: **{m.get('platform_risk', '—')}** - {m.get('platform_note', '') or 'none'}.", ""]
        L += ev.switch_lines(nid)
        ai = ais.get(nid)
        if ai and ai.get("covers") not in ("", None):
            L += [f"AI substitute (LLM probe, evidence for the manual platform risk, not a gate): a free chatbot covers the job **{ai['covers']} of 2** (votes over buyer requests: {ai.get('votes') or '-'}) - {ai['reason']}"
                  + (f" Still needs a product for: {ai['missing']}." if ai.get("missing") else "")
                  + (f" Brands the chatbot recommends: {ai['brands']}." if ai.get("brands") else "")
                  + (f" **{ai['check']}.**" if ai.get("check") else "") + " Method: `S5-ai-substitute.md`.", ""]
        # deals
        if d:
            L += ["## Deals, launches, monetization (S0 corpora)", "",
                  f"Product Hunt (12-month tops): {d.get('ph_launches_12m', 0)} · Y Combinator: {d.get('yc_companies', 0)} · TinySeed: {d.get('tinyseed', 0)} · "
                  f"App Store top-grossing: US {d.get('topgrossing_us', 0)}, RU {d.get('topgrossing_ru', 0)}.", ""]
            if d.get("ef_software") not in (None, "", "0"):
                L += [f"Empire Flippers, software businesses with a verified P&L, all years (not in the score): {d['ef_software']} listings, "
                      f"{d.get('ef_software_sold') or 0} sold, median net profit ${n(d.get('ef_median_profit'))}/month, "
                      f"median price {d.get('ef_median_multiple') or '—'}x monthly profit.", ""]
            if any(d.get(k) not in (None, "") for k in ("betalist_12m", "productradar_12m", "kickstarter_12m")):
                L += [f"Launches of the last 12 months (not in the score): BetaList pre-launch {d.get('betalist_12m') or 0} · Product Radar (RU) {d.get('productradar_12m') or 0} · "
                      f"Kickstarter {d.get('kickstarter_12m') or 0} launched, {d.get('kickstarter_success_12m') or 0} funded, ${n(d.get('kickstarter_pledged_12m') or 0)} pledged.", ""]
            L += ev.trustmrr_line(nid)
            ex = [f"{r['source']}: {r['name']}" for src in ("ph", "yc", "tinyseed") for r in dm.get((nid, src), [])][:8]
            ex += [f"ef: {r['name']} ({r['extra']})" for r in dm.get((nid, "ef"), [])][:3]
            ex += [f"{r['source']}: {r['name']}" for src in ("betalist", "productradar") for r in dm.get((nid, src), [])][:4]
            ex += [f"kickstarter: {r['name']} ({r['extra']})" for r in dm.get((nid, "kickstarter"), [])][:3]
            if ex:
                L += ["Examples: " + "; ".join(ex), ""]
        # demand outside search (S8)
        o = off.get(nid)
        if o:
            g = lambda k, fmt="{:,.0f}": (fmt.format(float(o[k])) if o.get(k) not in ("", None) else "—")  # noqa: E731
            L += ["## Demand outside search (S8)", "",
                  f"- **YouTube** (Google Trends, YouTube search, US, topic \"{o['yt_topic']}\"): level {g('yt_level', '{:.2f}')} of the reference topic \"budgeting\" (= 1.0), 2024 vs 2022 {g('yt_r_24_22', '{:+.0%}')} → **{o['yt_verdict']}**"
                  + (" (topic is not searched on YouTube - usually B2B)" if o["yt_verdict"] == "NA" else "") + ".",
                  f"- **Reddit** (subreddit statistics snapshot): r/{o['reddit_primary']} - {g('reddit_primary_subs')} subscribers; sum over the niche's subreddits {g('reddit_sum_subs')}.",
                  f"- **App Store US, rating velocity:** {g('as_us_vel_pm')} ratings/month across relevant apps; released within 24 months - {g('as_us_new24')}, gaining {g('as_us_new24_pm')} ratings/month ({g('as_us_new_share', '{:.0%}')} of the niche's velocity)"
                  + (f"; fastest newcomer - {o['as_us_fastest_new']} ({g('as_us_fastest_new_pm')}/month)" if o.get("as_us_fastest_new") else "") + "."
                  + (f" RU: {g('as_ru_vel_pm')} ratings/month, new within 24 months {g('as_ru_new24')} ({g('as_ru_new24_pm')}/month)." if o.get("as_ru_vel_pm") else ""),
                  f"- **Google Play** (category-query search + app pages; installs are global): US storefront - {g('gp_us_apps')} relevant apps, {g('gp_us_installs')} installs in total, {g('gp_us_players_100k')} with ≥ 100k and {g('gp_us_players_1m')} with ≥ 1M; install leader {o['gp_us_top1'] or '—'} = {g('gp_us_top1_share', '{:.0%}')}; new within 24 months {g('gp_us_new24')} ({g('gp_us_new24_installs')} installs)."
                  + (f" RU storefront: {g('gp_ru_apps')} apps, {g('gp_ru_installs')} installs, {g('gp_ru_players_100k')} with ≥ 100k, leader {o['gp_ru_top1'] or '—'} = {g('gp_ru_top1_share', '{:.0%}')}, new {g('gp_ru_new24')}." if o.get("gp_ru_apps") else ""),
                  ]
            if o.get("hh_vacancies"):
                L.append(f"- **hh.ru** (Russian job postings mentioning the niche's software brands - an adoption proxy): {g('hh_vacancies')}, leader \"{o['hh_top_brand']}\" - {g('hh_top_vacancies')}.")
            if o.get("hn_posts_12m") not in (None, ""):
                L.append(f"- **Hacker News** (Show HN + Ask HN posts whose titles match the niche, last 12 months vs the 12 before): {g('hn_posts_12m')} vs {g('hn_posts_prev12m')} → **{o.get('hn_trend') or 'NA'}**"
                         + (" (a search term hit the 1,000 cap: a lower bound)" if o.get("hn_capped") == "1" else "")
                         + f"; Show HN launches {g('hn_show_12m')} ({g('hn_show_prev12m')} the year before), Ask HN questions {g('hn_ask_12m')}."
                         + (f" Top Show HN: {o['hn_top_show']}." if o.get("hn_top_show") else "") + (f" Top Ask HN: {o['hn_top_ask']}." if o.get("hn_top_ask") else ""))
            if o.get("hn_hiring_12m") not in (None, ""):
                L.append(f"- **HN \"Who is hiring?\"** (startup job postings that match the niche): {g('hn_hiring_12m')} in the last 12 months, {g('hn_hiring_prev12m')} the year before"
                         + (f"; recent companies: {o['hn_hiring_companies']}" if o.get("hn_hiring_companies") else "") + ".")
            L += ev.freelance_line(nid)
            L += [f"- Flags: {o['offsearch_flags'] or '—'}", ""]
        v = rv.get(nid)
        if v:
            gi = lambda k: (f"{int(float(v[k])):,}" if v.get(k) not in ("", None) else "—")  # noqa: E731
            if reddit_verdict:
                rverd, rwhy = reddit_verdict(v, rl.get(nid))
                head = f"**Reddit verdict: {rverd}** - {rwhy}. "
            else:
                head = ""
            L += ["## Buyer voice (Reddit, S10)", "",
                  head + f"Source: Arctic Shift archive, subreddits {', '.join('r/' + x for x in v['subs'].split('|'))}; posts ({gi('posts')}), comments ({gi('comments')}: last 12 months in the niche's own subreddits + threads under matched posts of large ones); "
                  f"large subreddits - only posts matching brands/phrases (`config/reddit_terms.yaml`). Post trend in the niche's own subreddits: 2024/2022 = {v['r_24_22'] or '—'}, last 12 months vs prior {(('{:+.0%}'.format(float(v['yoy']))) if v.get('yoy') else '—')} → **{v['verdict']}** "
                  f"({gi('posts_last12')} vs {gi('posts_prev12')}). The verdict rule and the full analysis are in `S10-reddit-voice.md`.", "",
                  f"- **Markers** (share of documents): asking for a recommendation {float(v['seek_share']):.0%}, complaining {float(v['complain_share']):.0%}, switching {float(v['switch_share']):.0%}, talking price {float(v['price_share']):.0%}.",
                  f"- **Brand share of voice** ({gi('brand_mentions')} mentions, {v['brands_10plus']} brands with ≥ 10): {v['brand_top3'] or '—'}; HHI {v['brand_hhi']}."]
            trend_b = [r for r in rb.get(nid, []) if r.get("trend") not in ("", None)]
            if trend_b:
                up = [r for r in sorted(trend_b, key=lambda r: -float(r["trend"])) if float(r["trend"]) > 0][:3]
                dn = [r for r in sorted(trend_b, key=lambda r: float(r["trend"])) if float(r["trend"]) < 0][:3]
                L.append("- **Who is rising in conversations** (last 12 months vs prior 12, brands with ≥ 10 mentions): " + (", ".join(f"{r['brand']} {float(r['trend']):+.0%}" for r in up) or "nobody")
                         + "; falling: " + (", ".join(f"{r['brand']} {float(r['trend']):+.0%}" for r in dn) or "nobody") + ".")
            l = rl.get(nid)
            t10 = rt.get(nid) or {}
            if l:
                L.append(f"- **LLM classification** ({l['classified']} documents): asking for a recommendation {float(l['seek_share']):.0%}, complaints {float(l['complaint_share']):.0%}, switching {float(l['switching_share']):.0%}, pricing {float(l['pricing_share']):.0%}, praise {float(l['praise_share']):.0%}; "
                         f"\"too expensive\" {l['too_expensive']}, \"worth it\" {l['worth_it']}, \"want it free\" {l['wants_free']}, \"cancelled subscription\" {l['cancelled']}.")
            if t10.get("themes"):
                L += ["", "**Pain themes and unmet needs** (LLM clustering, by frequency):", ""]
                for th in t10["themes"][:10]:
                    qs = "; ".join(f"\"{q[:140]}\"" for q in (th.get("quotes") or [])[:2])
                    L.append(f"- **{th.get('theme', '')}** ({th.get('count', '')}) - {th.get('description', '')}" + (f" Quotes: {qs}" if qs else ""))
            sw = [(k, c) for k, c in (t10.get("switching") or []) if "?" not in k and len(set(y.strip() for y in k.split("->"))) == 2]
            if sw:
                L += ["", "Switches \"from → to\": " + "; ".join(f"{k} ({c})" for k, c in sw[:8]) + "."]
            L.append("")
        qr = qv.get(nid)
        if qr:
            qrl, qrt = ql.get(nid) or {}, qt.get(nid) or {}
            qp = lambda k: f"{float(qrl[k]):.0%}" if qrl.get(k) not in ("", None) else "—"  # noqa: E731
            L += ["## Buyer voice (Russian reviews, S10)", "",
                  f"**Reviews verdict: {qr['verdict']}** - {qr['reason']}." + (" _The thresholds are a draft (`config/ru_reviews.yaml`)._" if qr.get("status") != "fixed" else "")
                  + " Source: Russian App Store, Google Play and Startpack reviews of the niche's leading products; the rule and the per-product tables are in `S10-ru-reviews.md`.", ""]
            if qrl:
                L.append(f"- **LLM labels** ({qrl['classified']} reviews, {qrl['about_app']} about the app): unmet needs {qp('unmet_share')} (missing feature {qp('missing_feature_share')}, "
                         f"price {qp('pricing_share')}, switching {qp('switching_share')}), quality complaints {qp('quality_share')} (bugs, UX, ads, support), praise {qp('praise_share')}."
                         + (f" Gap share (missing features and switches in low-rated reviews, of all reviews about the app): "
                            f"{float(qr['unmet_low_share']):.0%}, from {qr.get('low_reviews') or 0} low-rated reviews"
                            + (f"; price complaints in them: {float(qr['price_low_share']):.0%}" if qr.get("price_low_share") not in ("", None) else "")
                            + "." if qr.get("unmet_low_share") not in ("", None) else ""))
            if qrt.get("themes"):
                L += ["", "**Pain themes in Russian reviews** (LLM clustering, by frequency):", ""]
                for th in qrt["themes"][:8]:
                    qs = "; ".join(f"\"{str(q)[:140]}\"" for q in (th.get("quotes") or [])[:2])
                    L.append(f"- **{th.get('theme', '')}** [{th.get('kind', '')}] ({th.get('count', '')}) - {th.get('description', '')}" + (f" Quotes: {qs}" if qs else ""))
            qsw = [(k, c) for k, c in (qrt.get("switching") or []) if "?" not in k]
            if qsw:
                L += ["", "Switches \"from → to\": " + "; ".join(f"{k} ({c})" for k, c in qsw[:8]) + "."]
            L.append("")
        L += ev.yt_lines(nid)
        L += ev.tg_lines(nid)
        L += ev.vk_lines(nid)
        # feasibility and lens
        fe = m.get("feas") or {}
        L += ["## Feasibility for a small team", "",
              f"Feasibility **{s['feasibility'] or '—'}/4**: indie_exists={fe.get('indie_exists', '—')}, stack_commodity={fe.get('stack_commodity', '—')}, no_regulated_data={fe.get('no_regulated_data', '—')}, self_serve={fe.get('self_serve', '—')}. {m.get('feas_note', '')}", ""]
        if m.get("lens"):
            L += [f"**Fad or business:** {m['lens']}", ""]
        L += ev.who_lines(nid, ptg.get(nid))
        # path to goal
        pg = ptg.get(nid)
        if pg:
            sh = lambda v: f"{float(v):.0%}" if v not in ("", None) else "—"  # noqa: E731
            L += ["## Path to goal", "",
                  f"Grade **{pg['grade']}** (A - the goal is reachable without winning the niche, at a ticket ≥ $50 and fit ≥ 2; B - reachable as a top-3 player at a ticket ≥ $50 or fit ≥ 2; B- - top-3 but ticket < $50 and fit < 2; C - requires leading the niche or lies outside the team's competence).",
                  "",
                  f"- Competitor price **${float(pg['price_month']):.0f}/month** ({pg['price_src']}) → ARPU after fees ≈ ${float(pg['arpu_net']):.1f}; ticket tier **{pg['ticket_tier']}**.",
                  f"- Payers needed for the low goal: **{format(int(pg['payers_low']), ',')}**, for the high goal: {format(int(pg['payers_high']), ',')}.",
                  f"- Payers in the niche (estimate): **{(format(int(float(pg['niche_payers_est'])), ',')) if pg['niche_payers_est'] else '—'}** ({pg['size_proxy'] or 'no proxy'}). Share of the niche for the low / high goal: **{sh(pg['share_low'])} / {sh(pg['share_high'])}** → position **{pg['position_low']} / {pg['position_high']}**." + (f" {pg['notes']}." if pg['notes'] else ""),
                  f"- Founder fit **{pg['founder_fit']}/3**" + (f" - {pg['founder_fit_why']}" if pg['founder_fit_why'] else "") + "."]
            if pg.get("ru_verdict"):
                L.append(f"- Russian-market branch verdict: {pg['ru_verdict']}.")
            L += ["", "_Assumptions - `config/ceiling.yaml`; order of magnitude, read shares as ±2×._", ""]
        # score
        L += ["## Score", "", f"Total **{s['score']}** = demand {s['s_demand']}/30 + growth {s['s_growth']}/20 + fragmentation {s['s_frag']}/25 + deals {s['s_deals']}/15 + switching {s['s_switch']}/10, × trend (KP {s['trend_kp']}, Trends {s['trend_gt']}).", "",
              "_Data: DataForSEO (Google Ads), Google Trends, iTunes Search API, Capterra/GetApp, Shopify App Store, Product Hunt/YC/TinySeed/Empire Flippers (S0). Manual judgments - `config/overrides.yaml`._", ""]
        open(ws.report(f"passports/{nid}.md"), "w", encoding="utf-8").write("\n".join(L))

    # summary
    S = ["# S6: niche passports - summary", "",
         f"Full score (0–100) over a cohort of {len(ordered)} niches: demand 30 + growth 20 + fragmentation 25 + deals 15 + switching 10, × trend. "
         "Gates: S5 (independent concentration), G3 (platform), G5 (feasibility ≥ 2). Verdict: red when a gate fails; otherwise green at the nf.yaml `verdict.green_min_score` or above, else yellow; a manual verdict in `config/overrides.yaml` replaces green/yellow. "
         "One passport per niche - `passports/<id>.md`.", "",
         "| # | Niche | Tier | Verdict | Score | Demand/mo | CPC | KP | Trends | Supply: players / top-1 | Gates / flags |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, s in enumerate(ordered, 1):
        if "S5:manual" in s["flags"]:
            sup = "manual estimate (see passport)"
        elif s["supply_src"] != "na" and s["gate_s5"] != "NA":   # NA here = unmeasured, the proxy numbers are not supply
            sup = f"{s['supply_src']}: {n(s['supply_players'])} / {p(s['supply_top1_share'])} {s['supply_top1'][:22]}"
        else:
            sup = "not measured"
        S.append(f"| {k} | [{s['niche_id']}](passports/{s['niche_id']}.md) | {s['tier']} | {V[s['verdict']]} | {s['score']} | {n(s['demand_us'])} | ${n(s['cpc'], '{:.0f}')} | {s['trend_kp']} | {s['trend_gt']} | {sup} | {s['gates_failed'] or ''} {s['flags']} |")
    open(ws.report("S6-passports.md"), "w", encoding="utf-8").write("\n".join(S) + "\n")
    print("-> reports/passports/", len(ordered), "+ reports/S6-passports.md")
