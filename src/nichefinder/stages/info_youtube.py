"""Short-video metrics for each info topic (YouTube Data API): attention, room for newcomers, Telegram funnels, offers.

For every phrase of a topic: measure.pages search pages (2 by default, the 100 most viewed videos; measure.order,
default viewCount) of videos under 4 minutes published in the window (relevanceLanguage and regionCode from config/info_topics.yaml), then video and
channel statistics. Kept: videos up to measure.shorts_max_seconds long (Shorts), with lang ru only Cyrillic titles,
with a topic `must` regex only videos whose title or description matches it in words (hashtags do not count), and
with `must_not` none that match it anywhere, hashtags included. Per topic, over the kept videos (the top of the
topic's attention pool):

- n_videos, n_channels; views_median, views_p90 (attention);
- breakout_share: videos with views >= breakout_ratio x channel subscribers and >= breakout_min_views, among videos
  whose channel shows its subscriber count (videos that outgrew their channel);
- small_share: videos from channels under small_channel_subs, among the same videos (room for newcomers at the top);
- top3_share: share of the kept videos that come from the three channels with the most of them (do a few creators
  own the topic's top). Counted in videos, not views: in a top-50 by views one viral video takes about half of all
  views (0.47-0.51 on test topics), so a views share only says whether there was a mega-hit;
- tg_channel_share / tg_video_share: Telegram link or mention (tg_pattern) in the video or channel description;
- offer_share: title or description names a guide, checklist, course... (offer_pattern);
- per video only, for info_telegram: pay (the video or channel description links a payment, paid-content or
  sales-funnel platform, pay_pattern) and tg_links (the Telegram channels and groups those descriptions link to or
  name as "@name" after a Telegram word);
- recent_ratio: (videos from the recent half of the window + 1) / (videos from the older half + 1). Older videos had
  longer to collect views, so every topic leans old; a higher ratio means recent videos reach the top.

Why the most viewed and not the relevance order: relevance mixes in fresh videos with a few hundred views (median
1-2k on test topics) and leans so hard to the last months that the recent/older split measures YouTube's freshness
boost, not the topic; the most viewed top separates topics clearly (2 of 47 vs 28 of 49 videos from small
channels). The cost: a broad phrase can pull in viral videos that only mention its words; `must` and `must_not`
filter them. Hashtags do not count for `must` because Shorts stuff them for reach: on the first run comedy sketches
tagged #self-esteem set the median of the self-esteem topic to 1.7M views. Phrase length matters as much: a how-to tail shrinks the pool, so on the first 30-topic run phrases
ending in "what to do" had medians of 1-2k views against 30-180k for subject phrases. One anchor per topic that
names the subject in 1-3 words keeps topics comparable (info.validate warns about longer phrases).
The sample is a ranking, not a census: the numbers compare topics with each other. Since 2025 YouTube counts every
Shorts replay as a view, so compare Shorts only with Shorts.

Teaching videos only (measure.classify, on by default; needs LLM_API_KEY): an LLM labels every kept video from its
title, channel and the start of its description as T (teaches: something the viewer can use), E (about the topic but
made to amuse: sketches, pranks, fails, vlogs, reactions, news, a result shown without the method) or O (off topic:
a homonym or a passing mention), one call per topic, cached. The metrics above are computed over T videos only; a
missing label counts as T. Why: on the first full run (2026-11-21) the most viewed top of broad topics was mostly
comedy that only uses the topic's words (a school-exam guessing game, physics jokes, gymnastics fails, a comedy-show
sketch about neural networks), so attention measured how easy a topic is to joke about, not whether people watch
lessons in it, the content a micro-product seller makes. Teaching videos were half of the top in the median topic (3-100 %),
so the sample is two search pages: from one page 25 of 61 topics kept fewer than gates.min_videos. n_shorts counts the kept videos before the labels,
dropped_fun and dropped_off what the labels removed, teach_share = T / n_shorts. Without the key the stage measures
all kept videos and says so (classified 0).

Input: config/info_topics.yaml, config/score_info.yaml (`measure`). Output: data/out/info_youtube.csv (per topic),
data/out/info_youtube_videos.csv (per video, with its label in `kind`). Cache: data/cache/youtube/,
data/cache/llm_info_kind/. Key: YOUTUBE_API_KEY; LLM_API_KEY for the labels. Cost: free quota of 10,000 units per
day and a separate limit of 100 search calls per day; a search page costs 100 units and one search call, statistics
2-4 units, so with 2 pages about 45 one-phrase topics a day. A run stopped by the quota keeps what it measured;
re-run the next day and the cached topics cost nothing.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
import statistics

from nichefinder import info, keys, llm
from nichefinder.sources import youtube
from nichefinder.workspace import Workspace

SUMMARY = "Short-video metrics per info topic (YouTube Data API)"
KEYS: tuple[str, ...] = ("YOUTUBE_API_KEY",)
NEEDS: tuple[str, ...] = ()

MEASURE = {
    "order": "viewCount", "shorts_max_seconds": 180, "breakout_ratio": 10, "breakout_min_views": 10000,
    "small_channel_subs": 10000, "tg_pattern": r"(?:t\.me|telegram\.me|telegram\.dog)/|telegram|\btg\b",
    "offer_pattern": r"guide|checklist|course|template|ebook|workshop|webinar|coaching", "classify": True,
    "pages": 2,
    # Payment, paid-content or sales-funnel platforms in a description: the author already sells (info_telegram too)
    "pay_pattern": r"getcourse|boosty\.to|tribute\.tg|t\.me/tribute|prodamus|payform|lava\.top|robokassa|yookassa"
                   r"|yoomoney|cloudpayments|gumroad|patreon\.com|bothelp\.io|salebot|leadteh|senler",
}
CYRILLIC = re.compile("[\u0400-\u04FF]")
HASHTAG = re.compile(r"#\w+")
# Telegram links in descriptions: public names and invite links; service paths are not channels
TG_LINK = re.compile(r"(?:t\.me|telegram\.me|telegram\.dog)/(?:s/)?(\+[\w-]{6,}|joinchat/[\w-]{6,}|[A-Za-z]\w{3,31})")
TG_SERVICE = {"share", "addstickers", "addemoji", "addlist", "proxy", "socks", "boost", "tribute", "joinchat", "iv",
              "contact", "setlanguage", "login"}
# "@name" right after a Telegram word ("TG @name", "Telegram - @name"): a third of the mentions carry no t.me link.
# No "@" in between, so an e-mail address or an Instagram handle after another word is not taken.
TG_AT = re.compile(r"(?:телеграм|telegram|\bтг\b|\btg\b)[^@\n]{0,40}@([A-Za-z]\w{3,31})", re.I)


def tg_links(*texts: str) -> list[str]:
    """Telegram channel or group links in the texts: public names (lower case, from t.me links or "@name" after a
    Telegram word) and invite links; bots and service paths are left out (a bot has no audience count)."""
    out = []
    for text in texts:
        for m in [*TG_LINK.finditer(text or ""), *TG_AT.finditer(text or "")]:
            h = m.group(1)
            if not h.startswith(("+", "joinchat/")):
                h = h.lower()
                if h in TG_SERVICE or h.endswith("bot"):
                    continue
            if h not in out:
                out.append(h)
    return out
DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
TOPIC_COLS = ["topic_id", "status", "phrases", "n_found", "dropped_lang", "dropped_must", "n_shorts", "dropped_fun",
              "dropped_off", "teach_share", "classified", "n_videos", "n_channels", "views_median", "views_p90",
              "subs_median", "breakout_share", "small_share", "top3_share", "tg_channel_share",
              "tg_video_share", "offer_share", "recent", "older", "recent_ratio", "window_from"]
VIDEO_COLS = ["topic_id", "video_id", "kind", "published", "seconds", "views", "likes", "comments", "channel_id",
              "channel_title", "subs", "breakout", "small", "tg", "offer", "pay", "tg_links", "title"]
KIND_PROMPT = """You sort short videos (YouTube Shorts) of one topic for a study of who could sell a micro info product
(a guide, a checklist, a mini course) on this topic through short videos.

