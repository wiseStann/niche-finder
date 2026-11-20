"""Free search suggestions: Google (Firefox endpoint), YouTube (the same endpoint with ds=yt) and Yandex
(suggest-ff). Cache: data/cache/suggest/.

    from nichefinder.sources import suggest
    res = suggest.google(ws, "tattoo studio software")     # {"q": ..., "suggestions": [...]}  or {"_error": "..."}
    res = suggest.youtube(ws, "avito", hl="ru", gl="ru")
    res = suggest.yandex(ws, "программа для салона")

Errors are returned (not raised) and are not cached, so a later run retries them.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse

from nichefinder import http
from nichefinder.workspace import Workspace

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"


def _fetch(url: str, proxy: str | None = None) -> str:
    return http.request(url, timeout=20, user_agent=UA, proxy=proxy).text


def _cached(ws: Workspace, kind: str, q: str, fn) -> dict:
    key = hashlib.sha1(f"{kind}|{q}".encode()).hexdigest()
    path = ws.cache("suggest") / f"{kind}_{key}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        res = fn(q)
    except Exception as e:  # noqa: BLE001
        res = {"_error": str(e)[:200]}
    if "_error" not in res:
        path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.4)
    return res


def google(ws: Workspace, q: str, hl: str = "en", gl: str = "us") -> dict:
    def fn(q):
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl={hl}&gl={gl}&q={urllib.parse.quote(q)}"
        data = json.loads(_fetch(url))
        return {"q": q, "suggestions": data[1] if len(data) > 1 else []}
    return _cached(ws, f"google_{hl}_{gl}", q, fn)


def youtube(ws: Workspace, q: str, hl: str = "ru", gl: str = "ru") -> dict:
    """What people type into YouTube search (the Google endpoint with ds=yt)."""
    def fn(q):
        url = (f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&hl={hl}&gl={gl}"
               f"&q={urllib.parse.quote(q)}")
        data = json.loads(_fetch(url))
        return {"q": q, "suggestions": data[1] if len(data) > 1 else []}
    return _cached(ws, f"youtube_{hl}_{gl}", q, fn)


def yandex(ws: Workspace, q: str) -> dict:
    def fn(q):
        url = f"https://suggest.yandex.ru/suggest-ff.cgi?part={urllib.parse.quote(q)}&uil=ru&v=3"
        data = json.loads(_fetch(url, proxy="ru"))
        return {"q": q, "suggestions": data[1] if len(data) > 1 else []}
    return _cached(ws, "yandex", q, fn)
