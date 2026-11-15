"""HTTP with retries, optional disk cache, proxies and a curl fallback. Standard library only.

    from nichefinder import http
    data = http.get_json(url, cache=ws.cache("itunes"))          # cached by URL
    html = http.get_text(url, cache=ws.cache("capterra"), cache_key=f"{slug}_p{page}", ext=".html",
                         backend="curl", min_size=10_000)          # some sites only answer browser-like clients

Proxies: HTTPS_PROXY / HTTP_PROXY apply to everything (urllib and curl read them).
`proxy="ru"` routes one request through NF_PROXY_RU (Russian sources that refuse foreign IPs).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
BOT_UA = "niche-finder/0.1 (+https://github.com/tinthefounder/niche-finder; market research)"
RETRY_STATUSES = (408, 425, 429, 500, 502, 503, 504, 520, 522, 524, 525)
_STATUS_MARK = "\n__NF_HTTP_STATUS__"


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        self.status, self.url, self.body = status, url, body
        super().__init__(f"HTTP {status} for {url[:160]}" + (f": {body[:200]}" if body else ""))


@dataclass
class Response:
    status: int
    text: str

    def json(self) -> Any:
        return json.loads(self.text)


def _proxy_url(proxy: str | None) -> str | None:
    if not proxy:
        return None
    if proxy == "ru":
        return os.environ.get("NF_PROXY_RU") or None
    return proxy


def _encode(data: Any) -> bytes | None:
    if data is None:
        return None
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _via_urllib(url, method, headers, body, timeout, proxy) -> Response:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    opener = (urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
              if proxy else urllib.request.build_opener())
    try:
        with opener.open(req, timeout=timeout) as r:
            return Response(r.status, r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return Response(e.code, e.read().decode("utf-8", errors="replace"))


def _via_curl(url, method, headers, body, timeout, proxy) -> Response:
    cmd = ["curl", "-s", "-L", "--compressed", "-m", str(int(timeout)), "-X", method, "-w", _STATUS_MARK + "%{http_code}"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if proxy:
        cmd += ["-x", proxy]
    if body is not None:
        cmd += ["--data-binary", "@-"]
    cmd.append(url)
    r = subprocess.run(cmd, input=body, capture_output=True)
    out = r.stdout.decode("utf-8", errors="replace")
    if _STATUS_MARK not in out:
        raise OSError(f"curl failed ({r.returncode}): {r.stderr.decode('utf-8', errors='replace')[:200]}")
    text, status = out.rsplit(_STATUS_MARK, 1)
    return Response(int(status or 0), text)


def request(url: str, *, method: str = "GET", headers: dict | None = None, data: Any = None,
            timeout: float = 60, proxy: str | None = None, backend: str = "urllib",
            user_agent: str = BROWSER_UA, tries: int = 3, backoff: tuple[float, ...] = (2, 5, 15, 30, 60),
            retry_statuses: tuple[int, ...] = RETRY_STATUSES, raise_for_status: bool = True) -> Response:
    """One HTTP call with retries on network errors and transient statuses.

    backend="urllib" by default; "curl" for sites that block Python clients; "auto" tries urllib and
    falls back to curl on HTTP 403.
    """
    h = {"User-Agent": user_agent, **(headers or {})}
    if data is not None and not isinstance(data, (bytes, str)):
        h.setdefault("Content-Type", "application/json")
    body = _encode(data)
    p = _proxy_url(proxy)
    last: Exception | None = None
    for attempt in range(max(1, tries)):
        try:
            if backend == "curl":
                resp = _via_curl(url, method, h, body, timeout, p)
            else:
                resp = _via_urllib(url, method, h, body, timeout, p)
                if backend == "auto" and resp.status == 403:
                    resp = _via_curl(url, method, h, body, timeout, p)
            if resp.status in retry_statuses and attempt < tries - 1:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
                continue
            if raise_for_status and resp.status >= 400:
                raise HttpError(resp.status, url, resp.text)
            return resp
        except HttpError:
            raise
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError) as e:
            last = e
            if attempt < tries - 1:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
    raise OSError(f"request failed after {tries} tries: {url[:160]}: {last}")


def cache_file(cache: Path, key: str, ext: str = ".json", hashed: bool = True) -> Path:
    """Where a cached response lives. Keys are SHA-1 hashed unless hashed=False (then used as the file name)."""
    name = hashlib.sha1(key.encode("utf-8")).hexdigest() if hashed else key
    return Path(cache) / f"{name}{ext}"


def get_text(url: str, *, cache: Path | None = None, cache_key: str | None = None, ext: str = ".txt",
             hashed: bool = True, min_size: int = 0, sleep: float = 0.0, **kw) -> str:
    """GET as text. With `cache`, a stored response is returned without a network call; responses shorter
    than `min_size` are not cached (they are usually block pages). `sleep` pauses after a live call."""
    path = cache_file(cache, cache_key or url, ext, hashed) if cache else None
    if path and path.is_file() and path.stat().st_size >= max(min_size, 1):
        return path.read_text(encoding="utf-8", errors="replace")
    text = request(url, **kw).text
    if path and len(text) >= min_size:
        path.write_text(text, encoding="utf-8")
    if sleep:
        time.sleep(sleep)
    return text


def get_json(url: str, *, cache: Path | None = None, cache_key: str | None = None, hashed: bool = True,
             sleep: float = 0.0, **kw) -> Any:
    path = cache_file(cache, cache_key or url, ".json", hashed) if cache else None
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    data = request(url, **kw).json()
    if path:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if sleep:
        time.sleep(sleep)
    return data


def post_json(url: str, body: Any, *, cache: Path | None = None, cache_key: str | None = None,
              hashed: bool = True, sleep: float = 0.0, **kw) -> Any:
    """POST a JSON body and parse the JSON answer. The cache key defaults to URL + canonical body."""
    key = cache_key or (url + "|" + json.dumps(body, sort_keys=True, ensure_ascii=False))
    path = cache_file(cache, key, ".json", hashed) if cache else None
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    data = request(url, method="POST", data=body, **kw).json()
    if path:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if sleep:
        time.sleep(sleep)
    return data
