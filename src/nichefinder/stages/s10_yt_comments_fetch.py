"""YouTube comments under each niche's how-to and review videos: buyer voice, Russian by default (--lang en: US English).

Niches: shortlisted niches whose geo includes the language's market (ru: geo both or ru, plus the shortlist tier `ru`;
en: geo global or both).
Phrases per niche, taken from its queries in the order of `fetch.phrases`: anchor = the anchor query, problem = the
first problem query, category = the first other category query, brand = the first brand query plus
`fetch.brand_suffix` ("review"). The next phrase is searched only while fewer than `fetch.min_videos` relevant videos
are found, and at most `fetch.max_phrases` phrases per niche.
Per phrase: one search.list page (50 videos, 100 units) with relevanceLanguage and regionCode, any duration, order
relevance, published from the first day of the month `fetch.window_months` before the run month (the same request
for every run in one month, so a re-run hits the cache), then videos.list statistics (1 unit per 50 videos).
Candidates: videos with at least `fetch.min_video_comments` comments and, for ru, a Cyrillic title (for en, none).
An LLM video check (LLM_API_KEY; one cached call per phrase) sees the `fetch.check_candidates` most commented
candidates with the niche (who, task, product) and keeps the videos whose viewers are the niche's buyers: how-to
videos for the task; reviews, comparisons and tutorials of its products; stories about the problem. It drops
entertainment, news, homonyms and videos for another audience. Why: a phrase such as "fitness club program" also
finds workout programs, and a prayer phrase finds prayers with thousands of one-word comments. Without the key every
candidate counts and the fetch table says so (`by` = none).
Picked: the `fetch.videos` relevant videos with the most comments. Comments: commentThreads.list, order relevance,
plain text, 100 top-level comments a page (1 unit), up to `fetch.pages_per_video` pages per video. Replies are not
read; comments by the video's own channel (pinned links, the author's answers) are dropped; for ru only comments with
Cyrillic letters are kept, for en only comments without them.

Quota: the daily 10,000 units shared with info_youtube (and its limit of 100 search calls a day). --budget caps the
units this run spends on uncached calls (default 3000: about 25 niches at one phrase each). Every response is cached
in data/cache/youtube/, so a run stopped by the budget or the daily quota resumes from the cache the next day. A niche
the budget did not reach is marked `quota` and keeps its rows from an earlier run. Comment pages are cached by URL
without a date: a later month searches again but reads the comments of a video it already read from the cache.

Output (with --lang en the names end in _en):
  data/out/yt_comments_docs.jsonl   per comment: niche_id, lang, phrase, video_id, video, channel, id, date, likes,
                                    replies, text
  data/out/yt_comments_videos.csv   per candidate video: views, likes, comments, the LLM check (fit, why), picked,
                                    comments read and kept
  data/out/yt_comments_fetch.csv    per niche: phrases searched, candidates, relevant, picked, comments, status
                                    (ok, no videos, check failed, quota)
Settings: config/yt_comments.yaml (`fetch`). Keys: YOUTUBE_API_KEY; LLM_API_KEY for the video check.
Usage: nf run s10_yt_comments_fetch -- [--lang ru|en] [--niches a,b] [--budget 3000]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import time
import urllib.parse
from pathlib import Path

from nichefinder import http, keys, llm, niches
from nichefinder.sources import youtube
from nichefinder.workspace import Workspace

SUMMARY = "YouTube comments under each niche's how-to and review videos (buyer voice; Russian, --lang en for English)"
KEYS: tuple[str, ...] = ("YOUTUBE_API_KEY",)
NEEDS: tuple[str, ...] = ()

CONFIG = "yt_comments.yaml"
CYR = re.compile("[Ѐ-ӿ]")
LAT = re.compile("[A-Za-z]")
MARKET = {"ru": {"region": "RU", "geo": ("both", "ru")}, "en": {"region": "US", "geo": ("global", "both")}}
DOCS, VIDEOS, FETCH = "yt_comments_docs.jsonl", "yt_comments_videos.csv", "yt_comments_fetch.csv"
VIDEO_COLS = ["niche_id", "lang", "phrase", "intent", "video_id", "title", "channel", "published", "views", "likes", "comments",
              "fit", "why", "picked", "read", "kept", "status"]
FETCH_COLS = ["niche_id", "lang", "phrases", "searched", "candidates", "relevant", "picked", "comments", "by", "status"]
DEFAULTS = {
    "fetch": {"window_months": 36, "phrases": ["anchor", "problem", "brand"], "max_phrases": 2, "min_videos": 3, "videos": 5,
              "min_video_comments": 20, "pages_per_video": 3, "check_candidates": 30, "video_check": True,
              "brand_suffix": {"ru": "обзор", "en": "review"}},
    "sample": {"max_comments": 300, "min_chars": 25},
    "verdict": {"min_niche_comments": 60, "min_videos": 2, "min_cohort": 6, "gap_pct": 0.67, "gap_floor": 0.10,
                "pain_pct": 0.67, "pain_floor": 0.20, "seek_pct": 0.67, "seek_floor": 0.12, "howto_pct": 0.67,
                "howto_floor": 0.20, "content_praise": 0.25, "top_video_warn": 0.60},
}
CHECK_SYSTEM = (
    "You pick YouTube videos whose comment sections carry the voice of a market niche's buyers. A niche is who x task x product. "
    "You get the niche, the search phrase and a numbered list of videos (title | channel | comments | start of the description). "
    "For each video decide fit: yes = most viewers are people who do this task or would buy this kind of product: a how-to or "
    "tutorial for the task, a review, comparison or tutorial of a product or tool for it, a complaint about one, a story or "
    "discussion of the problem these users have; no = anything else: entertainment, music, sketches, news, politics, a homonym "
    "(the words mean something else here), a video where the task is only a passing mention, content made for another audience "
    "than these users (shoppers or clients when the niche serves the business). "
    'Output JSON: {"videos": [{"k": <number>, "fit": "yes" or "no", "why": "<5-12 words>"}]} with every number.')


def settings(ws: Workspace, section: str) -> dict:
    """One block of config/yt_comments.yaml over the defaults; the file is optional."""
    cfg = ws.load_config(CONFIG, {}) or {}
    return {**DEFAULTS[section], **(cfg.get(section) or {})}


def config_status(ws: Workspace) -> str:
    return str((ws.load_config(CONFIG, {}) or {}).get("status") or "draft")


def default_lang(ws: Workspace) -> str:
    return "ru" if "ru" in ws.markets else "en"


def lang_of(ws: Workspace, args: argparse.Namespace) -> str:
    lang = (getattr(args, "lang", "") or default_lang(ws)).lower()
    if lang not in MARKET:
        raise SystemExit(f"--lang must be one of {sorted(MARKET)}")
    return lang


def out_name(name: str, lang: str) -> str:
    """File name for a language: Russian keeps the base name, English adds _en (-en for the report)."""
    if lang == "ru":
        return name
    stem, dot, ext = name.rpartition(".")
    return f"{stem}{'-' if stem.startswith('S10-') else '_'}{lang}.{ext}" if dot else f"{name}_{lang}"


def target_niches(ws: Workspace, lang: str, only: str = "") -> list[str]:
    """Shortlisted niches whose geo includes the language's market, optionally restricted to a comma-separated list."""
    geo = {n["id"]: n.get("geo", "global") for n in niches.load_niches(ws)}
    ids = [i for i in niches.shortlist_ids(ws, ru=lang == "ru") if geo.get(i) in MARKET[lang]["geo"]]
    wanted = {x.strip() for x in only.split(",") if x.strip()}
    return [i for i in ids if i in wanted] if wanted else ids


