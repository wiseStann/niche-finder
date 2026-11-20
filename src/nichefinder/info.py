"""Info-product topics: the `info` cohort (short video -> Telegram channel -> micro product).

A topic is a niche of the info cohort, still who x task x product, but measured by what people *watch* in short
video, not by what they search for. Topics live in config/info_topics.yaml:

    _settings:
      lang: ru                 # YouTube relevanceLanguage and autocomplete language; ru also keeps Cyrillic titles only
      region: RU               # YouTube regionCode and autocomplete country
      window_months: 12        # only videos published in this window (counted from the first day of the run month)
      seeds: [...]             # broad areas that info_suggest expands through YouTube autocomplete
    topics:
      - id: avito-listings     # slug, used everywhere as topic_id
        q: [...]               # 1-3 YouTube search phrases; each costs one search (100 quota units)
        must: ...              # optional regex: keep only videos whose title or description matches it
        who: ...
        task: ...
        product: ...           # the micro product and its price, e.g. "checklist, 490 RUB"

Measurement thresholds and the score weights are in config/score_info.yaml (pre-registered, see methodology 7.6).
"""
from __future__ import annotations

import re

from nichefinder.workspace import Workspace

TOPICS_FILE = "info_topics.yaml"
SCORE_FILE = "score_info.yaml"
DEFAULTS = {"lang": "ru", "region": "RU", "window_months": 12, "seeds": []}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_PHRASES = 3


def load(ws: Workspace) -> tuple[dict, list[dict]]:
    """(settings, topics) from config/info_topics.yaml; a missing file means no topics."""
    data = ws.load_config(TOPICS_FILE, {}) or {}
    settings = {**DEFAULTS, **(data.get("_settings") or {})}
    return settings, list(data.get("topics") or [])


def phrases(topic: dict) -> list[str]:
    q = topic.get("q") or []
    return [q] if isinstance(q, str) else [str(x) for x in q]


def validate(ws: Workspace) -> tuple[list[str], list[str]]:
    """Errors and warnings for config/info_topics.yaml."""
    errors: list[str] = []
    warns: list[str] = []
    _, topics = load(ws)
    seen: dict[str, str] = {}
    for t in topics:
        tid = t.get("id")
        if not tid or not SLUG.match(str(tid)):
            errors.append(f"info topic without a slug id: {t}")
            continue
        if tid in seen:
            errors.append(f"{tid}: duplicate info topic id")
        seen[tid] = tid
        qs = phrases(t)
        if not qs:
            errors.append(f"{tid}: no search phrases (q)")
        if len(qs) > MAX_PHRASES:
            warns.append(f"{tid}: {len(qs)} phrases; each costs a YouTube search (100 units), {MAX_PHRASES} is plenty")
        if t.get("must"):
            try:
                re.compile(str(t["must"]))
            except re.error as e:
                errors.append(f"{tid}: must is not a valid regex: {e}")
        for k in ("who", "task", "product"):
            if not t.get(k):
                warns.append(f"{tid}: no {k}")
    return errors, warns