Label every video by its title, channel and the start of its description:
T - teaches: about the topic and gives the viewer something usable: an instruction, tips, an explanation, a technique
    or a process shown so that it can be repeated, an exercise to follow, a lesson, advice on choosing.
E - entertains: about the topic but made to amuse or to show, not to teach: humor, sketches, pranks, reactions,
    fails, vlogs, drama, challenges, news, a finished result or a transformation shown without the method.
O - off topic: the topic's words in another sense (another meaning of the word) or only a passing mention.
A video that teaches with humor is T when the viewer learns something they can use.

Answer JSON: {"labels": {"<number>": "T" | "E" | "O", ...}} with every number."""


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--budget", type=int, default=9000, help="max quota units for uncached calls in this run")
    p.add_argument("--only", default="", help="comma-separated topic ids")


def seconds(iso: str) -> int:
    m = DURATION.match(iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def window_start(today: dt.date, months: int) -> dt.date:
    """First day of the month `months` before the run month: the same window for every run in one month (cache hits)."""
    y, m = today.year, today.month - int(months)
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, 1)


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def video_rows(topic_id: str, videos: list[dict], channels: list[dict], measure: dict, lang: str,
               must: str = "", must_not: str = "", dropped: dict | None = None) -> list[dict]:
    """Kept videos of one topic with their channel and the per-video flags. `dropped`, when given, counts the videos
    each filter removed: long, lang, must, must_not."""
    tg = re.compile(measure["tg_pattern"], re.I)
    offer = re.compile(measure["offer_pattern"], re.I)
    pay = re.compile(measure["pay_pattern"], re.I)
    need = re.compile(must, re.I) if must else None
    drop = re.compile(must_not, re.I) if must_not else None
    ch = {c["id"]: c for c in channels}
    rows = []
    dropped = {} if dropped is None else dropped
    for v in videos:
        sn, st = v.get("snippet") or {}, v.get("statistics") or {}
        sec = seconds((v.get("contentDetails") or {}).get("duration", ""))
        views = _int(st.get("viewCount"))
        title = sn.get("title") or ""
        desc = sn.get("description") or ""
        reason = ("long" if views is None or not 0 < sec <= measure["shorts_max_seconds"] else
                  "lang" if lang == "ru" and not CYRILLIC.search(title) else
                  "must" if need and not need.search(HASHTAG.sub(" ", title + "\n" + desc)) else
                  "must_not" if drop and drop.search(title + "\n" + desc) else "")
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        c = ch.get(sn.get("channelId"), {})
        cst = c.get("statistics") or {}
        subs = None if cst.get("hiddenSubscriberCount") else _int(cst.get("subscriberCount"))
        rows.append({
            "topic_id": topic_id, "video_id": v.get("id"), "published": (sn.get("publishedAt") or "")[:10],
            "seconds": sec, "views": views, "likes": _int(st.get("likeCount")), "comments": _int(st.get("commentCount")),
            "channel_id": sn.get("channelId"), "channel_title": sn.get("channelTitle") or "",
            "subs": subs,
            "breakout": "" if subs is None else int(views >= measure["breakout_ratio"] * subs
                                                     and views >= measure["breakout_min_views"]),
            "small": "" if subs is None else int(subs < measure["small_channel_subs"]),
            "tg": int(bool(tg.search(desc))),
            "tg_channel": int(bool(tg.search(desc) or tg.search((c.get("snippet") or {}).get("description") or ""))),
            "offer": int(bool(offer.search(title + "\n" + desc))),
            "pay": int(bool(pay.search(desc + "\n" + ((c.get("snippet") or {}).get("description") or "")))),
            "tg_links": " ".join(tg_links(desc, (c.get("snippet") or {}).get("description") or "")),
            "title": title, "desc": desc,
        })
    return rows


def video_kinds(ws: Workspace, topic: dict, rows: list[dict]) -> dict[str, str] | None:
    """video_id -> T / E / O from one cached LLM call (see the module docstring); None when the call failed."""
    lines = []
    for i, r in enumerate(rows, 1):
        desc = " ".join((r.get("desc") or "").split())[:160]
        lines.append(f"{i}. {r['title']} | channel: {r['channel_title']} | {desc}")
    about = "; ".join(x for x in (f"phrases: {', '.join(info.phrases(topic))}", topic.get("task") or "") if x)
    res, _, _ = llm.chat_json(ws, [{"role": "system", "content": KIND_PROMPT},
                                   {"role": "user", "content": f"Topic: {topic['id']} ({about})\n\n" + "\n".join(lines)}],
                              max_tokens=2500, temperature=0, cache_namespace="llm_info_kind")
    if not isinstance(res, dict) or not isinstance(res.get("labels"), dict):
        return None
    labels = {str(k): str(v).strip().upper()[:1] for k, v in res["labels"].items()}
    out = {}
    for i, r in enumerate(rows, 1):
        k = labels.get(str(i), "T")
        out[r["video_id"]] = k if k in ("T", "E", "O") else "T"
    return out


def percentile(sorted_vals: list[float], q: float):
    """Nearest-rank percentile of a sorted list."""
    if not sorted_vals:
        return ""
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


def metrics(rows: list[dict], measure: dict, mid: dt.date) -> dict:
    """Topic metrics from its kept videos (see the module docstring)."""
    n = len(rows)
    out: dict = {"n_videos": n}
    if not n:
        return out
    views = sorted(r["views"] for r in rows)
    known = [r for r in rows if r["subs"] is not None]
    by_channel: dict[str, int] = {}
    tg_channel: dict[str, int] = {}
    for r in rows:
        by_channel[r["channel_id"]] = by_channel.get(r["channel_id"], 0) + 1
        tg_channel[r["channel_id"]] = max(tg_channel.get(r["channel_id"], 0), r["tg_channel"])
    top3 = sum(sorted(by_channel.values(), reverse=True)[:3])
    recent = sum(1 for r in rows if r["published"] and dt.date.fromisoformat(r["published"]) >= mid)
    out.update({
        "n_channels": len(by_channel),
        "views_median": statistics.median(views),
        "views_p90": percentile(views, 0.9),
        "subs_median": statistics.median(r["subs"] for r in known) if known else "",
        "breakout_share": round(sum(r["breakout"] for r in known) / len(known), 3) if known else "",
        "small_share": round(sum(r["small"] for r in known) / len(known), 3) if known else "",
        "top3_share": round(top3 / n, 3),
        "tg_channel_share": round(sum(tg_channel.values()) / len(tg_channel), 3),
        "tg_video_share": round(sum(r["tg"] for r in rows) / n, 3),
        "offer_share": round(sum(r["offer"] for r in rows) / n, 3),
        "recent": recent, "older": n - recent,
        "recent_ratio": round((recent + 1) / (n - recent + 1), 3),
    })
    return out


def run(ws: Workspace, args: argparse.Namespace) -> None:
    settings, topics = info.load(ws)
    only = {x.strip() for x in (getattr(args, "only", "") or "").split(",") if x.strip()}
    topics = [t for t in topics if not only or t.get("id") in only]
    if not topics:
        print("  no topics in config/info_topics.yaml (info_suggest proposes phrases from the seeds)")
        return
    errors, _ = info.validate(ws)
    if errors:
        raise SystemExit("config/info_topics.yaml: " + "; ".join(errors))
    score_cfg = ws.load_config(info.SCORE_FILE, {}) or {}
    measure = {**MEASURE, **(score_cfg.get("measure") or {})}
    min_videos = int((score_cfg.get("gates") or {}).get("min_videos", 10))
    lang, region = str(settings["lang"]), str(settings["region"])
    start = window_start(ws.today, settings["window_months"])
    mid = start + (ws.today - start) / 2
    after = f"{start:%Y-%m-%d}T00:00:00Z"
    yt = youtube.Client(ws, budget=getattr(args, "budget", 9000))
    classify = bool(measure.get("classify"))
    if classify and not keys.get("LLM_API_KEY"):
        classify = False
        print("  LLM_API_KEY missing: metrics over all kept Shorts, entertainment not filtered (classified 0)")
    rows, vrows, stopped = [], [], ""
    for t in topics:
        tid, qs = t["id"], info.phrases(t)
        row = {"topic_id": tid, "phrases": " | ".join(qs), "window_from": f"{start}"}
        if stopped:
            rows.append({**row, "status": "quota"})
            continue
        try:
            ids: list[str] = []
            for q in qs:
                ids += yt.search(q, lang=lang, region=region, after=after, order=measure["order"],
                                 pages=int(measure["pages"]))
            ids = list(dict.fromkeys(ids))
            videos = yt.videos(ids)
            chans = yt.channels([(v.get("snippet") or {}).get("channelId") for v in videos])
        except youtube.QuotaExceeded as e:
            stopped = str(e)
            rows.append({**row, "status": "quota"})
            print(f"  !! {tid}: {e}", flush=True)
            continue
        dropped: dict[str, int] = {}
        kept = video_rows(tid, videos, chans, measure, lang, t.get("must") or "", t.get("must_not") or "", dropped)
        kinds = video_kinds(ws, t, kept) if classify and kept else None
        for r in kept:
            r["kind"] = (kinds or {}).get(r["video_id"], "")
        teach = [r for r in kept if r["kind"] in ("T", "")]
        m = metrics(teach, measure, mid)
        # The most viewed top of a short phrase can be global: English-language hits fill it and the language filter
        # leaves a handful. That says "this phrase cannot measure the Russian top", not "the topic is thin".
        status = "ok" if teach else "empty"
        if len(kept) < min_videos and dropped.get("lang", 0) >= len(videos) / 2:
            status = "global"
        fun, off = (sum(1 for r in kept if r["kind"] == k) for k in ("E", "O"))
        rows.append({**row, "status": status, "n_found": len(ids), "dropped_lang": dropped.get("lang", 0),
                     "dropped_must": dropped.get("must", 0) + dropped.get("must_not", 0), "n_shorts": len(kept),
                     "dropped_fun": fun, "dropped_off": off, "classified": int(kinds is not None),
                     "teach_share": round(len(teach) / len(kept), 3) if kinds is not None and kept else "", **m})
        vrows += kept
        print(f"  {tid:32} found={len(ids):>3} shorts={len(kept):>3} teach={m['n_videos']:>3} "
              f"median={m.get('views_median', '-'):>9} breakout={m.get('breakout_share', '-')} "
              f"small={m.get('small_share', '-')} tg={m.get('tg_channel_share', '-')} [units {yt.used}]", flush=True)
    for name, cols, data in (("info_youtube.csv", TOPIC_COLS, rows), ("info_youtube_videos.csv", VIDEO_COLS, vrows)):
        with open(ws.out(name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in data:
                w.writerow({k: ("" if r.get(k) is None else r.get(k, "")) for k in cols})
    done = sum(1 for r in rows if r["status"] != "quota")
    print(f"-> {ws.out('info_youtube.csv')}: {done}/{len(rows)} topics measured; {yt.live} API calls, {yt.used} units")
    if stopped:
        print(f"  stopped: {stopped}. Cached topics are free on the next run.")
