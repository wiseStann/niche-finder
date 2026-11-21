"""Offline tests for the YouTube comments stages (S10): phrases, fetch with the LLM video check and comment pages (fake
API and model), the budget stop, sampling and labels, the verdict rule and the report."""
from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.parse
from pathlib import Path

import pytest
import yaml

from nichefinder import http, llm
from nichefinder.stages import s10_yt_comments_classify as classify
from nichefinder.stages import s10_yt_comments_fetch as fetch
from nichefinder.stages import s10_yt_comments_report as report
from nichefinder.workspace import Workspace

EXAMPLE_CFG = Path(fetch.__file__).resolve().parents[1] / "examples" / "default" / "config" / "yt_comments.yaml"


def make_ws(tmp_path: Path, as_of: str = "2026-11-17") -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": as_of}), encoding="utf-8")
    base = {"who": "people", "task": "count money", "product": "app", "side": "b2c", "tier": "A"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "budget", "name": "Budget apps", "geo": "both", **base},
        {"id": "habits", "name": "Habit trackers", "geo": "ru", **base},
        {"id": "usonly", "name": "US only", "geo": "global", **base},
    ]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "budget": {"ru": [{"q": "приложение для бюджета", "i": "category", "anchor": True},
                          {"q": "как вести бюджет", "i": "problem"}, {"q": "дзен мани", "i": "brand", "b": "Zen"}],
                   "en": [{"q": "budget app", "i": "category", "anchor": True}]},
        "habits": {"ru": [{"q": "трекер привычек", "i": "category", "anchor": True}]},
        "usonly": {"en": [{"q": "us thing", "i": "category", "anchor": True}]},
    }, allow_unicode=True), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(
        yaml.safe_dump({"tier_a": [{"id": "budget"}, {"id": "usonly"}], "tier_b": ["habits"]}), encoding="utf-8")
    (tmp_path / "config" / "yt_comments.yaml").write_text(EXAMPLE_CFG.read_text(encoding="utf-8"), encoding="utf-8")
    return Workspace(tmp_path)


def test_names_phrases_and_window():
    assert fetch.out_name("yt_comments_docs.jsonl", "ru") == "yt_comments_docs.jsonl"
    assert fetch.out_name("yt_comments_docs.jsonl", "en") == "yt_comments_docs_en.jsonl"
    assert fetch.out_name("S10-yt-comments.md", "en") == "S10-yt-comments-en.md"
    rows = [{"q": "a", "intent": "category", "anchor": 1}, {"q": "b", "intent": "category", "anchor": 0},
            {"q": "c", "intent": "problem", "anchor": 0}, {"q": "zen", "intent": "brand", "anchor": 0}]
    assert fetch.phrases(rows, ["anchor", "problem", "brand"], "review") == [("anchor", "a"), ("problem", "c"), ("brand", "zen review")]
    assert fetch.phrases(rows, ["category", "info"], "") == [("category", "b")]
    assert str(fetch.window_start(__import__("datetime").date(2026, 11, 17), 36)) == "2023-11-01"
    assert fetch.text_ok("Привет", "ru") and not fetch.text_ok("hello", "ru") and fetch.text_ok("hello", "en") and not fetch.text_ok("Привет", "en")


def video(vid, title, comments, channel="ch1"):
    return {"id": vid, "snippet": {"title": title, "channelTitle": channel, "channelId": channel, "publishedAt": "2025-05-01T10:00:00Z",
                                   "description": "desc"},
            "statistics": {"viewCount": "1000", "likeCount": "10", "commentCount": str(comments)}}


def thread(cid, text, author="u1", likes=0):
    return {"id": cid, "snippet": {"totalReplyCount": 1, "topLevelComment": {"snippet": {
        "textDisplay": text, "authorChannelId": {"value": author}, "likeCount": likes, "publishedAt": "2025-06-01T00:00:00Z"}}}}