def window_start(today: dt.date, months: int) -> dt.date:
    """First day of the month `months` before the run month: one request for every run in a month (cache hits)."""
    y, m = today.year, today.month - int(months)
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, 1)


def text_ok(text: str, lang: str) -> bool:
    return bool(CYR.search(text)) if lang == "ru" else bool(LAT.search(text)) and not CYR.search(text)


def phrases(rows: list[dict], order: list[str], suffix: str) -> list[tuple[str, str]]:
    """(token, phrase) per token of `order`; each query is used once. rows: niches.keyword_rows() of one niche."""
    out: list[tuple[str, str]] = []
    used: set[str] = set()
    for tok in order:
        if tok == "anchor":
            cand = [r for r in rows if r["anchor"]]
        elif tok == "brand":
            cand = [r for r in rows if r["intent"] == "brand"]
        else:
            cand = [r for r in rows if r["intent"] == tok and not r["anchor"]]
        for r in cand:
            if r["q"] in used:
                continue
            used.add(r["q"])
            out.append((tok, f"{r['q']} {suffix}".strip() if tok == "brand" else r["q"]))
            break
    return out


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


COST = {"search": 100, "videos": 1, "channels": 1, "commentThreads": 1}
NO_COMMENTS = {"commentsdisabled": "comments disabled", "videonotfound": "video not found", "forbidden": "forbidden"}


