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
    cfg["measure"].update({"classify": False, **(measure or {})})       # labels: tested on their own
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
    def __init__(self, videos: dict | None = None):
        self.calls: list[tuple[str, dict, dict]] = []
        self.videos = VIDEOS if videos is None else videos

    def __call__(self, url, headers=None, **kw):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        method = u.path.rsplit("/", 1)[-1]
        self.calls.append((method, q, headers or {}))
        if method == "search":
            items = [{"id": {"videoId": v}} for v in self.videos]
        else:
            src = self.videos if method == "videos" else CHANNELS
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
                            {"id": "hacks", "q": ["авито лайфхак"], "must": "ЛАЙФХАК"},
                            {"id": "no-sales", "q": ["авито"], "must_not": "продаж|продава"}])
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    api = FakeApi()
    monkeypatch.setattr(http, "request", api)
    info_youtube.run(ws, argparse.Namespace(budget=1000, only=""))
    assert {p["order"] for m, p, _ in api.calls if m == "search"} == {"viewCount"}
    row, hacks, no_sales = list(csv.DictReader(open(ws.out("info_youtube.csv"), encoding="utf-8")))
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
    assert no_sales["n_videos"] == "2"                                          # must_not drops v1 and v5
    vids = list(csv.DictReader(open(ws.out("info_youtube_videos.csv"), encoding="utf-8")))
    assert {v["video_id"] for v in vids if v["topic_id"] == "avito"} == {"v1", "v2", "v5", "v6"}


def test_info_youtube_teaching_labels(tmp_path, monkeypatch):
    """Metrics count only the videos the LLM labels as teaching; the report shows teaching examples only."""
    from nichefinder import llm
    ws = make_ws(tmp_path, [{"id": "avito", "q": ["авито"], "task": "продавать"}], measure={"classify": True})
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(http, "request", FakeApi())
    seen = []

    def fake_chat(ws, messages, **kw):
        seen.append(messages[1]["content"])
        # kept order: v1, v2, v5, v6; v2 is a sketch, v6 off topic; v5 left unlabelled (counts as teaching)
        return {"labels": {"1": "T", "2": "E", "4": "o"}}, False, None
    monkeypatch.setattr(llm, "chat_json", fake_chat)
    info_youtube.run(ws, argparse.Namespace(budget=1000, only=""))
    (row,) = list(csv.DictReader(open(ws.out("info_youtube.csv"), encoding="utf-8")))
    assert (row["n_shorts"], row["n_videos"], row["dropped_fun"], row["dropped_off"]) == ("4", "2", "1", "1")
    assert row["teach_share"] == "0.5" and row["classified"] == "1"
    assert float(row["views_median"]) == 104_000                                 # v1 200k and v5 8k
    assert "Topic: avito" in seen[0] and "продавать" in seen[0] and "забирай гайд" in seen[0]
    kinds = {v["video_id"]: v["kind"] for v in csv.DictReader(open(ws.out("info_youtube_videos.csv"), encoding="utf-8"))}
    assert kinds == {"v1": "T", "v2": "E", "v5": "T", "v6": "O"}
    info_score.run(ws, argparse.Namespace())
    md = ws.report("info.md").read_text(encoding="utf-8")
    assert "teaching Shorts only" in md and "| 2 / 4 |" in md
    assert "Авито лайфхак" not in md                                               # the sketch is not an example


def test_info_youtube_without_llm_key_measures_all(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, [{"id": "avito", "q": ["авито"]}], measure={"classify": True})
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(http, "request", FakeApi())
    info_youtube.run(ws, argparse.Namespace(budget=1000, only=""))
    (row,) = list(csv.DictReader(open(ws.out("info_youtube.csv"), encoding="utf-8")))
    assert (row["n_videos"], row["classified"], row["teach_share"]) == ("4", "0", "")
    info_score.run(ws, argparse.Namespace())
    assert "Videos are not labelled" in ws.report("info.md").read_text(encoding="utf-8")


