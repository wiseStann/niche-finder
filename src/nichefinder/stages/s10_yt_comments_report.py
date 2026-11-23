"""YouTube comments buyer voice: the verdict per niche (data/out/yt_comments_voice.csv), the themes of the needs named
(yt_comments_themes.json) and the report reports/S10-yt-comments.md. With --lang en: *_en and S10-yt-comments-en.md.

Input: yt_comments_fetch.csv, yt_comments_videos.csv (s10_yt_comments_fetch), yt_comments_llm.csv, yt_comments_items.jsonl
(s10_yt_comments_classify), score_final.csv (S6) and ru_reviews_verdict.csv (S10 Russian reviews, for comparison), both
optional, niches.yaml (side), config/yt_comments.yaml (`verdict`, `status`).

Themes: one LLM call per niche (cached in data/cache/llm/; without LLM_API_KEY only cached themes are shown) groups the
needs named in comments about the niche (pain, unmet need, price, product request) into 4-10 themes with counts and quotes.

The verdict is a rule, not a score, and it never changes the S6 verdict (see voice_verdicts()). Like the Russian reviews
rule it is relative: comment sections differ by genre (a review draws complaints, a tutorial draws questions), and the
share of comments that say anything about the niche varies with the video, so an absolute threshold would rank video
genres, not markets. A share must be in the top of the cohort (mid-rank percentile among the measured niches of the
same segment, B2C + prosumer or B2B, as in s6_score) and above an absolute floor. With fewer than `verdict.min_cohort`
measured niches in a segment the floors alone decide. Labels, tried in order: gap (unmet needs + price objections),
pain, seeking (asks which product to use: buyers compare, they do not flee; the Reddit lesson that only dissatisfaction
makes green informative), how-to (questions on how to do the task: demand for know-how rather than for a product),
content (praise), mixed; quiet = fewer than `verdict.min_niche_comments` labeled comments about the niche or fewer than
`verdict.min_videos` videos with them. While config/yt_comments.yaml has `status: draft` the report says so at the top.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from nichefinder import keys, llm, niches
from nichefinder.stages.info_score import pct
from nichefinder.stages.s10_ru_reviews_report import segment
from nichefinder.stages.s10_yt_comments_classify import VOICE
from nichefinder.stages.s10_yt_comments_fetch import (FETCH, MARKET, VIDEOS, config_status, lang_of, out_name, read_rows, settings,
                                                     target_niches)
from nichefinder.workspace import Workspace

SUMMARY = "Report: YouTube comments buyer voice per niche (verdict rule within B2C/B2B, need themes, products named)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

VERD = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
LANG_NAME = {"ru": "Russian", "en": "English (US)"}
VOICE_COLS = ["niche_id", "lang", "verdict", "reason", "segment", "cohort", "about_niche", "niche_videos", "niche_share",
              "unmet_share", "unmet_pct", "pain_share", "pain_pct", "product_request_share", "seek_pct", "question_share",
              "question_pct", "praise_share", "top_video_share", "top_theme", "products", "status"]
THEME_SYSTEM = "You are a rigorous market researcher. Output only JSON."


def f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def pc(x) -> str:
    v = f(x)
    return "-" if v is None else f"{v:.0%}"


# Words and column / config names of one voice source; s10_tg_report passes its own (chats, messages).
YT_WORDS = {"items": "comments", "unit": "video", "units": "videos", "source": "YouTube comments", "stage": "s10_yt_comments_classify",
            "min_items": "min_niche_comments", "min_units": "min_videos", "warn": "top_video_warn", "where": "under"}


def voice_verdicts(rows: dict[str, dict], cfg: dict, segments: dict[str, str] | None = None, words: dict | None = None) -> dict[str, dict]:
    """niche_id -> {verdict, reason, unmet_pct, pain_pct, seek_pct, question_pct, segment, cohort}. Labels: 🟢 gap,
    🟡 pain, 🟡 seeking, 🟡 how-to, 🟡 content, 🟡 mixed, ⚪ quiet, ⚪ incomplete (some LLM batches gave no answer: the
    shares would be over a part of the sample, so the niche stays out of the verdict and the cohort). `rows` are rows of
    yt_comments_llm.csv; `cfg` is the `verdict` block of config/yt_comments.yaml; `segments` maps niche_id to its
    cohort (one cohort when omitted); `words` names the source's items, units and settings (YT_WORDS by default)."""
    w = {**YT_WORDS, **(words or {})}
    n_units, top_share = f"niche_{w['units']}", f"top_{w['unit']}_share"
    seg = {nid: (segments or {}).get(nid, "all") for nid in rows}
    complete = {nid for nid, r in rows.items() if not (f(r.get("failed_batches"), 0) or 0)}
    measured = {nid: r for nid, r in rows.items() if nid in complete
                and (f(r.get("about_niche"), 0) or 0) >= cfg[w["min_items"]] and (f(r.get(n_units), 0) or 0) >= cfg[w["min_units"]]}
    out = {}
    for nid, r in rows.items():
        peers = [m for m in measured if seg[m] == seg[nid]]
        base = {"segment": seg[nid], "cohort": len(peers)}
        if nid not in complete:
            out[nid] = {**base, "verdict": "⚪ incomplete", "unmet_pct": "", "pain_pct": "", "seek_pct": "", "question_pct": "",
                        "reason": f"{int(f(r.get('failed_batches'), 0) or 0)} LLM batches gave no answer ({r.get('classified', 0)} of "
                                  f"{r.get('sampled', '?')} sampled {w['items']} labeled); re-run {w['stage']} (labeled batches are cached)"}
            continue
        if nid not in measured:
            out[nid] = {**base, "verdict": "⚪ quiet", "unmet_pct": "", "pain_pct": "", "seek_pct": "", "question_pct": "",
                        "reason": f"{int(f(r.get('about_niche'), 0) or 0)} labeled {w['items']} about the niche {w['where']} "
                                  f"{int(f(r.get(n_units), 0) or 0)} {w['units']} (needs {cfg[w['min_items']]} and {cfg[w['min_units']]}) - "
                                  f"{w['source']} say too little about this niche"}
            continue
        floors_only = len(peers) < cfg["min_cohort"]

        def rank(col):
            return pct([f(measured[m].get(col), 0) for m in peers], f(r.get(col), 0))

        u, p, s, q, pr = (f(r.get(c), 0) for c in ("unmet_share", "pain_share", "product_request_share", "question_share", "praise_share"))
        pu, pp, ps, pq = rank("unmet_share"), rank("pain_share"), rank("product_request_share"), rank("question_share")

        def top(v, key):
            return floors_only or v >= cfg[key]

        def where(v):
            return "" if floors_only else f", percentile {v:.0%} of {len(peers)} {seg[nid]} niches"

        rest = f"unmet needs + price {u:.0%}, pain {p:.0%}, asks for a product {s:.0%}, how-to {q:.0%}, praise {pr:.0%}"
        if u >= cfg["gap_floor"] and top(pu, "gap_pct"):
            v, why = "🟢 gap", (f"{u:.0%} of {w['items']} about the niche name something missing or object to the price "
                               f"(missing {pc(r.get('unmet_need_share'))}, price {pc(r.get('price_share'))}){where(pu)}")
        elif p >= cfg["pain_floor"] and top(pp, "pain_pct"):
            v, why = "🟡 pain", (f"{p:.0%} complain about the task or the existing tools{where(pp)}, while unmet needs + price are {u:.0%}: "
                                "the wedge is doing the job better, not a new job")
        elif s >= cfg["seek_floor"] and top(ps, "seek_pct"):
            v, why = "🟡 seeking", (f"{s:.0%} ask which product to use{where(ps)}, without dissatisfaction standing out "
                                   f"(unmet + price {u:.0%}, pain {p:.0%}): buyers compare, they do not flee")
        elif q >= cfg["howto_floor"] and top(pq, "howto_pct"):
            v, why = "🟡 how-to", (f"{q:.0%} ask how to do the task{where(pq)}: demand for know-how (an info product, onboarding) "
                                  f"more than for a new tool; {rest}")
        elif pr >= cfg["content_praise"]:
            v, why = "🟡 content", f"praise {pr:.0%}, no buyer signal stands out against the cohort ({rest})"
        else:
            v, why = "🟡 mixed", f"no share stands out against the cohort: {rest}"
        tv = f(r.get(top_share), 0) or 0
        if tv > cfg[w["warn"]]:
            why += f"; caution: {tv:.0%} of these {w['items']} come from one {w['unit']}, so this is mostly its audience's voice"
        out[nid] = {**base, "verdict": v, "reason": why, "unmet_pct": round(pu, 3), "pain_pct": round(pp, 3),
                    "seek_pct": round(ps, 3), "question_pct": round(pq, 3)}
    return out