def api_reason(body: str) -> str:
    """The `reason` and the message of a YouTube API error body, for logs (the key is in a header, never in the body)."""
    try:
        err = json.loads(body).get("error") or {}
        return f"{','.join(x.get('reason', '') for x in err.get('errors') or [])}: {str(err.get('message', ''))[:160]}"
    except (ValueError, AttributeError):
        return (body or "")[:160]


class Client(youtube.Client):
    """youtube.Client plus commentThreads.list (1 unit a page of up to 100 top-level comments), with the same key
    header, cache and budget. Two differences in error handling. A video with comments turned off answers 403
    commentsDisabled: that answer is cached as an empty page, so a re-run does not pay for it again. A per-minute rate
    limit also answers 403/429 with "quota" in the text: it waits a minute and retries instead of stopping the run as if
    the daily quota were spent. A real stop carries the API's reason: the 10,000 daily units (quotaExceeded) or the
    separate "Search Queries per day" limit, after which cached searches and comment pages still work."""

    wait_s = 65

    def _get(self, method: str, params: dict) -> dict:
        url = f"{youtube.API}/{method}?{urllib.parse.urlencode(params)}"
        path = http.cache_file(self.cache, url)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.used + COST[method] > self.budget:
            raise youtube.QuotaExceeded(f"the run budget of {self.budget} units is spent")
        (key,) = keys.require("YOUTUBE_API_KEY", purpose="YouTube Data API requests")
        for attempt in range(4):
            try:
                data = http.request(url, headers={"X-Goog-Api-Key": key}, timeout=30, tries=2).json()
                break
            except http.HttpError as e:
                body = (e.body or "").lower()
                # reason rateLimitExceeded covers both "Search Queries per minute" and "per day": only the first is worth a wait
                minute = ("per minute" in body or "per 100 seconds" in body) and "per day" not in body
                if e.status in (403, 429) and minute and attempt < 3:
                    print(f"    rate limit ({api_reason(e.body)}); waiting {self.wait_s} s", flush=True)
                    time.sleep(self.wait_s)
                    continue
                if e.status in (403, 429) and ("quota" in body or minute):
                    raise youtube.QuotaExceeded(f"YouTube API quota: {api_reason(e.body)}") from None
                reason = next((r for r in NO_COMMENTS if r in body), "")
                if method != "commentThreads" or e.status not in (403, 404) or not reason:
                    raise
                data = {"items": [], "_status": NO_COMMENTS[reason]}
                break
        self.used += COST[method]
        self.live += 1
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def _comments_page(self, params: dict) -> dict:
        return self._get("commentThreads", params)

    def comment_threads(self, video_id: str, *, pages: int, order: str = "relevance") -> tuple[list[dict], str]:
        """Top-level comment threads of a video: up to `pages` pages of 100. Returns (items, status)."""
        params = {"part": "snippet", "videoId": video_id, "maxResults": 100, "order": order, "textFormat": "plainText"}
        items: list[dict] = []
        for _ in range(max(1, pages)):
            data = self._comments_page(params)
            if data.get("_status"):
                return items, data["_status"]
            items += data.get("items", [])
            if not data.get("nextPageToken"):
                break
            params = {**params, "pageToken": data["nextPageToken"]}
        return items, "ok"


def candidates(videos: list[dict], lang: str, min_comments: int) -> list[dict]:
    """Video rows with enough comments and a title in the language, most commented first."""
    out = []
    for v in videos:
        sn, st = v.get("snippet") or {}, v.get("statistics") or {}
        title = sn.get("title") or ""
        if _int(st.get("commentCount")) < min_comments or not text_ok(title, lang):
            continue
        out.append({"video_id": v.get("id"), "title": title, "channel": sn.get("channelTitle") or "", "channel_id": sn.get("channelId") or "",
                    "published": (sn.get("publishedAt") or "")[:10], "views": _int(st.get("viewCount")), "likes": _int(st.get("likeCount")),
                    "comments": _int(st.get("commentCount")), "desc": (sn.get("description") or "")[:160].replace("\n", " ")})
    return sorted(out, key=lambda r: -r["comments"])