def test_youtube_search_pages(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, [])
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    calls = []

    def api(url, headers=None, **kw):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        calls.append(q)
        if "pageToken" not in q:
            return http.Response(200, json.dumps({"items": [{"id": {"videoId": "a"}}], "nextPageToken": "P2"}))
        return http.Response(200, json.dumps({"items": [{"id": {"videoId": "b"}}]}))
    monkeypatch.setattr(http, "request", api)
    yt = youtube.Client(ws)
    assert yt.search("x", lang="ru", region="RU", after="2025-11-01T00:00:00Z") == ["a"]
    assert yt.search("x", lang="ru", region="RU", after="2025-11-01T00:00:00Z", pages=3) == ["a", "b"]
    assert len(calls) == 2 and calls[1]["pageToken"] == "P2"                # page 1 reused from the cache
    assert yt.used == 200                                                    # no third page: no token


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
    assert "DRAFT weights" in md and "- later (quota: not measured yet" in md


def test_info_score_shows_paid_market_without_changing_the_score(tmp_path):
    ws = make_ws(tmp_path, [{"id": "a", "q": ["x"]}, {"id": "b", "q": ["y"]}])
    base = {"status": "ok", "phrases": "x", "window_from": "2025-11-01", "views_p90": "100000", "breakout_share": "0.1",
            "small_share": "0.2", "tg_channel_share": "0.2", "offer_share": "0.1", "top3_share": "0.3",
            "recent_ratio": "1.0", "n_videos": "40", "views_median": "20000"}
    with open(ws.out("info_youtube.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=info_youtube.TOPIC_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows([{**base, "topic_id": "a"}, {**base, "topic_id": "b", "views_median": "40000"}])
    info_score.run(ws, argparse.Namespace())
    before = {r["topic_id"]: r for r in csv.DictReader(open(ws.out("info_score.csv"), encoding="utf-8"))}
    with open(ws.out("info_paid.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["topic_id", "paid_flag", "sp_courses", "sp_paid", "sp_paid_learners", "lr_paid",
                                           "lr_ratings"])
        w.writeheader()
        w.writerows([{"topic_id": "a", "paid_flag": "I:paid-market", "sp_courses": "10", "sp_paid": "3", "sp_paid_learners": "5000",
                      "lr_paid": "20", "lr_ratings": "1500"},
                     {"topic_id": "b", "paid_flag": "I:no-paid", "sp_paid": "0", "sp_paid_learners": "0",
                      "lr_paid": "1", "lr_ratings": "7"}])
    info_score.run(ws, argparse.Namespace())
    after = {r["topic_id"]: r for r in csv.DictReader(open(ws.out("info_score.csv"), encoding="utf-8"))}
    assert {k: (r["score"], r["verdict"], r["rank"]) for k, r in after.items()} == \
           {k: (r["score"], r["verdict"], r["rank"]) for k, r in before.items()}
    assert "I:paid-market" in after["a"]["flags"].split() and "I:no-paid" in after["b"]["flags"].split()
    assert after["a"]["sp_paid_learners"] == "5000" and after["b"]["lr_ratings"] == "7"
    md = ws.report("info.md").read_text(encoding="utf-8")
    assert "| 5.0k / 1.5k |" in md and "- **paid market**: Stepik 3 paid of 10 courses" in md


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
                            {"id": "bad-must", "q": ["z"], "must": "(unclosed", "must_not": "[unclosed"},
                            {"id": "wordy", "q": ["выгорание на работе что делать"], "who": "w", "task": "t",
                             "product": "p"}])
    errors, warns = info.validate(ws)
    assert any("duplicate" in e for e in errors) and any("no search phrases" in e for e in errors)
    assert any("slug" in e for e in errors) and any("bad-must: must is" in e for e in errors)
    assert any("bad-must: must_not is" in e for e in errors)
    assert any("many: 4 phrases" in w for w in warns)
    assert any(w.startswith("wordy: long phrase") for w in warns) and not any(w.startswith("a: long") for w in warns)


def test_stages_without_topics_do_nothing(tmp_path):
    ws = make_ws(tmp_path, [])
    info_suggest.run(ws, argparse.Namespace(seed=[], top=5))
    info_youtube.run(ws, argparse.Namespace(budget=10, only=""))
    info_score.run(ws, argparse.Namespace())
    assert not ws.out("info_youtube.csv").exists() and not ws.out("info_score.csv").exists()


