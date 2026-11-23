"""VK API client: POST calls with the token in the body (never in a URL or a cache key), a month disk cache and the
two VK tokens.

Keys (workspace .env):
  VK_SERVICE_TOKEN  the service key of a VK mini app (dev.vk.com, the new panel: create a mini app, Development >
                    Access keys; no business verification). Never expires. Reads open communities: groups.getById
                    (members_count), wall.get, wall.getComments, board.getTopics.
  VK_USER_TOKEN     a user token of the same app, needed only for groups.search (error 15 with the service key).
                    Get it with the implicit flow: open
                    https://oauth.vk.com/authorize?client_id=<app id>&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=groups&response_type=token&v=5.199
                    and copy access_token from the address of the blank page. `offline` is an invalid scope for a mini
                    app, so the token lives about a day; an expired one (error 5) stops the stage with this hint, and
                    a re-run with a fresh token resumes from the cache.
Every answer is cached per run month in data/cache/vk/, so a re-run in the same month needs neither token nor network.
VK allows about 3 requests a second; the client waits `PACE` seconds after a live call and retries error 6 (too many
requests per second).
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse

from nichefinder import http, keys
from nichefinder.workspace import Workspace

API = "https://api.vk.com/method"
VERSION = "5.199"
PACE = 0.4
USER_TOKEN_HINT = ("VK community search (groups.search) needs a user token, which lives about a day: open "
                   "https://oauth.vk.com/authorize?client_id=<your VK app id>&display=page&redirect_uri=https://oauth.vk.com/blank.html"
                   "&scope=groups&response_type=token&v=5.199 and put access_token into the workspace .env as VK_USER_TOKEN")


class VKError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        super().__init__(f"VK API error {code}: {msg}")


def _post(method: str, body: str) -> dict:
    """One live call (tests replace it)."""
    r = http.request(f"{API}/{method}", method="POST", data=body, timeout=30, tries=3,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.json()


def call(ws: Workspace, method: str, params: dict, token: str = "VK_SERVICE_TOKEN") -> dict:
    """The `response` of a VK API method, cached per run month. `token` names the key in the environment / .env."""
    canon = json.dumps({"m": method, "p": {k: str(v) for k, v in sorted(params.items())}, "month": f"{ws.today:%Y-%m}"},
                       ensure_ascii=False, sort_keys=True)
    path = ws.cache("vk") / f"{method}_{hashlib.sha1(canon.encode('utf-8')).hexdigest()}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    value = keys.get(token)
    if not value:
        raise keys.MissingKey((token,), USER_TOKEN_HINT if token == "VK_USER_TOKEN" else "VK API calls")
    body = urllib.parse.urlencode({**params, "v": VERSION, "access_token": value})
    for attempt in range(4):
        js = _post(method, body)
        err = js.get("error")
        if not err:
            break
        code = int(err.get("error_code") or 0)
        if code == 6 and attempt < 3:   # too many requests per second
            time.sleep(1.0 + attempt)
            continue
        if code == 5:   # user authorization failed: expired or revoked token
            raise keys.MissingKey((token,), (USER_TOKEN_HINT if token == "VK_USER_TOKEN" else "VK API calls") + " (the token expired)")
        raise VKError(code, str(err.get("error_msg") or ""))
    resp = js["response"]
    path.write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
    time.sleep(PACE)
    return resp


def search_groups(ws: Workspace, q: str, count: int = 100) -> list[dict]:
    """groups.search (user token): id, name, screen_name, type, is_closed per community, in VK's own relevance order."""
    return call(ws, "groups.search", {"q": q, "count": count}, token="VK_USER_TOKEN").get("items", [])


def groups_by_id(ws: Workspace, ids: list[int], fields: str = "members_count,activity,description") -> list[dict]:
    """groups.getById (service key) in batches of 400 ids."""
    out: list[dict] = []
    for i in range(0, len(ids), 400):
        part = ",".join(str(x) for x in ids[i:i + 400])
        resp = call(ws, "groups.getById", {"group_ids": part, "fields": fields})
        out += resp.get("groups", []) if isinstance(resp, dict) else resp
    return out
