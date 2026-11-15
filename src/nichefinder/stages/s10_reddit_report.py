"""Buyer-voice report -> reports/S10-reddit-voice.md.

Input: data/out/reddit_voice.csv, reddit_brands.csv, reddit_monthly.csv (s10_reddit_metrics), reddit_voice_llm.csv,
reddit_voice_themes.json (s10_reddit_classify), reddit_subs_stats_*.csv (s10_reddit_fetch), score_final.csv (S6, optional),
niches.yaml, config/reddit_terms.yaml.
The Reddit verdict is a rule, not a score: see reddit_verdict() and the report header. Other stages import reddit_verdict.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import defaultdict

from nichefinder import niches
from nichefinder.stages.s10_reddit_fetch import terms_config
from nichefinder.stages.s10_reddit_metrics import last_month
from nichefinder.workspace import Workspace

SUMMARY = "Report: Reddit buyer voice per niche (verdict rule, brand share, pain themes)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

VERD = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def pct(x):
    v = f(x)
    return "-" if v is None else f"{v:.0%}"


def n(x):
    return f"{int(f(x, 0) or 0):,}".replace(",", " ")


def reddit_verdict(v, l):
    """🟢 "seeking" / 🟡 "leader" / 🟡 "content" / 🟡 "seeking but content" / 🟡 "weak" / ⚪ "quiet" - the rule is described in the
    report header. Shares come from the LLM (over documents about software); without LLM labels, from regex markers.
    `v` is a row of reddit_voice.csv, `l` a row of reddit_voice_llm.csv or None. Returns (label, reason)."""
    docs = int(v["posts"]) + int(v["comments"])
    if docs < 300 or (l and int(l["on_topic"]) < 60):
        return "⚪ quiet", "fewer than 300 documents (or < 60 about software) - Reddit is not representative for this niche"
    if l:
        seek, compl, sw, price, praise = (f(l[k]) or 0 for k in ("seek_share", "complaint_share", "switching_share", "pricing_share", "praise_share"))
    else:
        seek, compl, sw, price, praise = (f(v["seek_share"]) or 0), (f(v["complain_share"]) or 0), (f(v["switch_share"]) or 0), (f(v["price_share"]) or 0), 0
    top1 = f(v["brand_top1_share"], 0) or 0
    unhappy = compl + sw + price
    # Green needs DISSATISFACTION (complaints + switching + price >= 20 % of documents about software), not just
    # "which one should I pick" questions: questions without dissatisfaction mean "searching, but content".
    if praise >= 0.25 and praise > seek:
        return "🟡 content", f"praise {praise:.0%} is above \"what to choose\" requests ({seek:.0%}) - users are broadly happy with what exists{(' (' + v['brand_top1'] + ' ' + format(top1, '.0%') + ' of the conversation)') if top1 else ''}"
    if unhappy >= 0.20 and top1 <= 0.5:
        return "🟢 seeking", f"{unhappy:.0%} of documents about software are unhappy (complaints {compl:.0%} + switching {sw:.0%} + price {price:.0%}), {seek:.0%} are seeking; conversation leader {v['brand_top1'] or '-'} {top1:.0%} <= 50 %"
    if unhappy >= 0.20:
        return "🟡 leader", f"{unhappy:.0%} unhappy ({seek:.0%} seeking), but the conversation is about one player: {v['brand_top1']} {top1:.0%}"
    if seek >= 0.25:
        return "🟡 seeking but content", f"{seek:.0%} ask \"what to choose\", but dissatisfaction is only {unhappy:.0%} < 20 % - comparing, not running away"
    return "🟡 weak", f"unhappy {unhappy:.0%} < 20 %, seeking {seek:.0%} < 25 %"


def run(ws: Workspace, args: argparse.Namespace) -> None:
    def rd(name):
        p = ws.out(name)
        return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []

    names = niches.niche_names(ws)
    cfg, st = terms_config(ws)
    native_posts = int(st["native_max_posts"])
    history_year = str(st["history_start"])[:4]
    voice = {r["niche_id"]: r for r in rd("reddit_voice.csv")}
    brands = defaultdict(list)
    for r in rd("reddit_brands.csv"):
        brands[r["niche_id"]].append(r)
    monthly = defaultdict(dict)
    for r in rd("reddit_monthly.csv"):
        monthly[r["niche_id"]][r["month"]] = (int(r["posts"]), int(r["comments"]))
    llm = {r["niche_id"]: r for r in rd("reddit_voice_llm.csv")}
    tp = ws.out("reddit_voice_themes.json")
    themes = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
    subs = {}
    for p in glob.glob(str(ws.out("reddit_subs_stats_*.csv"))):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if r.get("display"):
                subs[r["sub"]] = r
    score = {r["niche_id"]: r for r in rd("score_final.csv")}
    ids = [x for x in cfg if x in voice]
    ids.sort(key=lambda x: -(f(score.get(x, {}).get("score"), 0) or 0))
    n_docs = sum(int(voice[x]["posts"]) + int(voice[x]["comments"]) for x in ids)
    n_cls = sum(int(llm[x]["classified"]) for x in ids if x in llm)
    last = last_month(ws.today)
    month_names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    until = f"{month_names[int(last[5:]) - 1]} {last[:4]}"
    L = [f"# S10: buyer voice - Reddit (updated {ws.today.isoformat()})", "",
         f"{len(ids)} niches with data, {n(n_docs)} posts and comments from {len(subs)} subreddits; "
         f"{n(n_cls)} documents labeled by an LLM for intent, pain, products, switching and willingness to pay.", "",
         "**How it was collected.** The official Reddit API is closed to new script apps (the creation form needs an application) and reddit.com/*.json answers 403, "
         "so the source is the open **Arctic Shift** archive (arctic-shift.photon-reddit.com). Its full-text search times out on medium and large subreddits, "
         "so subreddits are fetched **as a listing by date** and filtered by terms locally (`config/reddit_terms.yaml`). Volume rules: a \"native\" subreddit of the niche "
         f"(at most {n(native_posts)} posts in total) - all posts since {history_year} and comments for the last 12 months; a big general one (r/personalfinance, r/travel, r/Fitness) - "
         "only the last <= 100 pages of posts (about 1-12 months depending on activity) and only those matching brands/phrases.", "",
         "**What is measured.** (1) Volume and trend of discussion, over native subreddits (compare year / base year and the last 12 months vs the previous 12; more than +-20 % is UP/DOWN); "
         "(2) intent markers by regex (asking for a recommendation / complaining / switching / talking about price) - share of documents; "
         "(3) brand share of voice - a document counts once per brand, HHI over mentions, brand trend over 12/12 months; "
         "(4) LLM labeling of a sample of up to 160 posts + 160 comments per niche (priority: documents with a question, \"looking for\", \"alternative\", \"switched\", \"sucks\", a price, or a brand): intent, pain, products, "
         "\"from -> to\", willingness to pay, quote; then clustering of pains into 6-12 themes with quotes.", "",
         "**Limits.** Reddit is an English-language, mostly American, tech-literate audience: demand from other languages is not visible here; niches without a native subreddit (AI receptionist, "
         f"Shopify apps, B2B) have little data over a short window. The archive can lag by weeks - series are cut at {last}. Regex markers are coarse (for example \"bug\" also catches "
         "talk about bugs in other products), so conclusions lean on the LLM labels and the regexes serve to compare niches with each other.", "",
         "**Reddit verdict (a rule, not a score; shares are over documents about software per LLM labels):** 🟡 \"content\" - praise >= 25 % and above the share of \"what to choose\"; "
         "🟢 \"seeking\" - dissatisfaction (complaints + switching + price) >= 20 % and no brand takes more than 50 % of the conversation; "
         "🟡 \"leader\" - dissatisfaction >= 20 %, but the conversation is about one player; 🟡 \"seeking but content\" - \"what to choose\" >= 25 % with dissatisfaction < 20 %; 🟡 \"weak\" - the rest; ⚪ \"quiet\" - < 300 documents or < 60 about software. "
         "Questions of \"what to choose\" without dissatisfaction are not a sign of a vacuum. The S6 verdict is not recomputed: this is an independent layer for a manual decision.", "",
         "## 1. Summary", "",
         "| # | Niche | S6 | Score | Reddit | Posts since start / comments 12 mo | Post trend compare/base · 12/12 | Markers: seeking / complaints / switching / price | LLM: seeking / complaints / switching / price / praise | Share of voice: top 3 (HHI) | Pain theme #1 | Switch #1 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    verdicts, unhappy = {}, {}
    for k, nid in enumerate(ids, 1):
        v, l, s = voice[nid], llm.get(nid), score.get(nid, {})
        rv, why = reddit_verdict(v, l)
        verdicts[nid] = (rv, why)
        yoy = f(v["yoy"])
        trend = f"{v['r_24_22'] or '-'} · {('{:+.0%}'.format(yoy)) if yoy is not None else '-'} {v['verdict']}"
        marks = f"{pct(v['seek_share'])} / {pct(v['complain_share'])} / {pct(v['switch_share'])} / {pct(v['price_share'])}"
        lm = f"{pct(l['seek_share'])} / {pct(l['complaint_share'])} / {pct(l['switching_share'])} / {pct(l['pricing_share'])} / {pct(l['praise_share'])}" if l else "-"
        unhappy[nid] = (f(l["complaint_share"]) or 0) + (f(l["switching_share"]) or 0) + (f(l["pricing_share"]) or 0) if l else 0
        L.append(f"| {k} | {names.get(nid, nid)} | {VERD.get(s.get('verdict'), '')} | {s.get('score', '')} | {rv} | {n(v['posts'])} / {n(v['comments'])} | {trend} | {marks} | {lm} | {v['brand_top3'] or '-'} ({v['brand_hhi']}) | "
                 f"{(l or {}).get('top_theme', '') or '-'} ({(l or {}).get('top_theme_count', '')}) | {(l or {}).get('top_switch', '') or '-'} |")
    g = sorted([x for x in ids if verdicts[x][0].startswith("🟢")], key=lambda x: -unhappy[x])
    ld = [x for x in ids if verdicts[x][0] == "🟡 leader"]
    ok = [x for x in ids if verdicts[x][0] == "🟡 content"]
    sk = [x for x in ids if verdicts[x][0] == "🟡 seeking but content"]
    wk = [x for x in ids if verdicts[x][0] == "🟡 weak"]
    q = [x for x in ids if verdicts[x][0].startswith("⚪")]
    L += ["", "## 2. What this says", "",
          f"- **🟢 \"seeking\" ({len(g)})**, by descending dissatisfaction (complaints + switching + price): " + (", ".join(f"{names.get(x, x)} ({unhappy[x]:.0%})" for x in g) or "-") + ". "
          "Buyers on Reddit ask \"which app\", complain and change products, and no brand owns the conversation - demand-side confirmation of an open market, independent of search volumes. "
          "The 20 % threshold means one document about software in five complains, switches or argues about price; below that, people compare rather than run. Borderline niches (17-19 %) are named in section 3.",
          f"- **🟡 \"leader\" ({len(ld)})**: " + (", ".join(f"{names.get(x, x)} - {voice[x]['brand_top1']} {float(voice[x]['brand_top1_share']):.0%}" for x in ld) or "-") + ". There is demand for change, but the conversation revolves around one player: enter only with an explicit anti-leader positioning (see the leader's pain themes).",
          f"- **🟡 \"content\" ({len(ok)})**: " + (", ".join(f"{names.get(x, x)} - {voice[x]['brand_top1']} {float(voice[x]['brand_top1_share']):.0%}" for x in ok) or "-") + ". Praise outweighs requests: users are broadly happy with what exists; the niche is alive, but pains are secondary.",
          f"- **🟡 \"seeking but content\" ({len(sk)})**: " + (", ".join(f"{names.get(x, x)} (seeking {float((llm.get(x) or {}).get('seek_share') or 0):.0%}, unhappy {unhappy[x]:.0%})" for x in sk) or "-") + ". They ask \"which app\", but complaints, switching and price talk are rare - comparing, not running; no anti-X wedge here.",
          f"- **🟡 \"weak\" ({len(wk)})**: " + (", ".join(names.get(x, x) for x in wk) or "-") + ".",
          f"- **⚪ \"quiet\" ({len(q)})**: " + (", ".join(names.get(x, x) for x in q) or "-") + ". Few documents are not a signal against the niche: the audience is not on Reddit (SMB, Shopify merchants, other languages).", ""]
    L += ["## 3. By niche", ""]
    for k, nid in enumerate(ids, 1):
        v, l, s, t = voice[nid], llm.get(nid), score.get(nid, {}), themes.get(nid) or {}
        rv, why = verdicts[nid]
        sub_l = []
        for sb in cfg[nid]["subs"]:
            stt = subs.get(sb, {})
            np_ = f(stt.get("num_posts"))
            kind = "native" if np_ is not None and np_ <= native_posts else "big"
            subs_n = f(stt.get("subscribers"), 0) or 0
            sub_l.append(f"r/{sb} ({(f'{subs_n / 1e6:.1f} M' if subs_n >= 1e6 else f'{subs_n / 1e3:.0f}k')} subscribers, {kind})")
        L += [f"### {k}. {names.get(nid, nid)} - {rv}", "",
              f"S6: {VERD.get(s.get('verdict'), '')} score {s.get('score', '')}. Reddit verdict: {why}. Subreddits: {', '.join(sub_l)}.", "",
              f"- **Volume:** {n(v['posts'])} posts (since {history_year}), {n(v['comments'])} comments (12 months). Post trend: compare/base year = {v['r_24_22'] or '-'}, last 12 months {n(v['posts_last12'])} vs previous {n(v['posts_prev12'])} -> **{v['verdict']}**."]
        mon = monthly.get(nid, {})
        if mon:
            years = {}
            for m, (p, _) in mon.items():
                years[m[:4]] = years.get(m[:4], 0) + p
            L.append("- **Posts by year:** " + ", ".join(f"{y}: {n(c)}" for y, c in sorted(years.items())) + f" ({ws.today.year} - through {until}).")
        L.append(f"- **Markers (regex, share of documents):** seeking a recommendation {pct(v['seek_share'])}, complaining {pct(v['complain_share'])}, switching {pct(v['switch_share'])}, price {pct(v['price_share'])}.")
        bl = brands.get(nid, [])
        if bl:
            top = ", ".join(f"{r['brand']} {float(r['share']):.0%} ({r['mentions']})" for r in bl[:6])
            L.append(f"- **Brand share of voice** ({v['brand_mentions']} mentions, HHI {v['brand_hhi']}): {top}.")
            tr = [r for r in bl if r.get("trend") not in ("", None)]
            if tr:
                up = [r for r in sorted(tr, key=lambda r: -float(r["trend"])) if float(r["trend"]) > 0][:3]
                dn = [r for r in sorted(tr, key=lambda r: float(r["trend"])) if float(r["trend"]) < 0][:3]
                L.append("- **Who is growing in conversations** (12 months vs previous 12, >= 10 mentions): " + (", ".join(f"{r['brand']} {float(r['trend']):+.0%}" for r in up) or "nobody")
                         + "; declining: " + (", ".join(f"{r['brand']} {float(r['trend']):+.0%}" for r in dn) or "nobody") + ".")
        if l:
            L.append(f"- **LLM labels** ({l['classified']} documents): seeking a recommendation {pct(l['seek_share'])}, complaints {pct(l['complaint_share'])}, switching {pct(l['switching_share'])}, price {pct(l['pricing_share'])}, praise {pct(l['praise_share'])}; "
                     f"willingness to pay: \"too expensive\" {l['too_expensive']}, \"worth the money\" {l['worth_it']}, \"want it free\" {l['wants_free']}, \"cancelled\" {l['cancelled']}.")
        if t.get("themes"):
            L += ["", "**Pain themes** (LLM clustering, descending):", ""]
            for th in t["themes"][:10]:
                qs = "; ".join(f"\"{str(qq)[:150]}\"" for qq in (th.get("quotes") or [])[:2])
                L.append(f"- **{th.get('theme', '')}** ({th.get('count', '')}) - {th.get('description', '')}" + (f" Quotes: {qs}" if qs else ""))
        sw = [(a, c) for a, c in (t.get("switching") or []) if "?" not in a and len(set(x.strip() for x in a.split("->"))) == 2]
        if sw:
            L += ["", "**Switches \"from -> to\":** " + "; ".join(f"{a} ({c})" for a, c in sw[:10]) + "."]
        L.append("")
    L += ["---", "", "_Stages: `s10_reddit_fetch` (archive, shardable), `s10_reddit_threads`, `s10_reddit_classify` (LLM), `s10_reddit_metrics`, `s10_reddit_report`. "
          "Data: `data/cache/arctic/<niche>_posts.jsonl`, `_comments.jsonl`; `data/out/reddit_voice*.csv|json`, `reddit_brands.csv`, `reddit_monthly.csv`._", ""]
    ws.report("S10-reddit-voice.md").write_text("\n".join(L), encoding="utf-8")
    print("-> reports/S10-reddit-voice.md,", len(ids), "niches;", {k: v[0] for k, v in verdicts.items()})
