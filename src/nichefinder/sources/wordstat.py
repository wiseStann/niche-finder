"""Yandex Wordstat API v2 client with a disk cache and a wait on the request quota (about 100 requests per hour).

Key: YANDEX_API_KEY (environment or workspace .env), required only when a request is not in the cache.
Cache: data/cache/wordstat/<kind>_<sha1>.json, where <kind> is the API method (topRequests, dynamics)
and the hash covers the canonical request body.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time

from nichefinder import http, keys
from nichefinder.workspace import Workspace

API = "https://searchapi.api.cloud.yandex.net/v2/wordstat"


def _call(path: str, body: dict) -> dict:
    (key,) = keys.require("YANDEX_API_KEY", purpose="Yandex Wordstat requests")
    try:
        r = http.request(f"{API}/{path}", method="POST", data=body, headers={"Authorization": f"Api-Key {key}"},
                         timeout=30, tries=1, raise_for_status=False)
    except (OSError, TimeoutError) as e:
        return {"_error": "network", "_body": str(e)[:200]}
    if r.status >= 400:
        return {"_error": r.status, "_body": r.text[:300]}
    return r.json()


def cached(ws: Workspace, kind: str, body: dict, log=None):
    """Cached API call. Returns (response, from_cache). Waits and retries on quota (429) and network errors."""
    key = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = ws.cache("wordstat") / f"{kind}_{key}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), True
    waited = 0
    while True:
        res = _call(kind, body)
        if res.get("_error") == 429 or (res.get("_error") == "network" and waited < 600):
            if log:
                log(f"  quota/network: waiting 120 s (waited {waited // 60} min)")
            time.sleep(120)
            waited += 120
            if waited > 75 * 60:
                return res, False
            continue
        break
    if "_error" not in res:
        path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.3)
    return res, False


def top_requests(ws: Workspace, phrase: str, num: int = 50, regions=None, log=None):
    body: dict = {"phrase": phrase, "numPhrases": num}
    if regions:
        body["regions"] = [str(r) for r in regions]
    return cached(ws, "topRequests", body, log)


def dynamics(ws: Workspace, phrase: str, months: int = 36, log=None):
    """Monthly counts for the `months` full months before the run date (ws.today)."""
    last_full = ws.today.replace(day=1) - dt.timedelta(days=1)
    y, m = last_full.year, last_full.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    body = {"phrase": phrase, "period": "PERIOD_MONTHLY",
            "fromDate": dt.date(y, m, 1).isoformat() + "T00:00:00Z", "toDate": last_full.isoformat() + "T23:59:59Z"}
    return cached(ws, "dynamics", body, log)
