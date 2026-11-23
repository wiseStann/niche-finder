"""Passport blocks and leaderboard tags for the evidence-only sources (never in the score, never a gate).

One place reads their outputs, so s6_passports and s7_html stay small and show the same numbers:
  who_counts.csv (s8_who_counts; Russian part from ru_msp_counts), switch_intent.csv (s3_switch_intent),
  serp_ownership.csv (s5_serp), advertisers.csv (s5_advertisers), ecosystems_metrics.csv (s5_ecosystems),
  oss_substitutes.csv (s5_oss),
  wayback.csv (s9_wayback), freelance.csv (s8_freelance), yt_comments_voice.csv (s10_yt_comments_report),
  tg_voice.csv (s10_tg_report), vk_audience.csv (s8_vk_audience),
  deals.csv TrustMRR columns (s0_trustmrr via s5_deals).
Every file is optional: a missing file means its block is skipped.
"""
from __future__ import annotations

import csv
from pathlib import Path

from nichefinder.workspace import Workspace


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _n(v, fmt="{:,.0f}", dash="—"):
    x = _f(v)
    return fmt.format(x) if x is not None else dash


def _rows(path: Path, key: str = "niche_id") -> dict[str, dict]:
    if not path.is_file():
        return {}
    return {r[key]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def _group(path: Path, key: str = "niche_id") -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if path.is_file():
        for r in csv.DictReader(open(path, encoding="utf-8")):
            out.setdefault(r[key], []).append(r)
    return out


class Evidence:
    def __init__(self, ws: Workspace):
        o = ws.out
        self.who = _rows(o("who_counts.csv"))
        self.switch = _group(o("switch_intent.csv"))
        self.serp = _rows(o("serp_ownership.csv"))
        self.ads = _rows(o("advertisers.csv"))
        self.eco = _group(o("ecosystems_metrics.csv"))
        self.oss = _rows(o("oss_substitutes.csv"))
        self.wb = _rows(o("wayback.csv"))
        self.free = _rows(o("freelance.csv"))
        self.yt = _rows(o("yt_comments_voice.csv"))
        self.tg = _rows(o("tg_voice.csv"))
        self.vk = _rows(o("vk_audience.csv"))
        self.deals = _rows(o("deals.csv"))
        self.tmrr = {k: [r for r in v if r.get("source") == "trustmrr"] for k, v in _group(o("deals_matches.csv")).items()}

    # ---- who: how many buyers exist -------------------------------------------------
    def who_lines(self, nid: str, pg: dict | None = None) -> list[str]:
        w = self.who.get(nid)
        if not w:
            return []
        L = ["## Who: how many target businesses exist (registers)", ""]
        if w.get("us_est"):
            L.append(f"- **US** (Census County Business Patterns {w.get('us_year', '')}, NAICS {w['naics']}): "
                     f"**{_n(w['us_est'])} establishments with employees**"
                     + (f", {_n(w['us_est_yoy'], '{:+.1%}')} vs {w.get('us_prev_year', '')}" if w.get("us_est_yoy") else "")
                     + (f"; {_n(w['us_lt20_share'], '{:.0%}')} have under 20 employees" if w.get("us_lt20_share") else "")
                     + (f"; plus {_n(w['us_nonemp'])} firms without employees (Nonemployer Statistics {w.get('nonemp_year', '')})"
                        if w.get("us_nonemp") else "") + ".")
        if w.get("ru_msp"):
            L.append(f"- **Russia** (FNS register of small and medium businesses, main OKVED {w['okved']}): **{_n(w['ru_msp'])} businesses**"
                     + (f", {_n(w['ru_msp_yoy'], '{:+.1%}')} in 12 months" if w.get("ru_msp_yoy") else "")
                     + (f"; individual entrepreneurs {_n(w['ru_ip_share'], '{:.0%}')}" if w.get("ru_ip_share") else "")
                     + ". The self-employed (NPD) are not in the register.")
        base = _f(w.get("us_est"))
        if pg and pg.get("payers_low") and base:
            need = _f(pg["payers_low"])
            L.append(f"- Payers needed for the low goal ({_n(need)}) = **{need / base:.1%} of US establishments**"
                     + (f"; for the high goal {_f(pg['payers_high']) / base:.0%}" if _f(pg.get("payers_high")) else "")
                     + ". Read it as the penetration of the whole industry the goal requires.")
        if w.get("note"):
            L.append(f"- _Codes and limits: {w['note']}._")
        if w.get("missing"):
            L.append(f"- _NAICS codes not found in CBP: {w['missing']}._")
        return L + [""]

    # ---- switching intent in search ------------------------------------------------
    def switch_lines(self, nid: str) -> list[str]:
        rows = self.switch.get(nid) or []
        parts = []
        for r in rows:
            if not _f(r.get("brand_volume")) and not _f(r.get("alt_volume")):
                continue
            pool = {"us": "US", "ru": "Russian-language"}.get(r["pool"], r["pool"])
            parts.append(f"{pool}: \"alternative to <brand>\" {_n(r['alt_volume'])}/month = {_n(r['alt_ratio'], '{:.1%}')} of brand demand"
                         + (f" (percentile {_n(r['alt_ratio_pct'], '{:.0%}')} in the cohort)" if r.get("alt_ratio_pct") else "")
                         + (f", {_n(r['alt_yoy'], '{:+.0%}')} year on year" if r.get("alt_yoy") else "")
                         + (f"; most wanted way out of **{r['top_alt_brand']}** ({_n(r['top_alt_share'], '{:.0%}')})" if r.get("top_alt_brand") else "")
                         + (f"; \"cancel <brand>\" {_n(r['churn_volume'])}/month ({_n(r['churn_ratio'], '{:.1%}')})" if _f(r.get("churn_volume")) else ""))
        if not parts:
            return []
        return [f"Switching intent in search (s3_switch_intent, evidence): " + "; ".join(parts) + ".", ""]

    # ---- SERP ownership --------------------------------------------------------------
    def serp_lines(self, nid: str) -> list[str]:
        s = self.serp.get(nid)
        if not s:
            return []
        return ["## Who owns the search page (s5_serp, evidence)", "",
                f"Google US top 10 for {s['queries']} category queries: review directories {_n(s['directory_share'], '{:.0%}')}, "
                f"media listicles {_n(s['media_share'], '{:.0%}')}, stores {_n(s['store_share'], '{:.0%}')}, forums and video {_n(s['ugc_share'], '{:.0%}')}, "
                f"the niche's brands {_n(s['brand_share'], '{:.0%}')}, other sites {_n(s['other_share'], '{:.0%}')}; brands in the top 3: "
                f"{_n(s['top3_brand_avg'], '{:.1f}')} of 3 on average. AI Overview on {_n(s['ai_overview_share'], '{:.0%}')} of the queries; "
                f"keyword difficulty {_n(s['kd_mean'], '{:.0f}')}/100. Top domains: {s.get('top_domains') or '—'}."
                + (f" **{s['flags']}**." if s.get("flags") else ""), ""]

    # ---- who pays for traffic (acquisition cost evidence) ------------------------------
    def ads_lines(self, nid: str) -> list[str]:
        a = self.ads.get(nid)
        if not a or a.get("checked") in (None, "", "0"):
            return []
        return [f"**Who pays for traffic** (Google Ads Transparency, US, s5_advertisers): {a['advertisers_now']} of {a['checked']} competitor sites "
                f"advertise now; {a['long_runner_advertisers']} keep an ad running for 90+ days"
                + (f" (longest {a['longest_active_days']} days)" if a.get("longest_active_days") else "")
                + (f"; text ads (Search) {_n(a.get('text_share'), '{:.0%}')} of the running ones" if a.get("text_share") else "")
                + (f"; biggest advertiser {a['top_advertiser']}" if a.get("top_advertiser") else "")
                + (f". **{a['flags']}**" if a.get("flags") else "")
                + ". A long-running ad is an advertiser paying back its clicks; no advertisers means the paid channel is unused, "
                  "not that it is cheap.", ""]

    # ---- supply in more ecosystems, free substitutes, site history ------------------
    def supply_lines(self, nid: str) -> list[str]:
        L = []
        for e in self.eco.get(nid) or []:
            store = {"cws": "Chrome Web Store", "atlassian": "Atlassian Marketplace (cloud)"}.get(e.get("store", ""), e.get("store", ""))
            unit = e.get("unit") or "users"
            L.append(f"**{store}** (s5_ecosystems, phrases: {e.get('queries', '—')}): {e.get('products', '—')} relevant products of {e.get('fetched', '—')} found; "
                     f"{e.get('players_1k', '—')} with ≥ 1k {unit}, {e.get('players_10k', '—')} with ≥ 10k; {_n(e.get('users_total'))} {unit} in total; "
                     f"top-1 **{e.get('top1') or '—'}** = {_n(e.get('top1_share'), '{:.0%}')}, top-3 = {_n(e.get('top3_share'), '{:.0%}')}, HHI {_n(e.get('hhi'), '{:.2f}')}"
                     + (f"; free {_n(e.get('free_share'), '{:.0%}')}" if e.get("free_share") not in (None, "") else "")
                     + f". Top 3: {e.get('top3') or '—'}. Store {unit} are installs, not buyers.")
            L.append("")
        o = self.oss.get(nid)
        if o and o.get("relevant") not in (None, ""):
            L.append(f"**Open-source substitutes** (GitHub, s5_oss): {o.get('relevant')} relevant repositories, {o.get('stars_100', '—')} with ≥ 100 stars, "
                     f"{o.get('stars_1k', '—')} with ≥ 1,000, of which maintained {o.get('maintained_1k', '—')}"
                     + (f"; largest **{o['top_repo']}** ({_n(o.get('top_stars'))} stars, last push {o.get('top_pushed', '—')}, {o.get('top_license') or 'no license'})" if o.get("top_repo") else "")
                     + (" (top 100 by stars was full: counts may be capped)" if o.get("truncated") == "1" else "")
                     + (". **O:oss-substitute**: a maintained free alternative exists; it caps willingness to pay for technical buyers more than for consumers." if "O:oss-substitute" in (o.get("flags") or "") else "."))
            L.append("")
        w = self.wb.get(nid)
        if w and w.get("measured") not in (None, "", "0"):
            L.append(f"**Competitor sites over time** (Wayback Machine, s9_wayback, {w['measured']} sites of the top App Store apps): "
                     f"the top-5 apps' sites are {_n(w['leaders_age_median'], '{:.0f}')} years old (median); first seen within 3 years: "
                     f"{_n(w['young_share'], '{:.0%}')}; no live capture in 12 months: {_n(w['quiet_share'], '{:.0%}')}.")
            L.append("")
        return L

    # ---- paid demand outside search -------------------------------------------------
    def freelance_line(self, nid: str) -> list[str]:
        f = self.free.get(nid)
        if not f:
            return []
        if f.get("matched") in (None, "", "0"):
            return ["- **Freelance exchanges** (s8_freelance, Kwork + FL.ru): no matching buyer posts in the history (normal for consumer apps)."]
        ver = _f(f.get("verified"))
        parts = []
        for src, label in (("kwork", "Kwork"), ("fl", "FL.ru")):
            if f.get(f"{src}_matched") in (None, "", "0"):
                continue
            parts.append(f"{label} {f[f'{src}_matched']} (build {f.get(f'{src}_build') or 0}, service {f.get(f'{src}_service') or 0}"
                         + (f", median budget {_n(f.get(f'{src}_budget_med'))} RUB" if f.get(f"{src}_budget_med") else "")
                         + (f", {f[f'{src}_posts']} posts read {f.get(f'{src}_window', '')}" if f.get(f"{src}_posts") else "") + ")")
        return [f"- **Freelance exchanges** (s8_freelance, Russian buyer posts that pay a person to build the software or do the task): "
                + "; ".join(parts) + "."
                + (" **Keyword matches NOT verified by the LLM: read the examples.**" if ver is not None and ver < 0.5 else "")
                + (f" Examples: {f['examples'][:240]}." if f.get("examples") else "")]

    def trustmrr_line(self, nid: str) -> list[str]:
        d = self.deals.get(nid) or {}
        if d.get("trustmrr_n") in (None, "", "0"):
            return []
        top = "; ".join(f"{r['name']} ({r['extra']})" for r in (self.tmrr.get(nid) or [])[:3])
        return [f"TrustMRR, startups whose revenue is read from the payment provider (not in the score): {d['trustmrr_n']} matched"
                + (f", MRR sum ${_n(d.get('trustmrr_mrr_sum'))}" if d.get("trustmrr_mrr_sum") else "")
                + (f", median ${_n(d.get('trustmrr_mrr_median'))}/month" if d.get("trustmrr_mrr_median") else "")
                + (f", {d['trustmrr_for_sale']} for sale" if d.get("trustmrr_for_sale") not in (None, "", "0") else "")
                + (f". Top: {top}" if top else "")
                + ". The keyless snapshot holds the ~1,000 top earners: a match proves the niche pays at the indie end, a zero proves nothing.", ""]

    # ---- buyer voice in YouTube comments --------------------------------------------
    def yt_lines(self, nid: str) -> list[str]:
        y = self.yt.get(nid)
        if not y:
            return []
        names = {"unmet_share": "unmet needs + price", "pain_share": "pain", "product_request_share": "asks for a product",
                 "question_share": "how-to questions", "praise_share": "praise"}
        shares = ", ".join(f"{label} {_n(y[k], '{:.0%}')}" for k, label in names.items() if y.get(k) not in (None, ""))
        prods = "; ".join((y.get("products") or "").split("; ")[:3])
        return ["## Buyer voice (YouTube comments, S10)", "",
                f"**YouTube comments verdict: {y.get('verdict', '—')}**" + (f" - {y['reason'].rstrip('.')}." if y.get("reason") else ".")
                + (" _The thresholds are a draft (`config/yt_comments.yaml`)._" if y.get("status") == "draft" else "")
                + f" {y.get('about_niche') or '—'} comments about the niche under {y.get('niche_videos') or '—'} videos"
                + (f" ({_n(y['niche_share'], '{:.0%}')} of the labelled comments)" if y.get("niche_share") else "")
                + (f"; {shares}" if shares else "") + (f". Top theme: {y['top_theme']}" if y.get("top_theme") else "")
                + (f". Products named: {prods}" if prods else "") + ". Details: `S10-yt-comments.md`.", ""]

    # ---- audience in VK communities ------------------------------------------------
    def vk_lines(self, nid: str) -> list[str]:
        v = self.vk.get(nid)
        if not v or v.get("status") not in ("ok", "no communities"):
            return []
        if v.get("status") == "no communities":
            return ["## Audience in VK communities (S8, evidence)", "",
                    f"No VK community about the niche's topic or trade passed the check (searched: {v.get('phrases') or '-'}).", ""]
        return ["## Audience in VK communities (S8, evidence)", "",
                f"{v['communities']} communities about the niche's topic or trade; the 10 largest have **{_n(v['members_top10'])} members** "
                f"(an upper bound: people join several, counts include bots); the largest is \"{v['top1']}\" ({_n(v['top1_members'])}); "
                f"{v['n_100k']} communities above 100k members and {v['n_10k']} above 10k. Searched: {v.get('phrases') or '-'}. "
                "Not in the score.", ""]

    # ---- buyer voice in Telegram chats -----------------------------------------------
    def tg_lines(self, nid: str) -> list[str]:
        y = self.tg.get(nid)
        if not y:
            return []
        names = {"unmet_share": "unmet needs + price", "pain_share": "pain", "product_request_share": "asks for a product",
                 "question_share": "how-to questions", "praise_share": "praise"}
        shares = ", ".join(f"{label} {_n(y[k], '{:.0%}')}" for k, label in names.items() if y.get(k) not in (None, ""))
        prods = "; ".join((y.get("products") or "").split("; ")[:3])
        return ["## Buyer voice (Telegram chats, S10)", "",
                f"**Telegram chats verdict: {y.get('verdict', '—')}**" + (f" - {y['reason'].rstrip('.')}." if y.get("reason") else ".")
                + (" _The thresholds are a draft (`config/tg_voice.yaml`)._" if y.get("status") == "draft" else "")
                + f" {y.get('about_niche') or '—'} messages about the niche in {y.get('niche_chats') or '—'} chats"
                + (f" ({_n(y['niche_share'], '{:.0%}')} of the labelled messages; ads {y.get('about_ad') or 0})" if y.get("niche_share") else "")
                + (f"; {shares}" if shares else "") + (f". Top theme: {y['top_theme']}" if y.get("top_theme") else "")
                + (f". Products named: {prods}" if prods else "") + ". Details: `S10-telegram.md`.", ""]

    # ---- leaderboard -----------------------------------------------------------------
    def tags(self, nid: str) -> list[str]:
        t = []
        s = self.serp.get(nid) or {}
        t += [x for x in (s.get("flags") or "").split() if x]
        t += [x for x in ((self.ads.get(nid) or {}).get("flags") or "").split() if x]
        o = self.oss.get(nid) or {}
        t += [x for x in (o.get("flags") or "").split() if x]
        for r in self.switch.get(nid) or []:
            p = _f(r.get("alt_ratio_pct"))
            if p is not None and p >= 0.8 and r["pool"] == "us":
                t.append("W:switch-high")
        w = self.who.get(nid) or {}
        if w.get("us_est"):
            t.append(f"who:{int(float(w['us_est'])):,}")
        v = self.vk.get(nid) or {}
        m = _f(v.get("members_top10"))
        if v.get("status") == "ok" and m:
            t.append(f"vk:{m / 1e6:.1f}M" if m >= 1e6 else f"vk:{m / 1e3:.0f}k")
        return t

    def yt_verdict(self, nid: str) -> tuple[str, str]:
        y = self.yt.get(nid) or {}
        return y.get("verdict", ""), y.get("reason", "")

    def tg_verdict(self, nid: str) -> tuple[str, str]:
        y = self.tg.get(nid) or {}
        return y.get("verdict", ""), y.get("reason", "")
