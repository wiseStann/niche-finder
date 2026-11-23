"""DataForSEO client: Google Ads search volume (exact volume, CPC, competition, up to 48 months of history), Google SERP
and the AI Keyword Data index (`ai_search_volume`, modeled from Google People Also Ask).

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
COST_PER_AI_KEYWORD = 0.0001   # USD, ai_optimization/ai_keyword_data/keywords_search_volume/live
BATCH = 1000


class AccountError(RuntimeError):
    """The account cannot run paid tasks at all (status 401xx auth / verification, 402xx payment or a pause): every
    further call would fail the same way, so a stage stops instead of trying the next keyword."""


def is_account_error(code) -> bool:
    """401xx (authorisation, verification) and 402xx (payment, pause) refuse the account itself; 40102 is the one 401xx
    code about a task ('No Search Results')."""
    c = str(code or "")
    return c.startswith("402") or (c.startswith("401") and c != "40102")


def _fail(code, message: str, what: str = "DataForSEO") -> RuntimeError:
    cls = AccountError if is_account_error(code) else RuntimeError
    return cls(f"{what} {code}: {message}")


def _first_task(res: dict, what: str) -> dict:
    """The task of a one-task call. The API sometimes answers 20000 with an empty task list for one keyword (seen for
    'co parenting app' on serp/live, charged anyway): that keyword is skipped, never retried in a loop."""
    tasks = res.get("tasks") or []
    if not tasks:
        raise RuntimeError(f"{what}: the API returned no task (status {res.get('status_code')}, tasks_count {res.get('tasks_count')})")
    return tasks[0]


def _request(method: str, path: str, body=None) -> dict:
    """One API call. An account-level refusal (no tasks, e.g. 40104 'verify your account', 40200 payment) raises
    RuntimeError with the API's own message instead of failing later on the missing task list."""
    res = _raw_request(method, path, body)
    if not res.get("tasks") and res.get("status_code") != 20000:
        raise _fail(res.get("status_code"), res.get("status_message"))
    return res


def _raw_request(method: str, path: str, body=None) -> dict:
    login, pw = keys.require("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", purpose="DataForSEO search volume")
    auth = base64.b64encode(f"{login}:{pw}".encode()).decode()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        with http.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:  # firewall: retry through curl; the credentials go in through stdin (-K -), never the command line
            cmd = ["curl", "-s", "-m", "180", "-K", "-", "-H", "Content-Type: application/json", "-X", method, f"{API}{path}"]
            if data is not None:
                cmd += ["-d", data.decode("utf-8")]
            out = subprocess.run(cmd, input=f'header = "Authorization: Basic {auth}"\n', capture_output=True, text=True, encoding="utf-8").stdout
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
        if (res.get("tasks") or [{}])[0].get("status_code") == 20000:
            path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    t = _first_task(res, "DataForSEO")
    if t.get("status_code") != 20000:
        raise _fail(t.get("status_code"), t.get("status_message"))
    out = {}
    for item in t.get("result") or []:
        out[item["keyword"].lower()] = item
    return out, res.get("cost")


def ai_search_volume_cached(ws: Workspace, keywords, location_code=2840, language_code="en") -> bool:
    """True when this exact AI-volume batch is already in the cache (the call would be free)."""
    task = {"keywords": keywords, "location_code": location_code, "language_code": language_code}
    return _cache_path(ws, "aisv", task).exists()