def video_check(ws: Workspace, niche: dict, phrase: str, cands: list[dict]) -> dict[str, tuple[str, str]] | None:
    """The LLM video check: video_id -> (fit, why); None when the model gave no answer."""
    lines = [f"{k}: {c['title']} | {c['channel']} | {c['comments']} comments | {c['desc']}" for k, c in enumerate(cands, 1)]
    user = (f"Niche: {niche.get('name') or niche['id']}\nWho: {niche.get('who', '')}\nTask: {niche.get('task', '')}\n"
            f"Product: {niche.get('product', '')}\nSearch phrase: {phrase}\n\nVideos:\n" + "\n".join(lines))
    content, _, _ = llm.chat_json(ws, [{"role": "system", "content": CHECK_SYSTEM}, {"role": "user", "content": user}],
                                  max_tokens=3000, temperature=0.0)
    if not content:
        return None
    out: dict[str, tuple[str, str]] = {}
    for it in content.get("videos") or []:
        k = _int(it.get("k"))
        if 1 <= k <= len(cands):
            out[cands[k - 1]["video_id"]] = ("yes" if str(it.get("fit")).lower() == "yes" else "no", str(it.get("why") or "")[:120])
    return out


def comment_docs(nid: str, lang: str, phrase: str, video: dict, items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        sn = ((it.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
        text = (sn.get("textDisplay") or sn.get("textOriginal") or "").strip()
        author = (sn.get("authorChannelId") or {}).get("value", "")
        if not text or not text_ok(text, lang) or (author and author == video.get("channel_id")):
            continue
        out.append({"niche_id": nid, "lang": lang, "phrase": phrase, "video_id": video["video_id"], "video": video["title"],
                    "channel": video["channel"], "id": it.get("id", ""), "date": (sn.get("publishedAt") or "")[:10],
                    "likes": _int(sn.get("likeCount")), "replies": _int((it.get("snippet") or {}).get("totalReplyCount")), "text": text[:1500]})
    return out


def read_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    if path.suffix == ".jsonl":
        return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    return list(csv.DictReader(open(path, encoding="utf-8")))


def write_merged(path: Path, rows: list[dict], keep_old: set[str], cols: list[str] | None = None) -> None:
    """Write this run's rows plus the earlier rows of the niches in `keep_old` (not refreshed in this run)."""
    old = [r for r in read_rows(path) if r.get("niche_id") in keep_old]
    out = old + rows
    if path.suffix == ".jsonl":
        with open(path, "w", encoding="utf-8") as fh:
            for r in out:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lang", default="", choices=["", "ru", "en"], help="ru (default when nf.yaml markets include ru) or en")
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: the shortlisted niches of the language)")
    parser.add_argument("--budget", type=int, default=3000, help="max quota units for uncached calls in this run (daily quota: 10,000)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    lang = lang_of(ws, args)
    cfg = settings(ws, "fetch")
    ids = target_niches(ws, lang, getattr(args, "niches", "") or "")
    if not ids:
        print(f"  no shortlisted niches with geo {' or '.join(MARKET[lang]['geo'])} for --lang {lang}")
        return
    by_id = {n["id"]: n for n in niches.load_niches(ws)}
    rows = niches.keyword_rows(ws, lang)
    region = MARKET[lang]["region"]
    after = f"{window_start(ws.today, cfg['window_months']):%Y-%m-%d}T00:00:00Z"
    suffix = (cfg.get("brand_suffix") or {}).get(lang, "")
    check = bool(cfg.get("video_check"))
    if check and not keys.get("LLM_API_KEY"):
        check = False
        print("  LLM_API_KEY missing: no video check, every candidate with enough comments counts (by = none)")
    budget = getattr(args, "budget", None)
    yt = Client(ws, budget=3000 if budget is None else int(budget))
    docs_out, videos_out, fetch_out, stopped = [], [], [], ""
    print(f"  --lang {lang}: {len(ids)} niches, region {region}, published after {after[:10]}, budget {yt.budget} units")
    for nid in ids:
        n = by_id[nid]
        plan = phrases([r for r in rows if r["niche_id"] == nid], list(cfg["phrases"]), suffix)[:int(cfg["max_phrases"])]
        frow = {"niche_id": nid, "lang": lang, "phrases": " | ".join(q for _, q in plan), "searched": "", "candidates": 0, "relevant": 0,
                "picked": 0, "comments": 0, "by": "llm" if check else "none", "status": "ok"}
        if not plan:
            fetch_out.append({**frow, "status": "no phrases"})
            continue
        vrows: list[dict] = []
        ndocs: list[dict] = []
        seen: set[str] = set()
        searched: list[str] = []
        try:
            for tok, q in plan:
                if sum(1 for v in vrows if v["fit"] == "yes") >= int(cfg["min_videos"]):
                    break
                searched.append(q)
                cands = [c for c in candidates(yt.videos(yt.search(q, lang=lang, region=region, after=after, duration="any")),
                                               lang, int(cfg["min_video_comments"])) if c["video_id"] not in seen]
                cands = cands[:int(cfg["check_candidates"])]
                seen.update(c["video_id"] for c in cands)
                fit = video_check(ws, n, q, cands) if check and cands else {c["video_id"]: ("yes", "") for c in cands}
                if fit is None:
                    frow["status"] = "check failed"
                    print(f"  !! {nid}: the LLM video check gave no answer for '{q}'; re-run to retry")
                    break
                for c in cands:
                    f_, why = fit.get(c["video_id"], ("no", "no answer"))
                    vrows.append({"niche_id": nid, "lang": lang, "phrase": q, "intent": tok, **c, "fit": f_, "why": why,
                                  "picked": 0, "read": 0, "kept": 0, "status": ""})
            frow["searched"] = " | ".join(searched)
            relevant = sorted((v for v in vrows if v["fit"] == "yes"), key=lambda v: -v["comments"])
            for v in relevant[:int(cfg["videos"])]:
                items, st = yt.comment_threads(v["video_id"], pages=int(cfg["pages_per_video"]))
                got = comment_docs(nid, lang, v["phrase"], v, items)
                v.update({"picked": 1, "read": len(items), "kept": len(got), "status": st})
                ndocs += got
        except youtube.QuotaExceeded as e:
            if not stopped:
                stopped = str(e)
                print(f"  !! {nid}: {e}; the remaining niches are read from the cache only")
                yt.budget = yt.used          # no further network calls in this run
            fetch_out.append({**frow, "searched": " | ".join(searched), "status": "quota"})
            continue
        frow.update({"candidates": len(vrows), "relevant": sum(1 for v in vrows if v["fit"] == "yes"),
                     "picked": sum(v["picked"] for v in vrows), "comments": len(ndocs)})
        if frow["status"] == "ok" and not frow["picked"]:
            frow["status"] = "no videos"
        fetch_out.append(frow)
        videos_out += vrows
        docs_out += ndocs
        print(f"  {nid:36} {frow['searched'][:60]:60} cand {frow['candidates']:>2} rel {frow['relevant']:>2} picked {frow['picked']} "
              f"comments {frow['comments']:>4} {frow['status']} [units {yt.used}]", flush=True)
    # Earlier rows survive for the niches the budget did not reach and, in a run with --niches, for the other niches.
    old_fetch = read_rows(ws.out(out_name(FETCH, lang)))
    old_niches = {r.get("niche_id") for r in old_fetch}
    old_data = {r.get("niche_id") for r in old_fetch if r.get("status") != "quota"}
    quota = {r["niche_id"] for r in fetch_out if r["status"] == "quota"}
    keep_old = (quota & old_niches) | (old_niches - set(ids) if getattr(args, "niches", "") else set())
    write_merged(ws.out(out_name(DOCS, lang)), docs_out, keep_old)
    write_merged(ws.out(out_name(VIDEOS, lang)), videos_out, keep_old, VIDEO_COLS)
    write_merged(ws.out(out_name(FETCH, lang)), [r for r in fetch_out if r["niche_id"] not in keep_old], keep_old, FETCH_COLS)
    st: dict[str, int] = {}
    for r in fetch_out:
        st[r["status"]] = st.get(r["status"], 0) + 1
    print(f"-> {out_name(DOCS, lang)}: {len(docs_out)} comments from {sum(v['picked'] for v in videos_out)} videos; niches {st}; "
          f"{yt.live} API calls, {yt.used} units" + (f"; stopped: {stopped}" if stopped else "")
          + (f"; {len(quota & old_data)} niches not reached keep their earlier data" if quota & old_data else ""))
