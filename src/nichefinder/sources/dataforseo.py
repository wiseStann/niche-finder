"""DataForSEO client: Google Ads search volume (exact volume, CPC, competition, up to 48 months of history) and Google SERP.

Credentials: DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD (workspace .env or environment).
Cache: data/cache/dfs/sv_<sha1>.json and serp_<sha1>.json, keyed by the request body, so re-runs are free.
Price: about $0.09 per search-volume call of up to 1000 keywords. The API firewall blocks the default urllib
user agent, so a custom one is sent; on HTTP 403 the request is retried through curl.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from nichefinder import http, keys
from nichefinder.workspace import Workspace

API = "https://api.dataforseo.com/v3"
UA = http.BOT_UA
COST_PER_CALL = 0.09     # USD, search_volume/live with up to 1000 keywords
BATCH = 1000


def _request(method: str, path: str, body=None) -> dict:
    login, pw = keys.require("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", purpose="DataForSEO search volume")
    auth = base64.b64encode(f"{login}:{pw}".encode()).decode()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:  # firewall: retry through curl
            cmd = ["curl", "-s", "-m", "180", "-u", f"{login}:{pw}", "-H", "Content-Type: application/json", "-X", method, f"{API}{path}"]
            if data is not None:
                cmd += ["-d", data.decode("utf-8")]
            out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8").stdout
            return json.loads(out)
        raise


def balance() -> float:
    res = _request("GET", "/appendix/user_data")
    return res["tasks"][0]["result"][0]["money"]["balance"]


def _cache_path(ws: Workspace, prefix: str, task: dict) -> Path:
    key = hashlib.sha1(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return ws.cache("dfs") / f"{prefix}_{key}.json"


def search_volume_task(keywords, location_code=None, language_code=None, date_from=None) -> dict:
    task = {"keywords": keywords, "search_partners": False}
    if location_code:
        task["location_code"] = location_code
    if language_code:
        task["language_code"] = language_code
    if date_from:
        task["date_from"] = date_from
    return task


def search_volume_cached(ws: Workspace, keywords, location_code=None, language_code=None, date_from=None) -> bool:
    """True when this exact batch is already in the cache (the call would be free)."""
    return _cache_path(ws, "sv", search_volume_task(keywords, location_code, language_code, date_from)).exists()


def search_volume(ws: Workspace, keywords, location_code=None, language_code=None, date_from=None, use_cache=True):
    """keywords <= 1000. Returns ({keyword: item as in the DataForSEO response}, cost)."""
    assert len(keywords) <= BATCH
    task = search_volume_task(keywords, location_code, language_code, date_from)
    path = _cache_path(ws, "sv", task)
    if use_cache and path.exists():
        res = json.loads(path.read_text(encoding="utf-8"))
    else:
        res = _request("POST", "/keywords_data/google_ads/search_volume/live", [task])
        if res["tasks"][0].get("status_code") == 20000:
            path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    t = res["tasks"][0]
    if t.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO: {t.get('status_code')} {t.get('status_message')}")
    out = {}
    for item in t.get("result") or []:
        out[item["keyword"].lower()] = item
    return out, res.get("cost")


def serp(ws: Workspace, keyword, location_code=2840, language_code="en", depth=10, use_cache=True):
    """Google SERP (advanced: organic + paid blocks). Cached as serp_<sha1>.json. Returns (items, cost)."""
    task = {"keyword": keyword, "location_code": location_code, "language_code": language_code,
            "device": "desktop", "os": "windows", "depth": depth}
    path = _cache_path(ws, "serp", task)
    if use_cache and path.exists():
        res = json.loads(path.read_text(encoding="utf-8"))
    else:
        res = _request("POST", "/serp/google/organic/live/advanced", [task])
        if res["tasks"][0].get("status_code") == 20000:
            path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    t = res["tasks"][0]
    if t.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO serp {t.get('status_code')}: {t.get('status_message')}")
    items = (t["result"] or [{}])[0].get("items") or []
    return items, t.get("cost", 0)