def ai_search_volume(ws: Workspace, keywords, location_code=2840, language_code="en", use_cache=True):
    """AI Keyword Data: `ai_search_volume` and up to 12 months of `ai_monthly_searches` per keyword (<= 1000 keywords).

    DataForSEO models this index from Google's People Also Ask data, not from chatbot logs, so it is not independent
    of Google demand. Price: COST_PER_AI_KEYWORD per keyword. Russia and Belarus are not served.
    Cached as aisv_<sha1>.json. Returns ({keyword: item}, cost)."""
    assert len(keywords) <= BATCH
    task = {"keywords": keywords, "location_code": location_code, "language_code": language_code}
    path = _cache_path(ws, "aisv", task)
    if use_cache and path.exists():
        res = json.loads(path.read_text(encoding="utf-8"))
    else:
        res = _request("POST", "/ai_optimization/ai_keyword_data/keywords_search_volume/live", [task])
        if (res.get("tasks") or [{}])[0].get("status_code") == 20000:
            path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    t = _first_task(res, "DataForSEO")
    if t.get("status_code") != 20000:
        raise _fail(t.get("status_code"), t.get("status_message"), "DataForSEO AI keyword data")
    out = {}
    for block in t.get("result") or []:
        for item in (block.get("items") or [block]) if isinstance(block, dict) else []:
            if item.get("keyword"):
                out[item["keyword"].lower()] = item
    return out, res.get("cost")


COST_SERP = 0.002        # USD, serp/google/organic/live/advanced, one page of 10 results
COST_KD_TASK = 0.01      # USD per DataForSEO Labs bulk_keyword_difficulty task, plus COST_KD_KEYWORD per keyword
COST_KD_KEYWORD = 0.0001


def serp_cached(ws: Workspace, keyword, location_code=2840, language_code="en", depth=10) -> bool:
    task = {"keyword": keyword, "location_code": location_code, "language_code": language_code,
            "device": "desktop", "os": "windows", "depth": depth}
    return _cache_path(ws, "serp", task).exists()


def keyword_difficulty(ws: Workspace, keywords, location_code=2840, language_code="en", use_cache=True):
    """DataForSEO Labs bulk keyword difficulty (0-100, from the link profiles of the top-10 pages), up to 1000 keywords
    per task. Cached as kd_<sha1>.json. Returns ({keyword: difficulty}, cost)."""
    assert len(keywords) <= BATCH
    task = {"keywords": keywords, "location_code": location_code, "language_code": language_code}
    path = _cache_path(ws, "kd", task)
    if use_cache and path.exists():
        res = json.loads(path.read_text(encoding="utf-8"))
    else:
        res = _request("POST", "/dataforseo_labs/google/bulk_keyword_difficulty/live", [task])
        if (res.get("tasks") or [{}])[0].get("status_code") == 20000:
            path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    t = _first_task(res, "DataForSEO")
    if t.get("status_code") != 20000:
        raise _fail(t.get("status_code"), t.get("status_message"), "DataForSEO keyword difficulty")
    out = {}
    for block in t.get("result") or []:
        for it in block.get("items") or []:
            if it.get("keyword") is not None and it.get("keyword_difficulty") is not None:
                out[it["keyword"].lower()] = it["keyword_difficulty"]
    return out, res.get("cost")


def keyword_difficulty_cached(ws: Workspace, keywords, location_code=2840, language_code="en") -> bool:
    return _cache_path(ws, "kd", {"keywords": keywords, "location_code": location_code, "language_code": language_code}).exists()


def serp(ws: Workspace, keyword, location_code=2840, language_code="en", depth=10, use_cache=True):
    """Google SERP (advanced: organic + paid blocks). Cached as serp_<sha1>.json. Returns (items, cost)."""
    task = {"keyword": keyword, "location_code": location_code, "language_code": language_code,
            "device": "desktop", "os": "windows", "depth": depth}
    path = _cache_path(ws, "serp", task)
    if use_cache and path.exists():
        res = json.loads(path.read_text(encoding="utf-8"))
    else:
        res = _request("POST", "/serp/google/organic/live/advanced", [task])
        if (res.get("tasks") or [{}])[0].get("status_code") == 20000:
            path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    t = _first_task(res, "DataForSEO")
    if t.get("status_code") != 20000:
        raise _fail(t.get("status_code"), t.get("status_message"), "DataForSEO serp")
    items = (t["result"] or [{}])[0].get("items") or []
    return items, t.get("cost", 0)
