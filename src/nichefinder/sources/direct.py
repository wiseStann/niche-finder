"""Yandex Direct API Live 4 budget forecast: CreateNewForecast -> GetForecastList -> GetForecast -> DeleteForecastReport.

Key: YANDEX_DIRECT_TOKEN, an OAuth token (scope direct:api) of an application whose API access request was approved in
Direct Pro (Tools > API > My requests; up to 7 working days). Until then every call answers error 58 "No access", which
skips the stage with that hint (tools.ToolMissing). The token goes in the JSON body ("token"), never in a URL or a cache key.
Docs (2026-11-23): https://yandex.ru/dev/direct/doc/dg-v4/live/CreateNewForecast.html and GetForecast.html.
- CreateNewForecast: up to 100 phrases, GeoID (225 = Russia), Currency (required in Live 4). A report takes up to a
  minute; at most 5 reports are stored per user (error 31 for a sixth), each for five hours.
- GetForecast: per phrase Shows, Clicks, FirstPlaceClicks, PremiumClicks, CTRs, and the average click price Min / Max
  (guarantee block, its first place) and PremiumMin / PremiumMax (premium block, its first place), in the request's
  currency. Phrases that overlap inside one report may have their forecast attributed to either of them.
- The forecast methods do not spend API points; other methods share a cap of 50,000 calls a day, five at a time.
A finished report is cached per run month in data/cache/direct/ by its phrases, regions and currency, so a re-run in the
same month makes no call.
"""
from __future__ import annotations

import hashlib
import json
import time

from nichefinder import http, keys, tools
from nichefinder.workspace import Workspace

API = "https://api.direct.yandex.ru/live/v4/json/"
RETRY = {56, 57, 500, 503, 504, 506}          # request limits and temporary server errors
WAIT = 5.0


class DirectError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        super().__init__(f"Yandex Direct API error {code}: {msg}")


def _post(body: str) -> dict:
    """One live call (tests replace it)."""
    r = http.request(API, method="POST", data=body, timeout=60, tries=3, raise_for_status=False,
                     headers={"Content-Type": "application/json; charset=utf-8"})
    return r.json()


def call(method: str, param=None):
    """The `data` of a Live 4 method; retries request limits and temporary errors, turns access errors into a skip."""
    token = keys.get("YANDEX_DIRECT_TOKEN")
    if not token:
        raise keys.MissingKey(("YANDEX_DIRECT_TOKEN",), "Yandex Direct budget forecasts")
    env = {"method": method, "locale": "en", "token": token}
    if param is not None:
        env["param"] = param
    body = json.dumps(env, ensure_ascii=False)
    for attempt in range(4):
        js = _post(body)
        if "error_code" not in js:
            return js.get("data")
        code, msg = int(js.get("error_code") or 0), f"{js.get('error_str', '')}: {js.get('error_detail', '')}".strip(": ")
        if code in RETRY and attempt < 3:
            time.sleep(WAIT * (attempt + 1))
            continue
        # a skip, not a failure: the token is present but cannot be used yet (or any more)
        if code == 58:
            raise tools.ToolMissing("Yandex Direct: the app's API access request is not approved yet (error 58; "
                                    "Direct Pro > Tools > API > My requests)")
        if code == 53:
            raise tools.ToolMissing("Yandex Direct: YANDEX_DIRECT_TOKEN is invalid or expired (error 53); get a new one at "
                                    "https://oauth.yandex.ru/authorize?response_type=token&client_id=<app ClientID>")
        raise DirectError(code, msg)
    raise DirectError(0, "no answer")


def forecast(ws: Workspace, phrases: list[str], geo: list[int], currency: str = "RUB", poll_s: float = 10,
             max_wait_s: float = 600) -> dict:
    """{"phrases": [BannerPhraseInfo, ...], "common": ForecastCommonInfo} for up to 100 phrases, cached per month."""
    if len(phrases) > 100:
        raise ValueError("CreateNewForecast takes at most 100 phrases")
    canon = json.dumps({"p": phrases, "g": geo, "c": currency, "month": f"{ws.today:%Y-%m}"}, ensure_ascii=False)
    path = ws.cache("direct") / f"forecast_{hashlib.sha1(canon.encode('utf-8')).hexdigest()}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        fid = call("CreateNewForecast", {"Phrases": phrases, "GeoID": geo, "Currency": currency, "AuctionBids": "No"})
    except DirectError as e:
        if e.code == 31:
            raise DirectError(31, "five forecast reports are already stored: delete them in Direct or wait five hours") from None
        raise
    waited = 0.0
    while True:
        status = next((r.get("StatusForecast") for r in call("GetForecastList") or [] if r.get("ForecastID") == fid), "")
        if status == "Done":
            break
        if status == "Failed":
            raise DirectError(0, f"forecast report {fid} failed")
        if waited >= max_wait_s:
            raise DirectError(0, f"forecast report {fid} not ready after {max_wait_s:.0f} s")
        time.sleep(poll_s)
        waited += poll_s
    data = call("GetForecast", fid) or {}
    try:
        call("DeleteForecastReport", fid)
    except DirectError:
        pass   # reports expire after five hours anyway
    out = {"phrases": data.get("Phrases") or [], "common": data.get("Common") or {}}
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
