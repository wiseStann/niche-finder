"""Telegram chats buyer voice: the verdict per niche (data/out/tg_voice.csv), the themes of the needs named
(tg_themes.json) and the report reports/S10-telegram.md.

Input: tg_fetch.csv, tg_chats.csv (s10_tg_fetch), tg_llm.csv, tg_items.jsonl (s10_tg_classify), and for comparison
score_final.csv (S6), ru_reviews_verdict.csv and yt_comments_voice.csv (the other Russian voice sources), all optional;
niches.yaml (side); config/tg_voice.yaml (`verdict`, `status`).
Themes: one LLM call per niche groups the needs named in messages about the niche into 4-10 themes (the theme step of
s10_yt_comments_report; cached; without LLM_API_KEY only cached themes are shown).
The verdict is the rule of the YouTube comments (s10_yt_comments_report.voice_verdicts) with its own thresholds: a share
must be in the top of the cohort (mid-rank percentile among the measured niches of the same segment, B2C + prosumer or
B2B) and above an absolute floor; labels in order: gap (unmet needs + price), pain, seeking (asks which product to use),
how-to, content (praise), mixed; quiet = fewer than `verdict.min_niche_messages` labeled messages about the niche or
fewer than `verdict.min_chats` chats with them. It never changes the S6 verdict. While config/tg_voice.yaml has
`status: draft` the report says so at the top.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict

from nichefinder import niches
from nichefinder.stages.s10_ru_reviews_report import segment
from nichefinder.stages.s10_tg_fetch import CHATS, FETCH, config_status, settings, target_niches
from nichefinder.stages.s10_yt_comments_fetch import read_rows
from nichefinder.stages.s10_yt_comments_report import build_themes, f, pc, voice_verdicts
from nichefinder.workspace import Workspace

SUMMARY = "Report: Telegram chats buyer voice per niche (verdict rule within B2C/B2B, need themes, products named)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

VERD = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
WORDS = {"items": "messages", "unit": "chat", "units": "chats", "source": "Telegram chats", "stage": "s10_tg_classify",
         "min_items": "min_niche_messages", "min_units": "min_chats", "warn": "top_chat_warn", "where": "in"}
SOURCE = "Russian messages in public Telegram group chats of the niche's users (owners, practitioners, users of its tools)"
VOICE_COLS = ["niche_id", "verdict", "reason", "segment", "cohort", "about_niche", "about_ad", "niche_chats", "niche_share",
              "unmet_share", "unmet_pct", "pain_share", "pain_pct", "product_request_share", "seek_pct", "question_share",
              "question_pct", "praise_share", "top_chat_share", "top_theme", "products", "status"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workers", type=int, default=6, help="parallel LLM calls for the themes")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    fetch_rows = read_rows(ws.out(FETCH))
    if not fetch_rows:
        print(f"{ws.out(FETCH)} not found - run s10_tg_fetch first")
        return
    vcfg, fcfg, scfg = settings(ws, "verdict"), settings(ws, "fetch"), settings(ws, "sample")
    status = config_status(ws)
    names = niches.niche_names(ws)
    llm_rows = {r["niche_id"]: r for r in read_rows(ws.out("tg_llm.csv"))}
    if not llm_rows:
        print(f"{ws.out('tg_llm.csv')} not found - run s10_tg_classify first; the report shows the fetch only")
    items = defaultdict(list)
    for r in read_rows(ws.out("tg_items.jsonl")):
        items[r["niche_id"]].append(r)
    chats = defaultdict(list)
    for r in read_rows(ws.out(CHATS)):
        chats[r["niche_id"]].append(r)
    score = {r["niche_id"]: r for r in read_rows(ws.out("score_final.csv"))}
    ru_rev = {r["niche_id"]: r for r in read_rows(ws.out("ru_reviews_verdict.csv"))}
    ytv = {r["niche_id"]: r for r in read_rows(ws.out("yt_comments_voice.csv"))}
    segments = {n["id"]: segment(n.get("side", "")) for n in niches.load_niches(ws)}
    complete = [nid for nid, r in llm_rows.items() if not (f(r.get("failed_batches"), 0) or 0)]
    themes = build_themes(ws, "ru", {nid: items.get(nid, []) for nid in complete}, names, int(getattr(args, "workers", 6) or 6),
                          source=SOURCE, item="message")
    ws.out("tg_themes.json").write_text(json.dumps(themes, ensure_ascii=False, indent=1), encoding="utf-8")
    verdicts = voice_verdicts(llm_rows, vcfg, segments, WORDS)
    with open(ws.out("tg_voice.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=VOICE_COLS)
        w.writeheader()
        for nid, v in verdicts.items():
            r, t = llm_rows[nid], (themes.get(nid) or {}).get("themes") or []
            w.writerow({"niche_id": nid, **{k: v[k] for k in ("verdict", "reason", "segment", "cohort", "unmet_pct", "pain_pct", "seek_pct", "question_pct")},
                        **{k: r.get(k, "") for k in ("about_niche", "about_ad", "niche_chats", "niche_share", "unmet_share", "pain_share",
                                                     "product_request_share", "question_share", "praise_share", "top_chat_share", "products")},
                        "top_theme": t[0]["theme"] if t else "", "status": status})

    order = {nid: k for k, nid in enumerate(target_niches(ws))}
    ids = list(dict.fromkeys(r["niche_id"] for r in fetch_rows))
    ids.sort(key=lambda x: (x not in verdicts, -(f(score.get(x, {}).get("score"), 0) or 0), order.get(x, len(order))))
    cohorts = Counter()
    for v in verdicts.values():
        cohorts[v["segment"]] = v["cohort"]
    mc = vcfg["min_cohort"]
    cohort_note = "; ".join(f"{s} {c} measured niches" + (f" (< {mc}: the floors alone decide)" if c < mc else "") for s, c in sorted(cohorts.items()))
    n_chats = sum(int(f(r.get("picked"), 0) or 0) for r in fetch_rows)
    n_msg = sum(int(f(r.get("messages"), 0) or 0) for r in fetch_rows)
    n_lab = sum(int(f(r.get("classified"), 0) or 0) for r in llm_rows.values())
    by_status = Counter(r["status"] for r in fetch_rows)
    fetch_by = {r["niche_id"]: r for r in fetch_rows}
    L = [f"# S10: buyer voice - Telegram chats (updated {ws.today.isoformat()})", ""]
    if status != "fixed":
        L += ["> **DRAFT.** The thresholds in `config/tg_voice.yaml` are not fixed yet (`status: draft`). Fix them before reading "
              "the verdicts below as a decision, then change them only with a written reason.", ""]
    L += [f"{len(ids)} niches ({', '.join(f'{k}: {n}' for k, n in by_status.most_common())}), {n_chats} chats, {n_msg:,} messages; "
          f"{n_lab:,} labeled by an LLM.", "",
          "**How it was collected.** For each shortlisted niche with geo both or ru, an LLM writes "
          f"{fcfg['phrases_llm']} Russian phrases that the titles of its users' group chats would contain (plus the hand phrases of "
          "`config/tg_voice.yaml`). Telegram's global search returns public chats for them; only groups count (not broadcast "
          f"channels), with at least {fcfg['min_members']} members. An LLM keeps the chats whose members are the niche's users talking "
          "about their work (owners, practitioners, users of its tools) and drops chats of clients, jobs, ads, neighbourhoods and other "
          f"trades. In the {fcfg['chats']} largest kept chats, Telegram's message search runs for each term ({', '.join(fcfg['terms'])}"
          + (", plus the niche's brands" if fcfg["brands"] else "") + f"), up to {fcfg['max_per_term']} messages per term from the last "
          f"{fcfg['window_months']} months. No chat is joined; author names and ids are not stored.", "",
          f"**What is measured.** A sample of up to {scfg['max_messages']} messages per niche with at least {scfg['min_chars']} characters, drawn "
          "evenly across its chats, is labeled by an LLM: is the message about the niche (its task, problem or tools), an advertisement, or "
          "off topic, and its kind: pain, unmet need, price, product request (\"which app?\"), how-to question, praise. Shares are over "
          "messages about the niche, as for the YouTube comments, so the two compare.", "",
          "**Limits.** The search terms pick tool talk, so these shares describe how the niche's users talk about tools, not everything they "
          "discuss. Chat titles decide which chats are found, and big chats are moderated differently (some are mostly ads). Members are "
          "not a sample of the market: they are the people who join chats. LLM labels and themes are not hand-validated.", "",
          f"**Verdict (a rule, not a score; it does not change S6):** 🟢 \"gap\" - unmet needs + price >= {vcfg['gap_floor']:.0%} of messages about "
          f"the niche and percentile >= {vcfg['gap_pct']:.0%}; 🟡 \"pain\" - complaints >= {vcfg['pain_floor']:.0%}, percentile >= {vcfg['pain_pct']:.0%}; "
          f"🟡 \"seeking\" - asks for a product >= {vcfg['seek_floor']:.0%}, percentile >= {vcfg['seek_pct']:.0%}; 🟡 \"how-to\" - how-to questions >= "
          f"{vcfg['howto_floor']:.0%}, percentile >= {vcfg['howto_pct']:.0%}; 🟡 \"content\" - praise >= {vcfg['content_praise']:.0%}; 🟡 \"mixed\" - the rest; "
          f"⚪ \"quiet\" - fewer than {vcfg['min_niche_messages']} labeled messages about the niche or fewer than {vcfg['min_chats']} chats with them. "
          f"Percentiles within the segment (B2C + prosumer, B2B). **Cohorts: {cohort_note or 'none'}.**", "",
          "## 1. Summary", ""]
    head = ("| # | Niche | S6 | Score | Telegram verdict | YT voice | RU reviews | Chats | Messages (labeled) | About the niche | Ads | "
            "Unmet: need / price | Pain | Asks for a product | How-to | Praise | Theme #1 | Products named |")
    L += [head, "|" + "---|" * (head.count("|") - 1)]
    for k, nid in enumerate(ids, 1):
        s, fr, lr, v = score.get(nid, {}), fetch_by[nid], llm_rows.get(nid), verdicts.get(nid)
        t = (themes.get(nid) or {}).get("themes") or []
        verdict = v["verdict"] if v else f"- ({fr['status']})"
        if lr:
            cells = (f"{lr['niche_chats']} / {fr['picked']} | {fr['messages']} ({lr['classified']}) | {lr['about_niche']} ({pc(lr['niche_share'])}) | "
                     f"{lr['about_ad']} | **{pc(lr['unmet_share'])}**: {pc(lr['unmet_need_share'])} / {pc(lr['price_share'])} | {pc(lr['pain_share'])} | "
                     f"{pc(lr['product_request_share'])} | {pc(lr['question_share'])} | {pc(lr['praise_share'])} | "
                     f"{(t[0]['theme'] + ' (' + str(t[0]['count']) + ')') if t else '-'} | "
                     f"{', '.join(p for p, _ in (themes.get(nid) or {}).get('products', [])[:4]) or '-'} |")
        else:
            cells = f"{fr['picked'] or 0} | {fr['messages'] or 0} | - | - | - | - | - | - | - | - | - |"
        L.append(f"| {k} | {names.get(nid, nid)} | {VERD.get(s.get('verdict'), '')} | {s.get('score', '')} | {verdict} | "
                 f"{(ytv.get(nid) or {}).get('verdict', '-')} | {(ru_rev.get(nid) or {}).get('verdict', '-')} | {cells}")
    groups = defaultdict(list)
    for nid in ids:
        if nid in verdicts:
            groups[verdicts[nid]["verdict"]].append(nid)
    unread = [nid for nid in ids if nid not in verdicts]
    L += ["", "## 2. What this says", ""]
    notes = {"🟢 gap": "Users name what their tools lack or object to the price more than in other niches: read the unmet themes below first.",
             "🟡 pain": "The task or the existing tools hurt; entering means doing the job better.",
             "🟡 seeking": "Users ask each other which product to use: an open choice, not dissatisfaction.",
             "🟡 how-to": "Users ask how to do the task: demand for know-how more than for a tool.",
             "🟡 content": "", "🟡 mixed": "",
             "⚪ quiet": "Few messages about the niche are not a signal against it: its users may talk elsewhere or in closed chats.",
             "⚪ incomplete": "Some LLM batches gave no answer: re-run s10_tg_classify (cached batches are free), then this report."}
    for label, note in notes.items():
        L.append(f"- **{label} ({len(groups[label])})**: " + (", ".join(names.get(x, x) for x in groups[label]) or "-") + (f". {note}" if note else "."))
    L += [f"- **Not measured ({len(unread)})**: " + (", ".join(f"{names.get(x, x)} ({fetch_by[x]['status']})" for x in unread) or "-")
          + (". `flood`: Telegram asked to wait; re-run the fetch later (the cache keeps what was read)." if any(fetch_by[x]["status"] == "flood" for x in unread) else "."),
          "", "## 3. By niche", ""]
    for k, nid in enumerate(ids, 1):
        s, fr, lr, v, th = score.get(nid, {}), fetch_by[nid], llm_rows.get(nid), verdicts.get(nid), themes.get(nid) or {}
        L += [f"### {k}. {names.get(nid, nid)} - {v['verdict'] if v else fr['status']}", "",
              f"S6: {VERD.get(s.get('verdict'), '')} score {s.get('score', '-')}." + (f" Telegram verdict: {v['reason']}." if v else ""), "",
              f"Chat search phrases: {fr.get('phrases') or '-'}; {fr['candidates']} candidate chats, {fr['relevant']} relevant, {fr['picked']} read.", ""]
        picked = [r for r in chats.get(nid, []) if str(r.get("picked")) == "1"]
        if picked:
            L += ["| Chat | Members | Messages kept | Status |", "|---|---|---|---|"]
            for r in picked:
                L.append(f"| [{str(r['title']).replace('|', '/')[:70]}](https://t.me/{r['username']}) | {int(f(r['members'], 0) or 0):,} | "
                         f"{r['messages']} | {r['status']} |")
        dropped = [r for r in chats.get(nid, []) if r.get("fit") == "no"][:6]
        if dropped:
            L += ["", "Dropped by the chat check: " + "; ".join(f"{str(r['title'])[:50]} ({r['why']})" for r in dropped) + "."]
        if lr:
            L += ["", f"- **LLM labels** ({lr['classified']} messages; about the niche {lr['about_niche']} ({pc(lr['niche_share'])}), ads "
                      f"{lr['about_ad']}, off topic {lr['off_topic']}): unmet need {pc(lr['unmet_need_share'])}, price {pc(lr['price_share'])}, "
                      f"pain {pc(lr['pain_share'])}, asks for a product {pc(lr['product_request_share'])}, how-to {pc(lr['question_share'])}, "
                      f"praise {pc(lr['praise_share'])}, other {pc(lr['other_share'])}."]
        if th.get("themes"):
            L += ["", "**Need themes** (LLM grouping, largest first):", ""]
            for t in th["themes"][:8]:
                qs = "; ".join(f"\"{q}\"" for q in t["quotes"])
                L.append(f"- **{t['theme']}** [{t['kind']}] ({t['count']}) - {t['description']}" + (f" Quotes: {qs}" if qs else ""))
        if th.get("products"):
            L += ["", "**Products named:** " + "; ".join(f"{p} ({n})" for p, n in th["products"][:12]) + "."]
        L.append("")
    L += ["---", "", "_Stages: `s10_tg_fetch`, `s10_tg_classify` (LLM), `s10_tg_report`. Settings: `config/tg_voice.yaml`. Data: "
          "`data/out/tg_docs.jsonl`, `tg_chats.csv`, `tg_fetch.csv`, `tg_items.jsonl`, `tg_llm.csv`, `tg_themes.json`, `tg_voice.csv`._", ""]
    ws.report("S10-telegram.md").write_text("\n".join(L), encoding="utf-8")
    print(f"-> reports/S10-telegram.md, tg_voice.csv: {len(ids)} niches;", dict(Counter(v["verdict"] for v in verdicts.values())))
