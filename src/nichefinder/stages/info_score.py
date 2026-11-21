"""Score, verdict and report of the info cohort (short video -> Telegram channel -> micro product).

Score, 0-100 (weights in config/score_info.yaml; mid-rank percentiles within the topics measured in this run):
  attention    = views_median * pct(median views) + views_p90 * pct(90th-percentile views)
  newcomers    = breakout_share * pct(breakout share) + small_share * pct(share of top videos from small channels)
  monetization = tg_channels * pct(share of channels pointing to Telegram) + offers * pct(share of videos with offers)
  spread       = spread * (1 - share of top videos from the top-3 channels)   (absolute, not a percentile)
  trend        = recent * pct(recent_ratio)
A missing value counts as the neutral percentile 0.5, as in s6_score.

Shown, never scored: data/out/info_telegram.csv (optional, info_telegram): the Telegram funnels of the authors of
teaching Shorts (how many link a measurable channel, its subscribers, how many already link a payment or a sales
funnel), as a table after the ranking and a line per topic; score.csv gets tg_linked, tg_subs_median, tg_big, pay_share.

Gates (red): I0 fewer than gates.min_videos short videos in the window; I1 median views below gates.min_views_median.
Flags (no effect): I:top3, I:fading, I:no-tg, I:ai-answers (info_ai rates the free chatbot answer at covers >=
flags.ai_answers: the chat gives the product's content away), I:paid-market / I:no-paid (info_paid's paid_flag, its
thresholds in config/info_paid.yaml). Verdict: red on a failed gate, green at verdict.green_min_score from
nf.yaml (70), yellow otherwise. While score_info.yaml has `status: draft` the report says so at the top: fix the
weights before reading the ranking as a decision.

All video metrics are over the teaching Shorts of a topic (info_youtube labels each video; entertainment and
off-topic videos are left out). Input: data/out/info_youtube.csv (required), info_youtube_videos.csv (examples in
the report, teaching videos only), info_ai.csv (optional, the AI substitute probe), info_paid.csv (optional, the paid
market: Stepik courses, Litres books), config/info_topics.yaml, config/score_info.yaml. Output: data/out/info_score.csv,
reports/info.md.
"""
from __future__ import annotations

import argparse
import csv

from nichefinder import info
from nichefinder.workspace import Workspace

SUMMARY = "Score, verdict and report of the info cohort"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

WEIGHTS = {"views_median": 20, "views_p90": 10, "breakout_share": 15, "small_share": 10, "tg_channels": 15,
           "offers": 10, "spread": 10, "recent": 10}
GATES = {"min_videos": 10, "min_views_median": 1000}
FLAGS = {"top3_share": 0.6, "recent_ratio_low": 0.5, "ai_answers": 2}
TELEGRAM = ("yt_channels", "tg_linked", "tg_subs_median", "tg_subs_p90", "tg_subs_max", "tg_big", "pay_share",
            "top_channel")
TELEGRAM_COLS = ["tg_linked", "tg_subs_median", "tg_big", "pay_share"]
COLS = ["rank", "topic_id", "verdict", "score", "gates", "flags", "attention", "newcomers", "monetization", "spread",
        "trend", "n_videos", "views_median", "views_p90", "breakout_share", "small_share", "tg_channel_share",
        "offer_share", "top3_share", "recent_ratio", "n_shorts", "teach_share", "ai_covers", "paid_flag", "sp_paid",
        "sp_paid_learners", "lr_paid", "lr_ratings", "who", "task", "product"]
PAID = ("paid_flag", "sp_courses", "sp_paid", "sp_paid_learners", "sp_price_median", "sp_top", "lr_paid", "lr_ratings",
        "lr_price_median", "lr_new", "lr_selfpub", "lr_top")


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pct(values, v) -> float:
    """Mid-rank percentile: share of values below plus half of the ties. Shares are often 0 for many topics; with
    "share <= v" six zero topics out of ten would each get 0.6 for having nothing, with mid-rank they get 0.3."""
    vals = [x for x in values if x is not None]
    if v is None or not vals:
        return 0.5
    return (sum(1 for x in vals if x < v) + 0.5 * sum(1 for x in vals if x == v)) / len(vals)


