"""Short-video metrics for each info topic (YouTube Data API): attention, room for newcomers, Telegram funnels, offers.

For every phrase of a topic: one search page of the 50 most viewed videos (measure.order, default viewCount) under
4 minutes published in the window (relevanceLanguage and regionCode from config/info_topics.yaml), then video and
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

Input: config/info_topics.yaml, config/score_info.yaml (`measure`). Output: data/out/info_youtube.csv (per topic),
data/out/info_youtube_videos.csv (per video). Cache: data/cache/youtube/. Key: YOUTUBE_API_KEY. Cost: free quota of
10,000 units per day; about 100 units per phrase plus 2-4 for statistics, so about 90 one-phrase or 45 two-phrase
topics a day. A run stopped by the quota keeps what it measured; re-run the next day and the cached topics cost nothing.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
import statistics

from nichefinder import info
from nichefinder.sources import youtube
from nichefinder.workspace import Workspace

SUMMARY = "Short-video metrics per info topic (YouTube Data API)"
KEYS: tuple[str, ...] = ("YOUTUBE_API_KEY",)
NEEDS: tuple[str, ...] = ()

MEASURE = {
    "order": "viewCount", "shorts_max_seconds": 180, "breakout_ratio": 10, "breakout_min_views": 10000,
    "small_channel_subs": 10000, "tg_pattern": r"(?:t\.me|telegram\.me|telegram\.dog)/|telegram|\btg\b",
    "offer_pattern": r"guide|checklist|course|template|ebook|workshop|webinar|coaching",
}
CYRILLIC = re.compile("[\u0400-\u04FF]")
HASHTAG = re.compile(r"#\w+")
DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
TOPIC_COLS = ["topic_id", "status", "phrases", "n_found", "n_videos", "n_channels", "views_median", "views_p90",
              "subs_median", "breakout_share", "small_share", "top3_share", "tg_channel_share",
              "tg_video_share", "offer_share", "recent", "older", "recent_ratio", "window_from"]
VIDEO_COLS = ["topic_id", "video_id", "published", "seconds", "views", "likes", "comments", "channel_id",
              "channel_title", "subs", "breakout", "small", "tg", "offer", "title"]


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
               must: str = "", must_not: str = "") -> list[dict]:
    """Kept videos of one topic with their channel and the per-video flags."""
    tg = re.compile(measure["tg_pattern"], re.I)
    offer = re.compile(measure["offer_pattern"], re.I)
    need = re.compile(must, re.I) if must else None
    drop = re.compile(must_not, re.I) if must_not else None
    ch = {c["id"]: c for c in channels}
    rows = []
    for v in videos:
        sn, st = v.get("snippet") or {}, v.get("statistics") or {}
        sec = seconds((v.get("contentDetails") or {}).get("duration", ""))
        views = _int(st.get("viewCount"))
        title = sn.get("title") or ""
        desc = sn.get("description") or ""
        if views is None or not 0 < sec <= measure["shorts_max_seconds"]:
            continue
        if lang == "ru" and not CYRILLIC.search(title):
            continue
        if need and not need.search(HASHTAG.sub(" ", title + "\n" + desc)):
            continue
        if drop and drop.search(title + "\n" + desc):
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
            "title": title,
        })
    return rows


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
    measure = {**MEASURE, **((ws.load_config(info.SCORE_FILE, {}) or {}).get("measure") or {})}
    lang, region = str(settings["lang"]), str(settings["region"])
    start = window_start(ws.today, settings["window_months"])
    mid = start + (ws.today - start) / 2
    after = f"{start:%Y-%m-%d}T00:00:00Z"
    yt = youtube.Client(ws, budget=getattr(args, "budget", 9000))
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
                ids += yt.search(q, lang=lang, region=region, after=after, order=measure["order"])
            ids = list(dict.fromkeys(ids))
            videos = yt.videos(ids)
            chans = yt.channels([(v.get("snippet") or {}).get("channelId") for v in videos])
        except youtube.QuotaExceeded as e:
            stopped = str(e)
            rows.append({**row, "status": "quota"})
            print(f"  !! {tid}: {e}", flush=True)
            continue
        kept = video_rows(tid, videos, chans, measure, lang, t.get("must") or "", t.get("must_not") or "")
        m = metrics(kept, measure, mid)
        rows.append({**row, "status": "ok" if kept else "empty", "n_found": len(ids), **m})
        vrows += kept
        print(f"  {tid:32} found={len(ids):>3} shorts={m['n_videos']:>3} median={m.get('views_median', '-'):>9} "
              f"breakout={m.get('breakout_share', '-')} small={m.get('small_share', '-')} "
              f"tg={m.get('tg_channel_share', '-')} [units {yt.used}]", flush=True)
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
