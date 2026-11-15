"""LLM calls through any OpenAI-compatible chat completions endpoint, cached on disk.

Keys and settings (environment or workspace .env):
    LLM_API_KEY      required
    LLM_BASE_URL     default https://api.deepseek.com/v1
    LLM_MODEL        default deepseek-chat (nf.yaml `llm.model` also works)
    LLM_EXTRA_BODY   optional JSON merged into each request, e.g. {"thinking": {"type": "disabled"}}

Identical requests are answered from data/cache/llm/ without a call, so re-runs are free.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from nichefinder import http, keys
from nichefinder.workspace import Workspace

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def config(ws: Workspace) -> dict[str, Any]:
    extra = keys.get("LLM_EXTRA_BODY") or ws.setting("llm.extra_body") or {}
    if isinstance(extra, str):
        extra = json.loads(extra)
    return {
        "base_url": (keys.get("LLM_BASE_URL") or ws.setting("llm.base_url") or DEFAULT_BASE_URL).rstrip("/"),
        "model": keys.get("LLM_MODEL") or ws.setting("llm.model") or DEFAULT_MODEL,
        "extra": extra,
    }


def chat_json(ws: Workspace, messages: list[dict], *, max_tokens: int = 3000, temperature: float = 0.1,
              tries: int = 4, cache_namespace: str = "llm") -> tuple[dict | None, bool, dict | None]:
    """Ask for a JSON object. Returns (parsed_content or None, from_cache, usage)."""
    cfg = config(ws)
    body = {"model": cfg["model"], "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
            "response_format": {"type": "json_object"}, **cfg["extra"]}
    key = hashlib.sha1((cfg["base_url"] + "|" + json.dumps(body, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()
    path = ws.cache(cache_namespace) / f"{key}.json"
    if path.is_file():
        d = json.loads(path.read_text(encoding="utf-8"))
        return d.get("content"), True, d.get("usage")
    (api_key,) = keys.require("LLM_API_KEY", purpose="LLM classification")
    for i in range(tries):
        try:
            resp = http.request(f"{cfg['base_url']}/chat/completions", method="POST", data=body, timeout=180, tries=1,
                                headers={"Authorization": f"Bearer {api_key}"}, user_agent=http.BOT_UA)
            d = resp.json()
            content = json.loads(d["choices"][0]["message"]["content"])
            out = {"content": content, "usage": d.get("usage")}
            path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            return content, False, d.get("usage")
        except Exception as e:  # noqa: BLE001 — network, HTTP or malformed JSON: retry
            print(f"    llm retry {i + 1}/{tries}: {str(e)[:120]}")
            time.sleep(5 * (i + 1))
    return None, False, None