class FakeApi:
    """search -> the niche's videos by phrase; videos -> statistics; commentThreads -> two pages for v1, comments off for v3."""
    SEARCH = {"приложение для бюджета": ["v1", "v2", "v3", "v4", "v5"], "как вести бюджет": ["v6"], "трекер привычек": ["h1"]}
    VIDEOS = {"v1": video("v1", "Лучшие приложения для бюджета", 500), "v2": video("v2", "Игра про деньги", 900),
              "v3": video("v3", "Как вести бюджет в таблице", 300), "v4": video("v4", "Budget app review", 800),
              "v5": video("v5", "Мало комментариев", 3), "v6": video("v6", "Семейный бюджет: мой опыт", 50),
              "h1": video("h1", "Трекер привычек обзор", 40)}

    def __init__(self):
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers=None, **kw):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        method = u.path.rsplit("/", 1)[-1]
        self.calls.append((method, q, headers or {}))
        if method == "search":
            return http.Response(200, json.dumps({"items": [{"id": {"videoId": v}} for v in self.SEARCH.get(q["q"], [])]}))
        if method == "videos":
            return http.Response(200, json.dumps({"items": [self.VIDEOS[i] for i in q["id"].split(",") if i in self.VIDEOS]}))
        vid = q["videoId"]
        if vid == "v3":
            raise http.HttpError(403, url, '{"error": {"errors": [{"reason": "commentsDisabled"}]}}')
        if vid == "v1" and "pageToken" not in q:
            return http.Response(200, json.dumps({"items": [thread("c1", "Нет нормального приложения для семьи"),
                                                            thread("c2", "Ссылка в описании", author="ch1"),
                                                            thread("c3", "great video")], "nextPageToken": "P2"}))
        if vid == "v1":
            return http.Response(200, json.dumps({"items": [thread("c4", "Подписка слишком дорогая")]}))
        return http.Response(200, json.dumps({"items": [thread(f"{vid}-1", f"Комментарий под {vid}")]}))


def fake_check(calls):
    """Video check: a game is not about the niche."""
    def chat(ws, messages, **kw):
        assert messages[0]["content"] == fetch.CHECK_SYSTEM
        calls.append(messages[1]["content"])
        lines = [x for x in messages[1]["content"].split("\n") if re.match(r"\d+: ", x)]
        return {"videos": [{"k": int(x.split(":")[0]), "fit": "no" if "Игра" in x else "yes", "why": "w"} for x in lines]}, False, None
    return chat