def score_rows(rows: list[dict], cfg: dict, green_min: float) -> list[dict]:
    """Scored and ranked topics (status ok only)."""
    w = {**WEIGHTS, **(cfg.get("weights") or {})}
    g = {**GATES, **(cfg.get("gates") or {})}
    fl = {**FLAGS, **(cfg.get("flags") or {})}
    ok = [r for r in rows if r.get("status") == "ok"]
    col = {k: [f(r.get(k)) for r in ok] for k in ("views_median", "views_p90", "breakout_share", "small_share",
                                                 "tg_channel_share", "offer_share", "recent_ratio")}
    out = []
    for r in ok:
        v = {k: f(r.get(k)) for k in col}
        top3 = f(r.get("top3_share"))
        parts = {
            "attention": w["views_median"] * pct(col["views_median"], v["views_median"])
            + w["views_p90"] * pct(col["views_p90"], v["views_p90"]),
            "newcomers": w["breakout_share"] * pct(col["breakout_share"], v["breakout_share"])
            + w["small_share"] * pct(col["small_share"], v["small_share"]),
            "monetization": w["tg_channels"] * pct(col["tg_channel_share"], v["tg_channel_share"])
            + w["offers"] * pct(col["offer_share"], v["offer_share"]),
            "spread": w["spread"] * (1 - top3 if top3 is not None else 0.5),
            "trend": w["recent"] * pct(col["recent_ratio"], v["recent_ratio"]),
        }
        score = sum(parts.values())
        gates = []
        if (f(r.get("n_videos")) or 0) < g["min_videos"]:
            gates.append("I0:thin")
        if (v["views_median"] or 0) < g["min_views_median"]:
            gates.append("I1:views")
        flags = []
        if top3 is not None and top3 >= fl["top3_share"]:
            flags.append("I:top3")
        if v["recent_ratio"] is not None and v["recent_ratio"] < fl["recent_ratio_low"]:
            flags.append("I:fading")
        if not v["tg_channel_share"]:
            flags.append("I:no-tg")
        ai = f(r.get("ai_covers"))
        if ai is not None and fl.get("ai_answers") is not None and ai >= fl["ai_answers"]:
            flags.append("I:ai-answers")
        if r.get("paid_flag"):
            flags.append(r["paid_flag"])
        verdict = "red" if gates else ("green" if score >= green_min else "yellow")
        out.append({**r, **{k: round(x, 1) for k, x in parts.items()}, "score": round(score, 1),
                    "gates": " ".join(gates), "flags": " ".join(flags), "verdict": verdict})
    order = {"green": 0, "yellow": 1, "red": 2}
    out.sort(key=lambda r: (order[r["verdict"]], -r["score"]))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


def human(v) -> str:
    x = f(v)
    if x is None:
        return "-"
    for div, suf in ((1e6, "M"), (1e3, "k")):
        if abs(x) >= div:
            return f"{x / div:.1f}{suf}"
    return f"{x:.0f}"


def share(v) -> str:
    x = f(v)
    return "-" if x is None else f"{x:.0%}"


def teach(r: dict) -> str:
    if r.get("teach_share") in (None, ""):
        return str(r.get("n_videos", ""))
    return f"{r.get('n_videos')} / {r.get('n_shorts')}"