def theme_prompt(name: str, lang: str, stmts: list[dict], source: str = "", item: str = "comment") -> str:
    """`source` says where the texts come from (default: YouTube comments under the niche's how-to and review videos)."""
    source = source or f"{LANG_NAME.get(lang, lang)} YouTube comments under the niche's how-to and review videos"
    return (f"Niche: {name}. Below are {len(stmts)} needs extracted from {source}, one per line as 'k: [kind] need | {item}'. "
            "Group them into 4-10 themes (distinct needs or "
            "complaints). For each theme return: theme (short English name), kind (unmet = something missing or a price objection; "
            "pain = a complaint about the task or the existing tools; seeking = asks which product to use), description (one sentence), "
            f"ids (list of k), quotes (2 best verbatim fragments up to 140 characters from the {item}s, in the original language). "
            'Output JSON {"themes": [...]}, largest theme first.\n\n'
            + "\n".join(f"{k}: [{r['kind']}] {r['pain']} | {r['text'][:160]}" for k, r in enumerate(stmts)))


def build_themes(ws: Workspace, lang: str, items: dict[str, list[dict]], names: dict[str, str], workers: int = 6,
                 source: str = "", item: str = "comment") -> dict[str, dict]:
    """niche_id -> {themes, statements, kinds, products}. Themes are counted from the ids the model returns. `source` and
    `item` describe the texts in the prompt (YouTube comments by default)."""
    jobs = {}
    for nid, recs in items.items():
        stmts = [r for r in recs if r["about"] == "niche" and r["kind"] in VOICE and r.get("pain")][:200]
        if stmts:
            jobs[nid] = stmts
    missing = []

    def call(nid):
        try:
            return llm.chat_json(ws, [{"role": "system", "content": THEME_SYSTEM},
                                      {"role": "user", "content": theme_prompt(names.get(nid, nid), lang, jobs[nid], source, item)}],
                                  max_tokens=4000)
        except keys.MissingKey:
            missing.append(nid)
            return None, False, None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        res = dict(zip(jobs, ex.map(call, list(jobs))))
    if missing:
        print(f"  LLM_API_KEY missing: no themes for {len(missing)} niches (cached themes are shown)")
    out = {}
    for nid, recs in items.items():
        nic = [r for r in recs if r["about"] == "niche"]
        themes = []
        content = (res.get(nid) or (None,))[0]
        for th in (content or {}).get("themes") or []:
            ids = sorted({int(k) for k in th.get("ids") or [] if str(k).lstrip("-").isdigit() and 0 <= int(k) < len(jobs.get(nid, []))})
            themes.append({"theme": str(th.get("theme") or "")[:80], "kind": str(th.get("kind") or ""), "description": str(th.get("description") or "")[:240],
                           "count": len(ids) or int(f(th.get("count"), 0) or 0), "ids": ids, "quotes": [str(x)[:160] for x in (th.get("quotes") or [])[:2]]})
        themes.sort(key=lambda t: -t["count"])
        out[nid] = {"themes": themes, "statements": len(jobs.get(nid, [])), "kinds": dict(Counter(r["kind"] for r in nic)),
                    "products": Counter(p for r in nic for p in dict.fromkeys(r["products"])).most_common(15)}
    return out


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lang", default="", choices=["", "ru", "en"], help="ru (default when nf.yaml markets include ru) or en")
    parser.add_argument("--workers", type=int, default=6, help="parallel LLM calls for the themes")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    lang = lang_of(ws, args)
    fetch_rows = read_rows(ws.out(out_name(FETCH, lang)))
    if not fetch_rows:
        print(f"{ws.out(out_name(FETCH, lang))} not found - run s10_yt_comments_fetch first")
        return
    vcfg, fcfg, scfg = settings(ws, "verdict"), settings(ws, "fetch"), settings(ws, "sample")
    status = config_status(ws)
    names = niches.niche_names(ws)
    llm_rows = {r["niche_id"]: r for r in read_rows(ws.out(out_name("yt_comments_llm.csv", lang)))}
    if not llm_rows:
        print(f"{ws.out(out_name('yt_comments_llm.csv', lang))} not found - run s10_yt_comments_classify first; the report shows the fetch only")
    items = defaultdict(list)
    for r in read_rows(ws.out(out_name("yt_comments_items.jsonl", lang))):
        items[r["niche_id"]].append(r)
    videos = defaultdict(list)
    for r in read_rows(ws.out(out_name(VIDEOS, lang))):
        videos[r["niche_id"]].append(r)
    score = {r["niche_id"]: r for r in read_rows(ws.out("score_final.csv"))}
    ru_rev = {r["niche_id"]: r for r in read_rows(ws.out("ru_reviews_verdict.csv"))} if lang == "ru" else {}
    segments = {n["id"]: segment(n.get("side", "")) for n in niches.load_niches(ws)}
    complete = [nid for nid, r in llm_rows.items() if not (f(r.get("failed_batches"), 0) or 0)]
    themes = build_themes(ws, lang, {nid: items.get(nid, []) for nid in complete}, names, int(getattr(args, "workers", 6) or 6))
    (ws.out(out_name("yt_comments_themes.json", lang))).write_text(json.dumps(themes, ensure_ascii=False, indent=1), encoding="utf-8")
    verdicts = voice_verdicts(llm_rows, vcfg, segments)
    fetch_by = {r["niche_id"]: r for r in fetch_rows}
    with open(ws.out(out_name("yt_comments_voice.csv", lang)), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=VOICE_COLS)
        w.writeheader()
        for nid, v in verdicts.items():
            r, t = llm_rows[nid], (themes.get(nid) or {}).get("themes") or []
            w.writerow({"niche_id": nid, "lang": lang, **{k: v[k] for k in ("verdict", "reason", "segment", "cohort", "unmet_pct", "pain_pct", "seek_pct", "question_pct")},
                        **{k: r.get(k, "") for k in ("about_niche", "niche_videos", "niche_share", "unmet_share", "pain_share", "product_request_share",
                                                     "question_share", "praise_share", "top_video_share", "products")},
                        "top_theme": t[0]["theme"] if t else "", "status": status})

    order = {nid: k for k, nid in enumerate(target_niches(ws, lang))}
    ids = list(dict.fromkeys(r["niche_id"] for r in fetch_rows))
    ids.sort(key=lambda x: (x not in verdicts, -(f(score.get(x, {}).get("score"), 0) or 0), order.get(x, len(order))))
    cohorts = Counter()
    for v in verdicts.values():
        cohorts[v["segment"]] = v["cohort"]
    mc = vcfg["min_cohort"]
    cohort_note = "; ".join(f"{s} {c} measured niches" + (f" (< {mc}: the floors alone decide)" if c < mc else "") for s, c in sorted(cohorts.items()))
    n_vid = sum(int(f(r.get("picked"), 0) or 0) for r in fetch_rows)
    n_com = sum(int(f(r.get("comments"), 0) or 0) for r in fetch_rows)
    n_lab = sum(int(f(r.get("classified"), 0) or 0) for r in llm_rows.values())
    by_status = Counter(r["status"] for r in fetch_rows)
    lname = LANG_NAME.get(lang, lang)
    L = [f"# S10: buyer voice - YouTube comments, {lname} (updated {ws.today.isoformat()})", ""]
    if status != "fixed":
        L += ["> **DRAFT.** The thresholds in `config/yt_comments.yaml` are not fixed yet (`status: draft`). Fix them before reading "
              "the verdicts below as a decision, then change them only with a written reason.", ""]
    no_check = sum(1 for r in fetch_rows if r.get("by") == "none")
    L += [f"{len(ids)} niches ({', '.join(f'{k}: {n}' for k, n in by_status.most_common())}), {n_vid} videos, {n_com:,} comments; "
          f"{n_lab:,} labeled by an LLM.", "",
          f"**How it was collected.** For each shortlisted niche whose geo includes {'Russia' if lang == 'ru' else 'the US'}: YouTube search "
          f"(Data API, relevance order, region {MARKET[lang]['region']}, any duration, published in the last {fcfg['window_months']} months) for "
          f"the niche's own queries in this order: {', '.join(fcfg['phrases'])} (brand = the brand query + \"{(fcfg.get('brand_suffix') or {}).get(lang, '')}\"), "
          f"at most {fcfg['max_phrases']} per niche, the next one only while fewer than {fcfg['min_videos']} relevant videos were found. "
          f"Videos with at least {fcfg['min_video_comments']} comments pass an LLM check: are the viewers the niche's buyers (a how-to for the task, "
          "a review or tutorial of its products, a story about the problem), or is it entertainment, news or a homonym. "
          f"The {fcfg['videos']} relevant videos with the most comments give up to {100 * int(fcfg['pages_per_video'])} top-level comments each "
          "(relevance order, no replies, none by the video's own channel"
          + (", Cyrillic only" if lang == "ru" else ", no Cyrillic") + ")."
          + (f" {no_check} niches were fetched without the LLM check (no key)." if no_check else ""), "",
          f"**What is measured.** A sample of up to {scfg['max_comments']} comments per niche with at least {scfg['min_chars']} characters, drawn evenly "
          "across its videos, is labeled by an LLM: is the comment about the niche (its task, problem or products) or only a reaction to the video, "
          "and its kind: pain (the task or a tool hurts), unmet need (something missing), price, product request (\"which app?\"), how-to question, "
          "praise. Shares are over comments about the niche: **unmet** = unmet need + price (what a new product could answer), **pain**, "
          "**asks for a product**, **how-to**. The needs are then grouped into themes.", "",
          "**Limits.** Commenters are viewers of popular videos, not a sample of buyers: a review video draws complaints, a tutorial draws questions, "
          "so the genre mix of the picked videos moves the shares (the rule compares niches with each other for that reason). Relevance order "
          "favours liked comments, and five videos can be one creator's audience (see the caution on one video). B2B buyers rarely comment on "
          "YouTube, so B2B niches are often quiet here. LLM labels and themes are not hand-validated.", "",
          f"**Verdict (a rule, not a score; it does not change S6):** 🟢 \"gap\" - unmet needs + price >= {vcfg['gap_floor']:.0%} of comments about "
          f"the niche and in the top of the cohort (percentile >= {vcfg['gap_pct']:.0%}); 🟡 \"pain\" - not a gap, complaints >= {vcfg['pain_floor']:.0%} "
          f"and percentile >= {vcfg['pain_pct']:.0%}; 🟡 \"seeking\" - asks for a product >= {vcfg['seek_floor']:.0%} and percentile >= {vcfg['seek_pct']:.0%} "
          f"(buyers compare, they do not flee); 🟡 \"how-to\" - how-to questions >= {vcfg['howto_floor']:.0%} and percentile >= {vcfg['howto_pct']:.0%} "
          f"(demand for know-how); 🟡 \"content\" - praise >= {vcfg['content_praise']:.0%}; 🟡 \"mixed\" - the rest; ⚪ \"quiet\" - fewer than "
          f"{vcfg['min_niche_comments']} labeled comments about the niche or fewer than {vcfg['min_videos']} videos with them. Percentiles within the "
          f"segment (B2C + prosumer, B2B). **Cohorts: {cohort_note or 'none'}.**", "",
          "## 1. Summary", ""]
    head = "| # | Niche | S6 | Score | YouTube verdict |" + (" RU reviews |" if lang == "ru" else "") + \
        " Videos | Comments (labeled) | About the niche | Unmet: need / price | Pain | Asks for a product | How-to | Praise | Theme #1 | Products named |"
    L += [head, "|" + "---|" * (head.count("|") - 1)]
    for k, nid in enumerate(ids, 1):
        s, fr, l, v = score.get(nid, {}), fetch_by[nid], llm_rows.get(nid), verdicts.get(nid)
        t = (themes.get(nid) or {}).get("themes") or []
        verdict = v["verdict"] if v else f"- ({fr['status']})"
        rr = f" {(ru_rev.get(nid) or {}).get('verdict', '-')} |" if lang == "ru" else ""
        if l:
            cells = (f"{l['niche_videos']} / {fr['picked']} | {fr['comments']} ({l['classified']}) | {l['about_niche']} ({pc(l['niche_share'])}) | "
                     f"**{pc(l['unmet_share'])}**: {pc(l['unmet_need_share'])} / {pc(l['price_share'])} | {pc(l['pain_share'])} | "
                     f"{pc(l['product_request_share'])} | {pc(l['question_share'])} | {pc(l['praise_share'])} | "
                     f"{(t[0]['theme'] + ' (' + str(t[0]['count']) + ')') if t else '-'} | {', '.join(p for p, _ in (themes.get(nid) or {}).get('products', [])[:4]) or '-'} |")
        else:
            cells = f"{fr['picked'] or 0} | {fr['comments'] or 0} | - | - | - | - | - | - | - | - |"
        L.append(f"| {k} | {names.get(nid, nid)} | {VERD.get(s.get('verdict'), '')} | {s.get('score', '')} | {verdict} |{rr} {cells}")
    groups = defaultdict(list)
    for nid in ids:
        if nid in verdicts:
            groups[verdicts[nid]["verdict"]].append(nid)
    unread = [nid for nid in ids if nid not in verdicts]
    by_u = lambda xs: sorted(xs, key=lambda x: -(f(llm_rows[x]["unmet_share"], 0) or 0))  # noqa: E731
    L += ["", "## 2. What this says", "",
          f"- **🟢 gap ({len(groups['🟢 gap'])})**: " + (", ".join(f"{names.get(x, x)} ({pc(llm_rows[x]['unmet_share'])})" for x in by_u(groups["🟢 gap"])) or "-")
          + ". Viewers name what the tools they know lack or object to the price more than in other niches: read the unmet themes below before believing it.",
          f"- **🟡 pain ({len(groups['🟡 pain'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 pain"]) or "-")
          + ". The task or the existing tools hurt; entering means doing the job better.",
          f"- **🟡 seeking ({len(groups['🟡 seeking'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 seeking"]) or "-")
          + ". Viewers ask which product to use: an open choice, not dissatisfaction.",
          f"- **🟡 how-to ({len(groups['🟡 how-to'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 how-to"]) or "-")
          + ". Viewers ask how to do the task: demand for know-how (guides, onboarding) more than for a tool.",
          f"- **🟡 content ({len(groups['🟡 content'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 content"]) or "-") + ".",
          f"- **🟡 mixed ({len(groups['🟡 mixed'])})**: " + (", ".join(names.get(x, x) for x in groups["🟡 mixed"]) or "-") + ".",
          f"- **⚪ quiet ({len(groups['⚪ quiet'])})**: " + (", ".join(names.get(x, x) for x in groups["⚪ quiet"]) or "-")
          + ". Few comments about the niche are not a signal against it: its buyers may not talk on YouTube.",
          f"- **⚪ incomplete ({len(groups['⚪ incomplete'])})**: " + (", ".join(names.get(x, x) for x in groups["⚪ incomplete"]) or "-")
          + ". Some LLM batches gave no answer: re-run the classify stage (cached batches are free), then this report.",
          f"- **Not measured ({len(unread)})**: " + (", ".join(f"{names.get(x, x)} ({fetch_by[x]['status']})" for x in unread) or "-")
          + (". `quota`: the run budget was spent before the niche; re-run the fetch (cached niches are free)." if any(fetch_by[x]["status"] == "quota" for x in unread) else "."),
          "", "## 3. By niche", ""]
    for k, nid in enumerate(ids, 1):
        s, fr, l, v, th = score.get(nid, {}), fetch_by[nid], llm_rows.get(nid), verdicts.get(nid), themes.get(nid) or {}
        L += [f"### {k}. {names.get(nid, nid)} - {v['verdict'] if v else fr['status']}", "",
              f"S6: {VERD.get(s.get('verdict'), '')} score {s.get('score', '-')}." + (f" YouTube verdict: {v['reason']}." if v else "")
              + (f" RU reviews: {ru_rev[nid]['verdict']}." if nid in ru_rev else ""), "",
              f"Searched: {fr.get('searched') or '-'}; {fr['candidates']} candidates, {fr['relevant']} relevant, {fr['picked']} read.", ""]
        picked = sorted((r for r in videos.get(nid, []) if str(r.get("picked")) == "1"), key=lambda r: -(f(r["comments"], 0) or 0))
        if picked:
            L += ["| Video | Channel | Published | Views | Comments | Read / kept |", "|---|---|---|---|---|---|"]
            for r in picked:
                title = str(r["title"]).replace("|", "/")[:80]
                st = "" if r.get("status") in ("ok", "") else f" ({r['status']})"
                L.append(f"| [{title}](https://www.youtube.com/watch?v={r['video_id']}) | {str(r['channel']).replace('|', '/')[:40]} | {r['published']} | "
                         f"{int(f(r['views'], 0) or 0):,} | {int(f(r['comments'], 0) or 0):,} | {r['read']} / {r['kept']}{st} |")
        if l:
            L += ["", f"- **LLM labels** ({l['classified']} comments; about the niche {l['about_niche']} ({pc(l['niche_share'])}), reactions to the video "
                      f"{l['about_video']}, off topic {l['off_topic']}): unmet need {pc(l['unmet_need_share'])}, price {pc(l['price_share'])}, "
                      f"pain {pc(l['pain_share'])}, asks for a product {pc(l['product_request_share'])}, how-to {pc(l['question_share'])}, "
                      f"praise {pc(l['praise_share'])}, other {pc(l['other_share'])}."]
        if th.get("themes"):
            L += ["", "**Need themes** (LLM grouping, largest first):", ""]
            for t in th["themes"][:8]:
                qs = "; ".join(f"\"{q}\"" for q in t["quotes"])
                L.append(f"- **{t['theme']}** [{t['kind']}] ({t['count']}) - {t['description']}" + (f" Quotes: {qs}" if qs else ""))
        if th.get("products"):
            L += ["", "**Products named:** " + "; ".join(f"{p} ({n})" for p, n in th["products"][:12]) + "."]
        L.append("")
    sfx = "" if lang == "ru" else " -- --lang en"
    L += ["---", "", f"_Stages: `s10_yt_comments_fetch`, `s10_yt_comments_classify` (LLM), `s10_yt_comments_report`{sfx}. Settings: "
          f"`config/yt_comments.yaml`. Data: `data/out/{out_name('yt_comments_docs.jsonl', lang)}`, `{out_name(VIDEOS, lang)}`, `{out_name(FETCH, lang)}`, "
          f"`{out_name('yt_comments_items.jsonl', lang)}`, `{out_name('yt_comments_llm.csv', lang)}`, `{out_name('yt_comments_themes.json', lang)}`, "
          f"`{out_name('yt_comments_voice.csv', lang)}`._", ""]
    rp = ws.report(out_name("S10-yt-comments.md", lang))
    rp.write_text("\n".join(L), encoding="utf-8")
    print(f"-> reports/{rp.name}, {out_name('yt_comments_voice.csv', lang)}: {len(ids)} niches;", dict(Counter(v["verdict"] for v in verdicts.values())))
