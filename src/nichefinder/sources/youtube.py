"""YouTube Data API v3: video search, video and channel statistics. Key: YOUTUBE_API_KEY.

    from nichefinder.sources import youtube
    yt = youtube.Client(ws, budget=9000)
    ids = yt.search("how to sell on avito", lang="ru", region="RU", after="2025-11-01T00:00:00Z")
    videos = yt.videos(ids)            # snippet, statistics, contentDetails
    channels = yt.channels([v["snippet"]["channelId"] for v in videos])

The key travels in the X-Goog-Api-Key header, never in the URL, so cache file names, logs and error messages never
carry it. Quota: 10,000 units per day by default, reset at midnight Pacific time. search.list costs 100 units per
page, videos.list and channels.list 1 unit per call of up to 50 ids. Every response is cached in
data/cache/youtube/ by its URL, so a run stopped by the quota resumes from the cache the next day, and `budget`
caps the units one run may spend on uncached calls.
"""
from __future__ import annotations

import json
import urllib.parse

from nichefinder import http, keys
from nichefinder.workspace import Workspace

API = "https://www.googleapis.com/youtube/v3"
COST = {"search": 100, "videos": 1, "channels": 1}
BATCH = 50


class QuotaExceeded(Exception):
    """The run budget or the daily API quota is spent; cached calls still work."""


class Client:
    def __init__(self, ws: Workspace, budget: int = 9000):
        self.cache = ws.cache("youtube")
        self.budget = budget
        self.used = 0        # units spent on uncached calls in this run
        self.live = 0        # uncached calls in this run

    def _get(self, method: str, params: dict) -> dict:
        url = f"{API}/{method}?{urllib.parse.urlencode(params)}"
        path = http.cache_file(self.cache, url)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.used + COST[method] > self.budget:
            raise QuotaExceeded(f"the run budget of {self.budget} units is spent")
        (key,) = keys.require("YOUTUBE_API_KEY", purpose="YouTube Data API requests")
        try:
            data = http.request(url, headers={"X-Goog-Api-Key": key}, timeout=30).json()
        except http.HttpError as e:
            # 403 quotaExceeded for the unit pool; 429 "Search Queries per day" for the separate search bucket
            if e.status in (403, 429) and "quota" in e.body.lower():
                raise QuotaExceeded("the daily YouTube API quota is spent; re-run after midnight Pacific time") from None
            raise
        self.used += COST[method]
        self.live += 1
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def search(self, q: str, *, lang: str, region: str, after: str, duration: str = "short",
               order: str = "relevance", n: int = 50, pages: int = 1) -> list[str]:
        """Video ids for a phrase: `pages` pages of up to 50 results each (100 units a page), published after `after`
        (RFC 3339). duration "short" is YouTube's under-4-minutes filter; there is no Shorts-only filter in the API.
        The first page's request is the same for any `pages`, so a deeper run reuses its cache."""
        params = {
            "part": "snippet", "type": "video", "q": q, "maxResults": n, "order": order, "publishedAfter": after,
            "relevanceLanguage": lang, "regionCode": region, "videoDuration": duration, "safeSearch": "none",
        }
        ids: list[str] = []
        for _ in range(max(1, pages)):
            data = self._get("search", params)
            ids += [it["id"]["videoId"] for it in data.get("items", []) if (it.get("id") or {}).get("videoId")]
            if not data.get("nextPageToken"):
                break
            params = {**params, "pageToken": data["nextPageToken"]}
        return ids

    def _batched(self, method: str, part: str, ids: list[str]) -> list[dict]:
        out: list[dict] = []
        uniq = list(dict.fromkeys(i for i in ids if i))
        for i in range(0, len(uniq), BATCH):
            chunk = uniq[i:i + BATCH]
            data = self._get(method, {"part": part, "id": ",".join(chunk), "maxResults": BATCH})
            out += data.get("items", [])
        return out

    def videos(self, ids: list[str]) -> list[dict]:
        return self._batched("videos", "snippet,statistics,contentDetails", ids)

    def channels(self, ids: list[str]) -> list[dict]:
        return self._batched("channels", "snippet,statistics", ids)