def test_fetch_checks_videos_reads_comment_pages_and_resumes_from_cache(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("YOUTUBE_API_KEY", "secret-key-1")
    monkeypatch.setenv("LLM_API_KEY", "x")
    api = FakeApi()
    checks: list[str] = []
    monkeypatch.setattr(http, "request", api)
    monkeypatch.setattr(llm, "chat_json", fake_check(checks))
    fetch.run(ws, argparse.Namespace(lang="", niches="", budget=1000))
    assert all("secret-key-1" not in json.dumps(q) for _, q, _ in api.calls)
    assert all(h.get("X-Goog-Api-Key") == "secret-key-1" for _, _, h in api.calls)
    search = [q for m, q, _ in api.calls if m == "search"]
    assert [q["q"] for q in search] == ["приложение для бюджета", "как вести бюджет", "трекер привычек"]   # usonly: geo global
    assert search[0]["publishedAfter"] == "2023-11-01T00:00:00Z" and search[0]["videoDuration"] == "any"
    assert (search[0]["relevanceLanguage"], search[0]["regionCode"]) == ("ru", "RU")
    vids = {r["video_id"]: r for r in csv.DictReader(open(ws.out(fetch.VIDEOS), encoding="utf-8"))}
    assert set(vids) == {"v1", "v2", "v3", "v6", "h1"}                 # v4: Latin title, v5: too few comments
    assert vids["v2"]["fit"] == "no" and vids["v2"]["picked"] == "0"
    assert (vids["v1"]["read"], vids["v1"]["kept"]) == ("4", "2")      # own channel and Latin comment dropped
    assert vids["v3"]["status"] == "comments disabled" and vids["v6"]["intent"] == "problem"
    docs = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8")]
    assert sorted(d["id"] for d in docs if d["niche_id"] == "budget") == ["c1", "c4", "v6-1"]
    f = {r["niche_id"]: r for r in csv.DictReader(open(ws.out(fetch.FETCH), encoding="utf-8"))}
    assert (f["budget"]["relevant"], f["budget"]["picked"], f["budget"]["comments"], f["budget"]["status"]) == ("3", "3", "3", "ok")
    assert f["budget"]["searched"] == "приложение для бюджета | как вести бюджет" and f["habits"]["status"] == "ok"
    n_calls = len(api.calls)

    # everything is cached: a re-run makes no API call (with no budget it could not) and writes the same docs
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call"))
    monkeypatch.setattr(llm, "chat_json", fake_check(checks))
    fetch.run(ws, argparse.Namespace(lang="ru", niches="", budget=0))
    assert len(api.calls) == n_calls
    assert len(open(ws.out(fetch.DOCS), encoding="utf-8").readlines()) == len(docs)


def test_fetch_budget_stop_marks_quota_and_keeps_earlier_rows(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setattr(http, "request", FakeApi())
    monkeypatch.setattr(llm, "chat_json", fake_check([]))
    fetch.run(ws, argparse.Namespace(lang="ru", niches="", budget=250))    # budget: 2 searches, then habits is cut
    f = {r["niche_id"]: r["status"] for r in csv.DictReader(open(ws.out(fetch.FETCH), encoding="utf-8"))}
    assert f == {"budget": "ok", "habits": "quota"}
    fetch.run(ws, argparse.Namespace(lang="ru", niches="", budget=1000))
    n_docs = len(open(ws.out(fetch.DOCS), encoding="utf-8").readlines())

    # a new month changes the search window, so nothing is cached; with no budget every niche keeps its earlier rows
    ws2 = Workspace(tmp_path, settings={"markets": ["us", "ru"], "as_of": "2026-12-03"})
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call with no budget"))
    fetch.run(ws2, argparse.Namespace(lang="ru", niches="", budget=0))
    f = {r["niche_id"]: r["status"] for r in csv.DictReader(open(ws.out(fetch.FETCH), encoding="utf-8"))}
    assert f == {"budget": "ok", "habits": "ok"}
    assert len(open(ws.out(fetch.DOCS), encoding="utf-8").readlines()) == n_docs


def test_fetch_without_llm_key_keeps_every_candidate(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(http, "request", FakeApi())
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: pytest.fail("no LLM call without the key"))
    fetch.run(ws, argparse.Namespace(lang="ru", niches="budget", budget=1000))
    vids = {r["video_id"]: r for r in csv.DictReader(open(ws.out(fetch.VIDEOS), encoding="utf-8"))}
    assert vids["v2"]["fit"] == "yes" and vids["v2"]["picked"] == "1"
    (row,) = csv.DictReader(open(ws.out(fetch.FETCH), encoding="utf-8"))
    assert row["by"] == "none"


def test_sample_round_robin_dedupe_and_min_chars():
    long = "x" * 30
    docs = ([{"video_id": "big", "id": f"b{i}", "text": f"{long} {i}"} for i in range(40)]
            + [{"video_id": "small", "id": f"s{i}", "text": f"{long} s{i}"} for i in range(3)]
            + [{"video_id": "small", "id": "dup", "text": f"{long} S0!"}, {"video_id": "small", "id": "short", "text": "ok"}])
    sel = classify.sample(docs, 10, 25)
    assert len(sel) == 10 and sum(d["video_id"] == "small" for d in sel) == 3
    ids = {d["id"] for d in sel}
    assert "short" not in ids and len(ids & {"dup", "s0"}) == 1          # "S0!" repeats "s0": one of them is kept
    assert [d["id"] for d in classify.sample(docs, 10, 25)] == [d["id"] for d in sel]     # seeded: same sample


def fake_label_chat(ws, messages, **kw):
    """Labels by keyword: 'нет' -> unmet_need, 'дорог' -> price, 'спасибо' -> video reaction, else praise."""
    user = messages[-1]["content"]
    if messages[0]["content"] == classify.SYSTEM:
        items = []
        for j, body in re.findall(r"### item (\d+) \[video \w+\]\n(.*?)(?=\n\n### item|\Z)", user, re.S):
            low = body.lower()
            if "спасибо" in low:
                items.append({"i": j, "about": "video", "kind": "praise"})
            elif "нет" in low:
                items.append({"i": j, "about": "niche", "kind": "unmet_need", "pain": "no family mode", "products": ["Zen"]})
            elif "дорог" in low:
                items.append({"i": j, "about": "niche", "kind": "price", "pain": "too expensive", "products": []})
            else:
                items.append({"i": j, "about": "niche", "kind": "praise", "products": ["zen"]})
        return {"items": items}, False, {"prompt_tokens": 10, "completion_tokens": 5}
    return {"themes": [{"theme": "Family mode", "kind": "unmet", "description": "d", "count": 9, "ids": [0, 1, 99], "quotes": ["q"]}]}, False, None


def write_docs(ws: Workspace, texts_by_video: dict[str, list[str]], nid: str = "budget") -> None:
    with open(ws.out(fetch.DOCS), "a", encoding="utf-8") as fh:
        for vid, texts in texts_by_video.items():
            for i, t in enumerate(texts):
                fh.write(json.dumps({"niche_id": nid, "lang": "ru", "phrase": "p", "video_id": vid, "video": f"Video {vid}", "channel": "c",
                                     "id": f"{nid}-{vid}-{i}", "date": "2025-06-01", "likes": 0, "replies": 0, "text": t}, ensure_ascii=False) + "\n")


def test_classify_shares_over_comments_about_the_niche(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    write_docs(ws, {"v1": ["Нет режима для всей семьи, ищу давно", "Подписка слишком дорогая для меня", "Спасибо за видео, очень полезно"],
                    "v2": ["Пользуюсь этим приложением три года", "Нет экспорта в таблицу, это неудобно"]})
    monkeypatch.setattr(llm, "chat_json", fake_label_chat)
    classify.run(ws, argparse.Namespace(lang="ru", niches="", dry=False, workers=2))
    (row,) = csv.DictReader(open(ws.out("yt_comments_llm.csv"), encoding="utf-8"))
    assert (row["classified"], row["about_niche"], row["about_video"], row["niche_videos"]) == ("5", "4", "1", "2")
    assert (float(row["unmet_share"]), float(row["unmet_need_share"]), float(row["price_share"]), float(row["praise_share"])) == (0.75, 0.5, 0.25, 0.25)
    assert float(row["top_video_share"]) == 0.5 and row["products"].startswith("zen (3)")
    items = [json.loads(x) for x in open(ws.out("yt_comments_items.jsonl"), encoding="utf-8")]
    assert len(items) == 5 and all(r["kind"] == "other" for r in items if r["about"] == "video")


def llm_row(nid, about=120, videos=3, unmet=0.05, pain=0.1, seek=0.05, question=0.1, praise=0.2, top=0.3):
    return {"niche_id": nid, "about_niche": about, "niche_videos": videos, "unmet_share": unmet, "unmet_need_share": unmet, "price_share": 0,
            "pain_share": pain, "product_request_share": seek, "question_share": question, "praise_share": praise, "top_video_share": top}


def test_verdict_rule_is_relative_with_floors_quiet_and_caution():
    cfg = {**fetch.DEFAULTS["verdict"], "min_cohort": 4}
    rows = {"a": llm_row("a", unmet=0.25), "a2": llm_row("a2", unmet=0.20), "b": llm_row("b", unmet=0.12), "c": llm_row("c", pain=0.35), "d": llm_row("d", seek=0.3),
            "e": llm_row("e", question=0.4, top=0.9), "f": llm_row("f", praise=0.5), "q": llm_row("q", about=20, unmet=0.9)}
    v = report.voice_verdicts(rows, cfg)
    assert v["a"]["verdict"] == "🟢 gap"
    assert v["a2"]["verdict"] == "🟢 gap"
    assert v["b"]["verdict"] == "🟡 mixed"           # above the floor but not in the top third of 7
    assert v["c"]["verdict"] == "🟡 pain" and v["d"]["verdict"] == "🟡 seeking"
    assert v["e"]["verdict"] == "🟡 how-to" and "one video" in v["e"]["reason"]
    assert v["f"]["verdict"] == "🟡 content"
    assert v["q"]["verdict"] == "⚪ quiet" and v["a"]["cohort"] == 7
    # segments: below min_cohort the floors alone decide
    v = report.voice_verdicts({**rows, "x": {**llm_row("x", unmet=0.9), "failed_batches": "2"}}, cfg)
    assert v["x"]["verdict"] == "⚪ incomplete" and v["a"]["cohort"] == 7 and v["a"]["verdict"] == "🟢 gap"
    v = report.voice_verdicts(rows, cfg, {"a": "B2B", "b": "B2B", "a2": "B2C", "c": "B2C", "d": "B2C", "e": "B2C", "f": "B2C", "q": "B2C"})
    assert v["b"]["verdict"] == "🟢 gap" and v["b"]["cohort"] == 2


def test_report_writes_verdicts_themes_and_a_draft_banner(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setattr(http, "request", FakeApi())
    monkeypatch.setattr(llm, "chat_json", fake_check([]))
    fetch.run(ws, argparse.Namespace(lang="ru", niches="", budget=1000))
    write_docs(ws, {"v1": ["Нет режима для всей семьи, ищу давно"] * 1 + [f"Нет функции номер {i} в приложении" for i in range(40)],
                    "v6": [f"Пользуюсь приложением {i} лет, всё устраивает" for i in range(40)]})
    monkeypatch.setattr(llm, "chat_json", fake_label_chat)
    classify.run(ws, argparse.Namespace(lang="ru", niches="", dry=False, workers=3))
    report.run(ws, argparse.Namespace(lang="ru", workers=2))
    voice = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("yt_comments_voice.csv"), encoding="utf-8"))}
    assert voice["budget"]["verdict"] == "🟢 gap" and voice["budget"]["top_theme"] == "Family mode" and voice["budget"]["status"] == "draft"
    assert voice["habits"]["verdict"] == "⚪ quiet"
    themes = json.loads(ws.out("yt_comments_themes.json").read_text(encoding="utf-8"))
    assert themes["budget"]["themes"][0]["count"] == 2           # counted from the valid ids, not the model's count
    md = ws.report("S10-yt-comments.md").read_text(encoding="utf-8")
    assert "DRAFT" in md and "Budget apps" in md and "Family mode" in md and "youtube.com/watch?v=v1" in md


def test_client_waits_on_a_per_minute_limit_and_stops_on_the_daily_quota(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr(fetch.Client, "wait_s", 0)
    answers = [http.HttpError(429, "u", json.dumps({"error": {"message": "Quota exceeded for quota metric 'Search' and limit "
                                                               "'Search requests per minute per user'", "errors": [{"reason": "rateLimitExceeded"}]}})),
               http.Response(200, json.dumps({"items": [{"id": {"videoId": "v1"}}]})),
               http.HttpError(403, "u", json.dumps({"error": {"message": "You have exceeded your quota.", "errors": [{"reason": "quotaExceeded"}]}})),
               http.HttpError(429, "u", json.dumps({"error": {"message": "Quota exceeded for quota metric 'Search Queries' and limit "
                                                               "'Search Queries per day'", "errors": [{"reason": "rateLimitExceeded"}]}}))]

    def api(url, **kw):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(http, "request", api)
    yt = fetch.Client(ws, budget=1000)
    assert yt.search("x", lang="ru", region="RU", after="2023-11-01T00:00:00Z", duration="any") == ["v1"]
    assert yt.used == 100
    with pytest.raises(fetch.youtube.QuotaExceeded, match="quotaExceeded"):
        yt.comment_threads("v1", pages=1)
    with pytest.raises(fetch.youtube.QuotaExceeded, match="per day"):     # the daily search limit: no wait, a stop
        yt.search("y", lang="ru", region="RU", after="2023-11-01T00:00:00Z", duration="any")
    assert yt.used == 100 and not answers