def test_must_ignores_hashtags_must_not_does_not():
    measure = {**info_youtube.MEASURE}
    vids = [video("w", 30, 50_000, "A", "Как поднять самооценку", "2026-05-01"),
            video("t", 30, 9_000_000, "A", "Собеседование пошло не по плану #самооценка", "2026-05-01"),
            video("x", 30, 70_000, "A", "Самооценка и уверенность", "2026-05-01", "#прикол")]
    kept = info_youtube.video_rows("s", vids, list(CHANNELS.values()), measure, "ru", must="самооцен", must_not="прикол")
    assert [r["video_id"] for r in kept] == ["w"]          # t: only a hashtag; x: excluded by a hashtag


# ---- info_discover ----------------------------------------------------------

def test_discover_demand_drops_nested_phrases_and_slug():
    from nichefinder.stages import info_discover
    rows = [("курсы английского", 100), ("курсы английского онлайн", 30), ("английский для детей", 50)]
    assert info_discover.demand(rows) == 150                  # "онлайн" variant is inside "курсы английского"
    assert info_discover.slug("английский язык", 1) == "angliyskiy-yazyk"
    assert info_discover.slug("ёж", 7) == "ezh" and info_discover.slug("!!!", 7) == "topic-7"


def test_discover_end_to_end(tmp_path, monkeypatch):
    from nichefinder import llm
    from nichefinder.sources import wordstat
    from nichefinder.stages import info_discover
    ws = make_ws(tmp_path, [{"id": "old", "q": ["x"]}])
    (tmp_path / "config" / "info_discover.yaml").write_text(yaml.safe_dump(
        {"stems": ["онлайн курсы", "как"], "min_count": 100, "batch": 2, "top_n": 2}, allow_unicode=True), encoding="utf-8")
    data = {"онлайн курсы": [("курсы английского", 900), ("курс доллара онлайн", 5000), ("курсы английского онлайн", 300)],
            "как": [("как похудеть", 800), ("как пишется", 4000), ("как выучить английский", 200), ("как сделать", 50)]}
    monkeypatch.setattr(wordstat, "top_requests", lambda ws, s, n, log=None: (
        {"results": [{"phrase": p, "count": c} for p, c in data[s]]}, False))
    labels = {"курсы английского": ["L", "английский язык", "lang"], "курсы английского онлайн": ["L", "английский язык", "lang"],
              "как выучить английский": ["L", "английский язык", "lang"], "как похудеть": ["F", "похудение", "health"]}
    prompts = []

    def fake_chat(ws, messages, **kw):
        if messages[0]["role"] == "system":
            prompts.append(messages[0]["content"])
            out = []
            for line in messages[1]["content"].splitlines():
                i, p = line.split(". ", 1)
                out.append([int(i), *labels[p]] if p in labels else [int(i), "O"])
            return {"r": out}, False, None
        return {"t": [{"topic": "английский язык", "yt": "английский язык", "must": "англ", "who": "взрослые",
                       "task": "заговорить", "product": "разговорник, 390 ₽"},
                      {"topic": "похудение", "yt": "похудение", "must": "(broken", "who": "w", "task": "t", "product": "p"}]}, False, None
    monkeypatch.setattr(llm, "chat_json", fake_chat)
    info_discover.run(ws, argparse.Namespace(write_topics=-1))
    topics = list(csv.DictReader(open(ws.out("info_discover.csv"), encoding="utf-8")))
    assert [(t["topic"], t["demand"]) for t in topics] == [("английский язык", "1100"), ("похудение", "800")]
    assert "английский язык" in prompts[-1]                    # later batches see the topics named so far
    phrases = {r["phrase"]: r for r in csv.DictReader(open(ws.out("info_discover_phrases.csv"), encoding="utf-8"))}
    assert phrases["курс доллара онлайн"]["kind"] == "O" and "как сделать" not in phrases   # below min_count
    written = yaml.safe_load(ws.config("info_topics.yaml").read_text(encoding="utf-8"))
    assert [t["id"] for t in written["topics"]] == ["angliyskiy-yazyk", "pohudenie"]
    assert written["topics"][0]["must"] == "англий|англ"                 # topic stem + the model stem, "язык" generic
    assert written["topics"][1]["must"] == "похуде"                      # an invalid model regex falls back to topic stems
    assert written["topics"][0]["q"] == ["английский язык"]              # the phrase is the topic itself
    assert written["_settings"]["lang"] == "ru"
    assert yaml.safe_load(ws.config("info_topics.previous.yaml").read_text(encoding="utf-8"))["topics"][0]["id"] == "old"
    assert info.validate(ws)[0] == []


