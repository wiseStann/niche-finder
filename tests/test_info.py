"""Offline tests for the info cohort: topics, the YouTube Data API client, info_suggest, info_youtube, info_score."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import urllib.parse
from pathlib import Path

import pytest
import yaml

from nichefinder import http, info
from nichefinder.sources import suggest, youtube
from nichefinder.stages import info_score, info_suggest, info_youtube
from nichefinder.workspace import Workspace

EXAMPLE_SCORE = Path(info.__file__).parent / "examples" / "default" / "config" / "score_info.yaml"


def make_ws(tmp_path: Path, topics: list[dict], seeds: list[str] | None = None, measure: dict | None = None) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["ru"], "as_of": "2026-11-17"}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "info_topics.yaml").write_text(yaml.safe_dump(
        {"_settings": {"lang": "ru", "region": "RU", "window_months": 12, "seeds": seeds or []}, "topics": topics},
        allow_unicode=True), encoding="utf-8")
    cfg = yaml.safe_load(EXAMPLE_SCORE.read_text(encoding="utf-8"))
    cfg["measure"].update(measure or {})
    (tmp_path / "config" / "score_info.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return Workspace(tmp_path)


def video(vid, sec, views, channel, title, published, desc=""):
    return {"id": vid, "snippet": {"title": title, "description": desc, "channelId": channel, "channelTitle": channel,
                                   "publishedAt": f"{published}T10:00:00Z"},
            "statistics": {"viewCount": str(views), "likeCount": "1"}, "contentDetails": {"duration": f"PT{sec}S"}}


VIDEOS = {
    "v1": video("v1", 30, 200_000, "A", "Как продавать на авито", "2026-10-01", "забирай гайд в моём канале t.me/abc"),
    "v2": video("v2", 60, 3_000, "B", "Авито лайфхак", "2026-01-01"),
    "v3": video("v3", 600, 900_000, "B", "Длинный разбор авито", "2026-02-01"),        # long: dropped
    "v4": video("v4", 45, 50_000, "B", "Avito tips", "2026-03-01"),                    # no Cyrillic: dropped
    "v5": video("v5", 20, 8_000, "A", "Авито продажи", "2026-06-01"),
    "v6": video("v6", 50, 12_000, "C", "Авито с нуля", "2025-12-01"),
}
CHANNELS = {
    "A": {"id": "A", "snippet": {"description": ""}, "statistics": {"subscriberCount": "5000"}},
    "B": {"id": "B", "snippet": {"description": "Telegram: @bchan"}, "statistics": {"subscriberCount": "1000000"}},
    "C": {"id": "C", "snippet": {"description": ""}, "statistics": {"hiddenSubscriberCount": True}},
}


class FakeApi:
    def __init__(self):
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers=None, **kw):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        method = u.path.rsplit("/", 1)[-1]
        self.calls.append((method, q, headers or {}))
        if method == "search":
            items = [{"id": {"videoId": v}} for v in VIDEOS]
        else:
            src = VIDEOS if method == "videos" else CHANNELS
            items = [src[i] for i in q["id"].split(",") if i in src]
        return http.Response(200, json.dumps({"items": items}))


def test_window_and_duration_helpers():
    assert info_youtube.window_start(dt.date(2026, 11, 17), 12) == dt.date(2025, 11, 1)
    assert info_youtube.window_start(dt.date(2026, 2, 3), 3) == dt.date(2025, 11, 1)
    assert info_youtube.seconds("PT1M5S") == 65 and info_youtube.seconds("PT45S") == 45
    assert info_youtube.seconds("PT1H") == 3600 and info_youtube.seconds("P0D") == 0


def test_youtube_client_key_in_header_cache_and_budget(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, [])
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-123")
    api = FakeApi()
    monkeypatch.setattr(http, "request", api)
    yt = youtube.Client(ws, budget=150)
    ids = yt.search("авито", lang="ru", region="RU", after="2025-11-01T00:00:00Z")
    assert ids == list(VIDEOS)
    method, params, headers = api.calls[0]
    assert headers["X-Goog-Api-Key"] == "test-key-123"
    assert all("test-key-123" not in json.dumps(p) for _, p, _ in api.calls)
    assert params["videoDuration"] == "short" and params["publishedAfter"] == "2025-11-01T00:00:00Z"
    assert yt.search("авито", lang="ru", region="RU", after="2025-11-01T00:00:00Z") == ids    # cached: free
    assert yt.used == 100 and len(api.calls) == 1
    with pytest.raises(youtube.QuotaExceeded):
        yt.search("другое", lang="ru", region="RU", after="2025-11-01T00:00:00Z")          # 200 > budget 150
    assert len(yt.channels(["A", "B", "A"])) == 2 and yt.used == 101


def test_youtube_client_daily_quota_error(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, [])
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")

    def refuse(url, **kw):
        raise http.HttpError(403, url, '{"error": {"errors": [{"reason": "quotaExceeded"}]}}')
    monkeypatch.setattr(http, "request", refuse)
    with pytest.raises(youtube.QuotaExceeded):
        youtube.Client(ws).search("x", lang="ru", region="RU", after="2025-11-01T00:00:00Z")


def test_info_youtube_metrics(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, [{"id": "avito", "q": ["авито"], "who": "w", "task": "t", "product": "p"},
                            {"id": "hacks", "q": ["авито лайфхак"], "must": "ЛАЙФХАК"}])
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    api = FakeApi()
    monkeypatch.setattr(http, "request", api)
    info_youtube.run(ws, argparse.Namespace(budget=1000, only=""))
    assert {p["order"] for m, p, _ in api.calls if m == "search"} == {"viewCount"}
    row, hacks = list(csv.DictReader(open(ws.out("info_youtube.csv"), encoding="utf-8")))
    assert row["status"] == "ok" and row["n_found"] == "6"
    assert row["n_videos"] == "4" and row["n_channels"] == "3"                   # v3 long, v4 not Cyrillic
    assert float(row["views_median"]) == 10_000 and row["views_p90"] == "200000"
    assert row["breakout_share"] == "0.333"                                     # v1 only; C hides its subscribers
    assert row["small_share"] == "0.667"                                        # v1 and v5 from channel A (5k subs)
    assert row["tg_channel_share"] == "0.667"                                   # A via a video, B via its channel
    assert row["tg_video_share"] == "0.25" and row["offer_share"] == "0.25"     # v1: t.me link and a guide
    assert row["top3_share"] == "1.0"
    assert (row["recent"], row["older"], row["recent_ratio"]) == ("2", "2", "1.0")
    assert hacks["n_videos"] == "1"                                             # must: only v2 names it
    vids = list(csv.DictReader(open(ws.out("info_youtube_videos.csv"), encoding="utf-8")))
    assert {v["video_id"] for v in vids if v["topic_id"] == "avito"} == {"v1", "v2", "v5", "v6"}


def test_info_youtube_quota_keeps_measured_topics(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, [{"id": "a", "q": ["авито"]}, {"id": "b", "q": ["озон"]}, {"id": "c", "q": ["вб"]}])
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(http, "request", FakeApi())
    info_youtube.run(ws, argparse.Namespace(budget=150, only=""))
    rows = list(csv.DictReader(open(ws.out("info_youtube.csv"), encoding="utf-8")))
    assert [r["status"] for r in rows] == ["ok", "quota", "quota"]


def test_info_score_gates_verdicts_and_report(tmp_path):
    ws = make_ws(tmp_path, [{"id": "best", "q": ["x"], "who": "sellers"}])
    base = {"status": "ok", "phrases": "x", "window_from": "2025-11-01", "views_p90": "100000", "breakout_share": "0.1",
            "small_share": "0.2", "tg_channel_share": "0.2", "offer_share": "0.1", "top3_share": "0.3",
            "recent_ratio": "1.0", "n_videos": "40", "views_median": "20000"}
    rows = [
        {**base, "topic_id": "best", "views_median": "90000", "views_p90": "900000", "breakout_share": "0.4",
         "small_share": "0.6", "tg_channel_share": "0.6", "offer_share": "0.5", "top3_share": "0.1",
         "recent_ratio": "2.0"},
        {**base, "topic_id": "mid"},
        {**base, "topic_id": "thin", "n_videos": "5"},
        {**base, "topic_id": "quiet", "views_median": "300", "tg_channel_share": "0", "top3_share": "0.8"},
        {"topic_id": "later", "status": "quota"},
    ]
    with open(ws.out("info_youtube.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=info_youtube.TOPIC_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    info_score.run(ws, argparse.Namespace())
    scored = {r["topic_id"]: r for r in csv.DictReader(open(ws.out("info_score.csv"), encoding="utf-8"))}
    assert set(scored) == {"best", "mid", "thin", "quiet"}
    assert scored["best"]["verdict"] == "green" and scored["best"]["rank"] == "1" and scored["best"]["who"] == "sellers"
    assert scored["thin"]["verdict"] == "red" and scored["thin"]["gates"] == "I0:thin"
    assert scored["quiet"]["gates"] == "I1:views" and set(scored["quiet"]["flags"].split()) == {"I:top3", "I:no-tg"}
    assert scored["mid"]["verdict"] == "yellow"
    md = ws.report("info.md").read_text(encoding="utf-8")
    assert "DRAFT weights" in md and "later (quota)" in md


def test_info_suggest_aggregates_expansions(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, [{"id": "a", "q": ["авито продажи"]}], seeds=["авито"])
    answers = {"авито": ["авито", "авито продажи", "авито вакансии"], "авито а": ["авито аккаунт", "авито продажи"]}
    monkeypatch.setattr(suggest, "youtube", lambda ws, q, hl, gl: {"q": q, "suggestions": answers.get(q, [])})
    info_suggest.run(ws, argparse.Namespace(seed=[], top=5))
    rows = list(csv.DictReader(open(ws.out("info_suggest.csv"), encoding="utf-8")))
    assert [r["phrase"] for r in rows] == ["авито продажи", "авито аккаунт", "авито вакансии"]   # hits, then position
    assert "авито" not in [r["phrase"] for r in rows]                                           # the seed itself
    assert rows[0]["hits"] == "2" and rows[0]["best_pos"] == "2" and rows[0]["in_topics"] == "1"


def test_info_validate(tmp_path):
    ws = make_ws(tmp_path, [{"id": "a", "q": ["x"], "who": "w", "task": "t", "product": "p"},
                            {"id": "a", "q": []}, {"id": "Bad Id", "q": ["y"]},
                            {"id": "many", "q": ["1", "2", "3", "4"], "who": "w", "task": "t", "product": "p"},
                            {"id": "bad-must", "q": ["z"], "must": "(unclosed"}])
    errors, warns = info.validate(ws)
    assert any("duplicate" in e for e in errors) and any("no search phrases" in e for e in errors)
    assert any("slug" in e for e in errors) and any("bad-must: must" in e for e in errors)
    assert any("many: 4 phrases" in w for w in warns)


def test_stages_without_topics_do_nothing(tmp_path):
    ws = make_ws(tmp_path, [])
    info_suggest.run(ws, argparse.Namespace(seed=[], top=5))
    info_youtube.run(ws, argparse.Namespace(budget=10, only=""))
    info_score.run(ws, argparse.Namespace())
    assert not ws.out("info_youtube.csv").exists() and not ws.out("info_score.csv").exists()
