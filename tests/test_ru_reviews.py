"""Offline tests for the Russian app-review stages (S10): RSS parsing, app choice, fetch from cache, sampling, LLM labels
(with a fake model), the verdict rule and the report."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import pytest
import yaml

from nichefinder import http, llm, tools
from nichefinder.stages import s10_ru_reviews_classify as classify
from nichefinder.stages import s10_ru_reviews_fetch as fetch
from nichefinder.stages import s10_ru_reviews_report as report
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": "2026-11-17"}), encoding="utf-8")
    base = {"who": "people", "task": "do things", "product": "app", "side": "b2c", "tier": "A"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "budget", "name": "Budget apps", "geo": "both", **base},
        {"id": "habits", "name": "Habit trackers", "geo": "ru", **base},
        {"id": "usonly", "name": "US only", "geo": "global", **base},
    ]), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(
        yaml.safe_dump({"tier_a": [{"id": "budget"}, {"id": "usonly"}], "tier_b": ["habits"]}), encoding="utf-8")
    return Workspace(tmp_path)


def write_csv(path: Path, rows: list[dict], bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig" if bom else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def rss_entry(rid, date, rating, text, title="t"):
    return {"id": {"label": rid}, "updated": {"label": f"{date}T10:00:00-07:00"}, "im:rating": {"label": str(rating)},
            "title": {"label": title}, "content": {"label": text}, "im:version": {"label": "1.0"}, "im:voteSum": {"label": "2"}}


def test_parse_rss_list_single_and_missing():
    page = {"feed": {"entry": [{"im:name": {"label": "The app itself"}}, rss_entry("1", "2026-11-01", 2, "Crashes on start")]}}
    (r,) = fetch.parse_rss(page)
    assert (r["id"], r["date"], r["rating"], r["text"], r["thumbs"]) == ("1", "2026-11-01", 2, "Crashes on start", 2)
    assert len(fetch.parse_rss({"feed": {"entry": rss_entry("2", "2026-11-02", 5, "Fine")}})) == 1
    assert fetch.parse_rss({"feed": {"id": {"label": "x"}}}) == []


def apps_fixture(ws: Workspace) -> None:
    write_csv(ws.out("appstore_apps.csv"), [
        {"niche_id": "budget", "store": "ru", "track_id": "111", "name": "Money RU", "seller": "A", "ratings": 900, "rating": 4.5, "relevant": 1},
        {"niche_id": "budget", "store": "ru", "track_id": "112", "name": "Coins", "seller": "B", "ratings": 300, "rating": 4.1, "relevant": 1},
        {"niche_id": "budget", "store": "ru", "track_id": "113", "name": "Tiny", "seller": "C", "ratings": 5, "rating": 5.0, "relevant": 1},
        {"niche_id": "budget", "store": "ru", "track_id": "114", "name": "Off topic", "seller": "D", "ratings": 9000, "rating": 4.9, "relevant": 0},
        {"niche_id": "budget", "store": "us", "track_id": "115", "name": "US app", "seller": "E", "ratings": 9000, "rating": 4.9, "relevant": 1},
        {"niche_id": "usonly", "store": "ru", "track_id": "116", "name": "Stray", "seller": "F", "ratings": 9000, "rating": 4.9, "relevant": 1},
    ])
    write_csv(ws.out("gplay_apps.csv"), [
        {"niche_id": "habits", "country": "ru", "appId": "com.habit", "title": "Habit", "developer": "G", "ratings": 5000, "score": 4.2},
        {"niche_id": "habits", "country": "us", "appId": "com.habit.us", "title": "Habit US", "developer": "G", "ratings": 9000, "score": 4.2},
    ], bom=True)


def test_pick_apps_leading_relevant_russian_apps(tmp_path):
    ws = make_ws(tmp_path)
    apps_fixture(ws)
    ids = fetch.target_niches(ws)
    assert ids == ["budget", "habits"]   # geo global is not measured
    st = {**fetch.DEFAULTS["fetch"], "apps_per_store": 1}
    got = [(a["niche_id"], a["store"], a["app_id"]) for a in fetch.pick_apps(ws, ids, st)]
    assert got == [("budget", "appstore", "111"), ("habits", "gplay", "com.habit")]
    got = [a["app_id"] for a in fetch.pick_apps(ws, ids, fetch.DEFAULTS["fetch"])]
    assert got == ["111", "112", "com.habit"]   # 113 has too few ratings, 114 is not relevant, 115 is the US store


def test_fetch_reads_cached_pages_and_applies_the_window(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    apps_fixture(ws)
    month = "2026-11"
    pages = {"111": [rss_entry("a1", "2026-11-10", 1, "Lost all my data after the update"), rss_entry("a2", "2025-01-01", 1, "Too old"),
                     rss_entry("a3", "2026-10-01", 5, "")],
             "112": [rss_entry("b1", "2026-09-09", 4, "Good, but needs export")]}
    for app_id, entries in pages.items():
        path = http.cache_file(ws.cache("ru_reviews"), f"{month}|appstore|{app_id}|1")
        path.write_text(json.dumps({"feed": {"entry": entries}}), encoding="utf-8")
    (ws.cache("gplay_reviews") / f"ru_com.habit_{month}.json").write_text(json.dumps({"reviews": [
        {"id": "g1", "date": "2026-11-15T08:00:00.000Z", "score": 2, "text": "Subscription is too expensive", "thumbsUp": 3}]}), encoding="utf-8")

    def no_node(*a, **k):
        raise AssertionError("the Node helper must not run when every app is cached")

    monkeypatch.setattr(tools, "run_node", no_node)
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call"))
    fetch.run(ws, argparse.Namespace(niches=""))
    docs = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8")]
    assert sorted(d["id"] for d in docs) == ["a1", "b1", "g1"]   # too old and empty text are dropped
    g1 = next(d for d in docs if d["id"] == "g1")
    assert (g1["niche_id"], g1["store"], g1["date"], g1["rating"]) == ("habits", "gplay", "2026-11-15", 2)
    apps = {r["app_id"]: r for r in csv.DictReader(open(ws.out(fetch.APPS), encoding="utf-8"))}
    assert (apps["111"]["fetched"], apps["111"]["kept"], apps["111"]["oldest"], apps["111"]["status"]) == ("3", "1", "2026-11-10", "ok")

    # a partial run replaces only its own niches
    fetch.run(ws, argparse.Namespace(niches="habits"))
    docs = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8")]
    assert sorted(d["id"] for d in docs) == ["a1", "b1", "g1"]


def test_sample_round_robin_over_apps_and_min_chars():
    long = "x" * 50
    docs = ([{"store": "appstore", "app_id": "big", "id": f"b{i}", "text": long} for i in range(30)]
            + [{"store": "gplay", "app_id": "small", "id": f"s{i}", "text": long} for i in range(3)]
            + [{"store": "gplay", "app_id": "small", "id": "short", "text": "Super!"}])
    got = classify.sample(docs, 10, 40)
    assert len(got) == 10
    assert sum(1 for d in got if d["app_id"] == "small") == 3   # the small app gets its whole share, not 1 in 11
    assert all(d["id"] != "short" for d in got)
    assert [d["id"] for d in got] == [d["id"] for d in classify.sample(list(reversed(docs)), 10, 40)]   # deterministic


def fake_chat_json(ws, messages, **kw):
    """Labels by keyword: 'export' -> missing_feature, 'crash' -> bug, 'driver' -> service, else praise."""
    user = messages[-1]["content"]
    if messages[0]["content"] == classify.SYSTEM:
        items = []
        for j, body in re.findall(r"### item (\d+)\n[^\n]*\n(.*?)(?=\n\n### item|\Z)", user, re.S):
            low = body.lower()
            if "driver" in low:
                items.append({"i": j, "about": "service", "intent": "other"})
            elif "export" in low:
                items.append({"i": j, "about": "app", "intent": "missing_feature", "pain": "no export", "quote": body[:40], "wtp": "none"})
            elif "crash" in low:
                items.append({"i": j, "about": "app", "intent": "bug", "pain": "crashes", "from_to": "a -> b", "wtp": "none"})
            else:
                items.append({"i": j, "about": "app", "intent": "praise", "wtp": "worth_it"})
        return {"items": items}, False, {"prompt_tokens": 10, "completion_tokens": 5}
    return {"themes": [{"theme": "No export", "kind": "unmet", "count": 2, "quotes": ["q"]}]}, False, None


def test_classify_shares_over_reviews_about_the_app(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    texts = ["Please add export to Excel, I need it every month"] * 2 + ["It crashes every time I open the report screen"] \
        + ["The driver was late and rude, never again with them"] + ["Works great, simple and clean, I use it every day"]
    with open(ws.out(fetch.DOCS), "w", encoding="utf-8") as fh:
        for i, t in enumerate(texts):
            fh.write(json.dumps({"niche_id": "budget", "store": "gplay", "app_id": f"app{i % 2}", "app": f"App {i % 2}", "id": str(i),
                                 "date": "2026-11-01", "rating": 3, "title": "", "text": t}) + "\n")
    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    classify.run(ws, argparse.Namespace(niches="", dry=False))
    (row,) = csv.DictReader(open(ws.out("ru_reviews_llm.csv"), encoding="utf-8"))
    assert (row["classified"], row["about_app"], row["apps"]) == ("5", "4", "2")
    assert (float(row["unmet_share"]), float(row["quality_share"]), float(row["praise_share"])) == (0.5, 0.25, 0.25)
    assert row["top_theme"] == "No export" and row["top_switch"] == "a -> b"
    themes = json.loads(ws.out("ru_reviews_themes.json").read_text(encoding="utf-8"))["budget"]
    assert sum(a["n"] for a in themes["apps"].values()) == 4 and themes["about"]["service"] == 1


def llm_row(nid, about_app=120, apps=3, unmet=0.1, quality=0.2, praise=0.3):
    return {"niche_id": nid, "about_app": about_app, "apps": apps, "unmet_share": unmet, "quality_share": quality, "praise_share": praise,
            "missing_feature_share": unmet, "pricing_share": 0, "switching_share": 0}


def test_verdict_rule_is_relative_with_floors():
    cfg = fetch.DEFAULTS["verdict"]
    rows = {r["niche_id"]: r for r in [
        llm_row("gap", unmet=0.40), llm_row("gap_low_floor", unmet=0.12, quality=0.1), llm_row("quality", unmet=0.05, quality=0.60),
        llm_row("content", unmet=0.02, quality=0.05, praise=0.7), llm_row("mixed1", unmet=0.08), llm_row("mixed2", unmet=0.09, quality=0.25),
        llm_row("quiet", about_app=20, unmet=0.9)]}
    v = report.reviews_verdicts(rows, cfg)
    assert v["gap"]["verdict"] == "🟢 gap"
    assert v["gap_low_floor"]["verdict"] != "🟢 gap"   # second in the cohort, but under the 15 % floor
    assert v["quality"]["verdict"] == "🟡 quality"
    assert v["content"]["verdict"] == "🟡 content"
    assert v["mixed1"]["verdict"] == "🟡 mixed"
    assert v["quiet"]["verdict"] == "⚪ quiet" and v["gap"]["cohort"] == 6
    # a small cohort: the floors alone decide
    small = report.reviews_verdicts({k: rows[k] for k in ("gap", "mixed2")}, cfg)
    assert small["gap"]["verdict"] == "🟢 gap" and small["mixed2"]["verdict"] == "🟡 mixed"


def test_report_writes_verdicts_and_a_draft_banner(tmp_path):
    ws = make_ws(tmp_path)
    write_csv(ws.out(fetch.APPS), [{"niche_id": "budget", "store": "gplay", "app_id": "a", "app": "App", "developer": "D", "ratings": 100,
                                    "rating": 4.0, "fetched": 2, "kept": 2, "oldest": "2026-10-01", "status": "ok"}])
    with open(ws.out(fetch.DOCS), "w", encoding="utf-8") as fh:
        for i, r in enumerate((1, 5)):
            fh.write(json.dumps({"niche_id": "budget", "store": "gplay", "app_id": "a", "app": "App", "id": str(i), "date": "2026-11-01",
                                 "rating": r, "title": "", "text": "y" * 60}) + "\n")
    row = {**llm_row("budget", unmet=0.3), "sampled": 2, "classified": 2, "app_share": 1, "bug_share": 0, "ux_share": 0, "ads_share": 0,
           "support_share": 0, "too_expensive": 0, "worth_it": 0, "wants_free": 0, "cancelled": 0, "themes": 0, "top_theme": "",
           "top_theme_kind": "", "top_theme_count": "", "top_switch": ""}
    write_csv(ws.out("ru_reviews_llm.csv"), [row])
    report.run(ws, argparse.Namespace())
    md = ws.report("S10-ru-reviews.md").read_text(encoding="utf-8")
    assert "DRAFT" in md and "Budget apps" in md and "| 2 (2) | 50% |" in md
    (v,) = csv.DictReader(open(ws.out("ru_reviews_verdict.csv"), encoding="utf-8"))
    assert v["verdict"] == "🟢 gap" and v["status"] == "draft"