def test_discover_build_must_drops_generic_and_short_stems():
    from nichefinder.stages import info_discover
    m = info_discover.build_must("гитара", "гитар|аккорд|бо|нот|начинающ|урок")
    assert m.split("|") == ["гитар", "аккорд"]                           # no "бо", "нот", "начинающ", "урок"
    assert info_discover.build_must("программирование", "алгоритм|код").split("|") == ["програ", "алгоритм"]
    assert info_discover.build_must("1с", "1с|обучен|бухгалт") == r"\b1с\b|бухгалт"   # bare "1с" would hide in words
    assert info_discover.build_must("вязание спицами", "спиц|петл").split("|")[:2] == ["вязан", "спица"]
    assert info_discover.build_must("обучение чтению", "чтен|букв") == "чтени|чтен|букв"    # "обучение" is generic


def test_info_youtube_global_top_is_not_thin(tmp_path, monkeypatch):
    """A short phrase whose most viewed top is English-language hits: status global, not a thin (red) topic."""
    vids = {f"e{i}": video(f"e{i}", 30, 1_000_000, "B", f"Guitar lesson {i}", "2026-05-01") for i in range(8)}
    vids.update({"r1": video("r1", 30, 50_000, "A", "Гитара для начинающих", "2026-05-01")})
    ws = make_ws(tmp_path, [{"id": "guitar", "q": ["гитара"], "must": "гитар"}])
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(http, "request", FakeApi(vids))
    info_youtube.run(ws, argparse.Namespace(budget=1000, only=""))
    (row,) = list(csv.DictReader(open(ws.out("info_youtube.csv"), encoding="utf-8")))
    assert (row["status"], row["dropped_lang"], row["n_videos"]) == ("global", "8", "1")
    info_score.run(ws, argparse.Namespace())
    assert "guitar (global: the most viewed top" in ws.report("info.md").read_text(encoding="utf-8")


def test_discover_trends_from_wordstat_dynamics(tmp_path, monkeypatch):
    from nichefinder.sources import wordstat
    from nichefinder.stages import info_discover
    ws = make_ws(tmp_path, [])
    months = [f"{2023 + (i + 10) // 12}-{(i + 10) % 12 + 1:02d}-01" for i in range(36)]
    series = {"растёт": [100] * 24 + [150] * 12, "падает": [100] * 24 + [70] * 12, "сезон": [50, 50, 200] * 12}
    monkeypatch.setattr(wordstat, "dynamics", lambda ws, p, m, log=None: (
        {"results": [{"date": d, "count": c} for d, c in zip(months, series[p])]}, False))
    topics = [{"head_phrase": p} for p in series] + [{"head_phrase": "не мерим"}]
    info_discover.trends(ws, topics, 3)
    assert [t["trend"] for t in topics[:3]] == ["UP", "DOWN", "FLAT"]     # a seasonal series is not growth
    assert topics[0]["yoy"] == 0.5 and "trend" not in topics[3]


def test_discover_write_topics_keeps_the_hand_made_backup(tmp_path):
    from nichefinder.stages import info_discover
    ws = make_ws(tmp_path, [{"id": "mine", "q": ["x"]}])
    info_discover.write_topics(ws, [{"id": "a", "q": ["a"], "source": "info_discover"}])
    info_discover.write_topics(ws, [{"id": "b", "q": ["b"], "source": "info_discover"}])   # second write
    prev = yaml.safe_load(ws.config("info_topics.previous.yaml").read_text(encoding="utf-8"))
    assert [t["id"] for t in prev["topics"]] == ["mine"]