def report(ws: Workspace, scored: list[dict], rest: list[dict], videos: dict[str, list[dict]], cfg: dict,
           settings: dict) -> str:
    lines = ["# Info topics: short video -> Telegram -> micro product", ""]
    if cfg.get("status") != "fixed":
        lines += ["> **DRAFT weights** (`config/score_info.yaml`, `status: draft`). Fix the weights before reading this "
                  "ranking as a decision; changing them after seeing it defeats the point of a score.", ""]
    lines += [f"Run {ws.today}; videos published since {scored[0]['window_from'] if scored else '-'}; "
              f"lang `{settings['lang']}`, region `{settings['region']}`; {len(scored)} topics scored. "
              "Percentiles are within this run's topics: the score ranks topics against each other. "
              + ("Video metrics count teaching Shorts only: an LLM labels the most viewed Shorts and sketches, vlogs, "
                 "fails and off-topic videos are left out (`kind` in info_youtube_videos.csv)."
                 if any(str(r.get("classified")) == "1" for r in scored) else
                 "**Videos are not labelled** (no LLM key in the info_youtube run): entertainment counts as attention."),
              "",
              "| # | topic | verdict | score | attention | newcomers | money | spread | trend | median views | p90 views "
              "| breakout | small channels | TG channels | offers | teaching / all shorts | AI covers "
              "| paid learners / ratings | gates / flags |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in scored:
        lines.append(f"| {r['rank']} | {r['topic_id']} | {r['verdict']} | {r['score']} | {r['attention']} | "
                     f"{r['newcomers']} | {r['monetization']} | {r['spread']} | {r['trend']} | "
                     f"{human(r.get('views_median'))} | {human(r.get('views_p90'))} | {share(r.get('breakout_share'))} | "
                     f"{share(r.get('small_share'))} | {share(r.get('tg_channel_share'))} | "
                     f"{share(r.get('offer_share'))} | {teach(r)} | {r.get('ai_covers') if r.get('ai_covers') not in (None, '') else '-'} | "
                     f"{human(r.get('sp_paid_learners'))} / {human(r.get('lr_ratings'))} | "
                     f"{' '.join(x for x in (r['gates'], r['flags']) if x)} |")
    if any(r.get("ai_covers") not in (None, "") for r in scored):
        lines += ["", "AI covers (info_ai, no effect on the score): how much of the micro product a free chatbot answer "
                  "gives away; 2 = an equivalent for free, 1 = the content but not what the product adds (video, "
                  "designed materials, a trusted author, accountability), 0 = the chat barely helps. Same model answers "
                  "and judges; answers in `data/out/info_ai_answers.jsonl`."]
    if any(r.get("paid_flag") is not None for r in scored):
        lines += ["", "Paid learners / ratings (info_paid, no effect on the score): learners in the relevant paid Stepik "
                  "courses / ratings of the relevant paid non-fiction Litres books that sold (a rating is a sales proxy); "
                  "flags I:paid-market and I:no-paid by the thresholds in `config/info_paid.yaml`. Stepik is mostly IT, "
                  "school and exam courses: an empty Stepik says little about craft topics. Items in "
                  "`data/out/info_paid_items.csv`."]
    if rest:
        why = {"global": "the most viewed top of the phrase is foreign-language; add a Russian-specific phrase",
               "quota": "not measured yet; re-run info_youtube after the quota reset (midnight Pacific time)",
               "empty": "no teaching Shorts passed the filters"}
        lines += ["", "Not scored:"]
        lines += [f"- {r['topic_id']} ({r.get('status')}: {why.get(r.get('status'), '')})" for r in rest]
    if any(r.get("tg_linked") not in (None, "") for r in scored):
        lines += ["", "Telegram funnels (info_telegram, no effect on the score): of the YouTube authors of a topic's "
                  "teaching Shorts, how many link a Telegram channel or group that shows a count (t.me links and "
                  "\"@name\" in the descriptions), its subscribers (one per author: the largest link), how many have "
                  "10k+, and the share of authors who link a payment or sales-funnel platform (GetCourse, Boosty, "
                  "Tribute, BotHelp...). A floor: a channel's \"link in profile\" is not in the YouTube API. Links "
                  "in `data/out/info_telegram_channels.csv`.", "",
                  "| # | topic | authors | with Telegram | median subscribers | p90 | 10k+ | sell | largest |",
                  "|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r['rank']} | {r['topic_id']} | {r.get('yt_channels') or 0} | {r.get('tg_linked') or 0} | "
                  f"{human(r.get('tg_subs_median'))} | {human(r.get('tg_subs_p90'))} | {r.get('tg_big') or 0} | "
                  f"{share(r.get('pay_share'))} | {r.get('top_channel') or '-'} |" for r in scored]
    for r in scored:
        lines += ["", f"## {r['rank']}. {r['topic_id']}: {r['verdict']}, {r['score']}", ""]
        for k in ("who", "task", "product"):
            if r.get(k):
                lines.append(f"- **{k}**: {r[k]}")
        lines.append(f"- **phrases**: {r.get('phrases', '')}")
        if r.get("tg_linked") not in (None, ""):
            lines.append(f"- **Telegram**: {r['tg_linked']} of {r.get('yt_channels') or 0} authors of teaching Shorts "
                         f"link a measurable channel; median {human(r.get('tg_subs_median'))} subscribers, "
                         f"{r.get('tg_big') or 0} with 10k+; {share(r.get('pay_share'))} link a payment or sales funnel"
                         + (f"; largest {r['top_channel']}" if r.get("top_channel") else ""))
        if r.get("ai_covers") not in (None, ""):
            lines.append(f"- **free chatbot answer**: covers {r['ai_covers']} of 2 (votes {r.get('ai_votes') or '-'}) - "
                         f"{r.get('ai_reason', '')}"
                         + (f" The chat cannot give: {r['ai_missing']}." if r.get("ai_missing") else ""))
        if r.get("paid_flag") is not None:
            lines.append(f"- **paid market**: Stepik {r.get('sp_paid') or 0} paid of {r.get('sp_courses') or 0} courses, "
                         f"{human(r.get('sp_paid_learners'))} learners, median {human(r.get('sp_price_median'))} RUB"
                         + (f" (top: {r['sp_top']})" if r.get("sp_top") else "")
                         + f"; Litres {r.get('lr_paid') or 0} books sold, {human(r.get('lr_ratings'))} ratings, median "
                         f"{human(r.get('lr_price_median'))} RUB, {r.get('lr_new') or 0} new in 24 months, "
                         f"{r.get('lr_selfpub') or 0} self-published" + (f" (top: {r['lr_top']})" if r.get("lr_top") else ""))
        vs = [x for x in videos.get(r["topic_id"], []) if x.get("kind", "") in ("T", "")]
        top = sorted(vs, key=lambda x: -(f(x["views"]) or 0))[:3]
        brk = sorted((x for x in vs if x.get("breakout") == "1" and x.get("small") == "1"),
                     key=lambda x: -(f(x["views"]) or 0))[:3]
        for title, items in (("Top views", top), ("Small channels that took off", brk)):
            if items:
                lines += ["", f"{title}:"]
                lines += [f"- [{x['title'][:90]}](https://www.youtube.com/shorts/{x['video_id']}): {human(x['views'])} "
                          f"views; {x['channel_title']} ({human(x['subs'])} subs){'; TG' if x.get('tg') == '1' else ''}"
                          for x in items]
    return "\n".join(lines) + "\n"


def run(ws: Workspace, args: argparse.Namespace) -> None:
    src = ws.out("info_youtube.csv")
    settings, topics = info.load(ws)
    if not src.is_file():
        if not topics:
            print("  no topics in config/info_topics.yaml: nothing to score")
            return
        raise SystemExit(f"{src} not found: run `nf run info_youtube` first")
    cfg = ws.load_config(info.SCORE_FILE, {}) or {}
    meta = {t["id"]: t for t in topics if t.get("id")}
    ai: dict[str, dict] = {}
    apath = ws.out("info_ai.csv")
    if apath.is_file():
        ai = {a["topic_id"]: {"ai_covers": a["covers"], "ai_votes": a.get("votes", ""), "ai_reason": a["reason"],
                              "ai_missing": a["missing"]}
              for a in csv.DictReader(open(apath, encoding="utf-8"))}
    paid: dict[str, dict] = {}
    ppath = ws.out("info_paid.csv")
    if ppath.is_file():
        paid = {p["topic_id"]: {k: p.get(k, "") for k in PAID} for p in csv.DictReader(open(ppath, encoding="utf-8"))}
    rows = [{**r, **{k: meta.get(r["topic_id"], {}).get(k, "") for k in ("who", "task", "product")},
             **ai.get(r["topic_id"], {}), **paid.get(r["topic_id"], {})}
            for r in csv.DictReader(open(src, encoding="utf-8"))]
    scored = score_rows(rows, cfg, float(ws.setting("verdict.green_min_score", 70)))
    rest = [r for r in rows if r.get("status") != "ok"]
    tpath = ws.out("info_telegram.csv")
    if tpath.is_file():
        tg = {t["topic_id"]: {k: t.get(k, "") for k in TELEGRAM} for t in csv.DictReader(open(tpath, encoding="utf-8"))}
        for r in scored:
            r.update(tg.get(r["topic_id"], {}))
    videos: dict[str, list[dict]] = {}
    vpath = ws.out("info_youtube_videos.csv")
    if vpath.is_file():
        for v in csv.DictReader(open(vpath, encoding="utf-8")):
            videos.setdefault(v["topic_id"], []).append(v)
    with open(ws.out("info_score.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS + TELEGRAM_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(scored)
    path = ws.report("info.md")
    path.write_text(report(ws, scored, rest, videos, cfg, settings), encoding="utf-8")
    for r in scored[:15]:
        print(f"  {r['rank']:>2} {r['topic_id']:32} {r['verdict']:6} {r['score']:>5}  {r['gates']} {r['flags']}")
    print("->", ws.out("info_score.csv"), "and", path, f"({cfg.get('status', 'draft')} weights)")
