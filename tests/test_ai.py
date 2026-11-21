"""Offline tests for the AI checks: the AI search volume experiment (s3_ai_volume), the AI substitute probe
(nichefinder.aiprobe, s5_ai_substitute, info_ai) and the I:ai-answers flag in info_score."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pytest
import yaml

from nichefinder import aiprobe, llm
from nichefinder.sources import dataforseo as dfs
from nichefinder.stages import info_ai, info_score, s3_ai_volume, s5_ai_substitute
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us"], "as_of": "2026-11-21"}), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "dog-daycare", "name": "Dog daycare software", "who": "dog daycares", "task": "bookings, vaccine records",
         "product": "SaaS $50/month", "geo": "global", "side": "b2b-smb", "tier": "A", "competitors": ["Gingr", "PetExec"]},
        {"id": "essay-helper", "name": "Essay helpers", "who": "students", "task": "write and polish essays",
         "product": "app $10/month", "geo": "global", "side": "b2c", "tier": "A", "competitors": ["Grammarly"]},
        {"id": "plant-id", "name": "Plant identification", "who": "gardeners", "task": "identify a plant from a photo",
         "product": "app $5/month", "geo": "global", "side": "b2c", "tier": "A"},
    ]), encoding="utf-8")
    q = {
        "dog-daycare": {"en": [{"q": "dog daycare software", "i": "category", "anchor": True},
                               {"q": "kennel software", "i": "category"},
                               {"q": "how to run a dog daycare", "i": "problem"},
                               {"q": "gingr", "i": "brand", "b": "Gingr"}]},
        "essay-helper": {"en": [{"q": "essay writer app", "i": "category", "anchor": True},
                                {"q": "how to write an essay", "i": "problem"}]},
        "plant-id": {"en": [{"q": "plant identifier app", "i": "category", "anchor": True},
                            {"q": "what plant is this", "i": "problem"}]},
    }
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump(q), encoding="utf-8")
    (tmp_path / "config" / "overrides.yaml").write_text(yaml.safe_dump({
        "dog-daycare": {"platform_risk": 0}, "essay-helper": {"platform_risk": 1}, "plant-id": {"platform_risk": 2}}),
        encoding="utf-8")
    return Workspace(tmp_path)


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---- s3_ai_volume -------------------------------------------------------------

def test_spearman_and_ranks():
    assert s3_ai_volume.ranks([10, 20, 20, 5]) == [2.0, 3.5, 3.5, 1.0]
    assert s3_ai_volume.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert s3_ai_volume.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert s3_ai_volume.spearman([1, 2], [1, 2]) is None
    assert s3_ai_volume.spearman([1, 1, 1], [1, 2, 3]) is None


def write_dfs_us(ws: Workspace, vols: dict[str, int]) -> None:
    with open(ws.out("dfs_us.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["keyword", "search_volume", "monthly_json"])
        w.writeheader()
        for k, v in vols.items():
            w.writerow({"keyword": k, "search_volume": v, "monthly_json": json.dumps([["2026-09", v], ["2026-10", v]])})


def test_ai_volume_reads_the_cache_and_reports(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    google = {"dog daycare software": 1000, "kennel software": 500, "how to run a dog daycare": 50, "gingr": 20000,
              "essay writer app": 300, "how to write an essay": 40000, "plant identifier app": 2000, "what plant is this": 50000}
    write_dfs_us(ws, google)
    ai = {"dog daycare software": 0, "kennel software": 0, "how to run a dog daycare": 10, "gingr": 30,
          "essay writer app": 900, "how to write an essay": 8000, "plant identifier app": 400, "what plant is this": 900000}
    kws, _ = s3_ai_volume.keywords(ws)
    items = [{"keyword": k, "ai_search_volume": ai[k],
              "ai_monthly_searches": [{"year": 2026, "month": 10, "ai_search_volume": ai[k]}]} for k in kws]
    task = {"keywords": kws, "location_code": 2840, "language_code": "en"}
    dfs._cache_path(ws, "aisv", task).write_text(json.dumps(
        {"cost": 0.0008, "tasks": [{"status_code": 20000, "result": [{"items": items}]}]}), encoding="utf-8")
    monkeypatch.setattr(dfs, "_request", lambda *a, **k: pytest.fail("network call"))
    s3_ai_volume.run(ws, argparse.Namespace(dry=False))
    rows = {r["keyword"]: r for r in read_csv(ws.out("ai_volume_us.csv"))}
    assert rows["what plant is this"]["ai_search_volume"] == "900000"
    assert rows["kennel software"]["niches"] == "dog-daycare" and rows["kennel software"]["intents"] == "category"
    niches = {r["niche_id"]: r for r in read_csv(ws.out("ai_volume_niches.csv"))}
    assert niches["dog-daycare"]["google_category"] == "1500" and niches["dog-daycare"]["ai_category"] == "0"
    report = ws.report("S3-ai-volume.md").read_text(encoding="utf-8")
    assert "Verdict" in report and "what plant is this" in report     # 18x Google: listed as a suspected collision
    assert "| no question | gingr |" in report                          # 20,000 on Google, almost nothing in the index


def test_artifacts_split_collisions_and_no_question_keywords():
    rows = [{"keyword": "whering", "google_volume": 4400, "ai_search_volume": 28_000_000},
            {"keyword": "uscis case tracker", "google_volume": 60500, "ai_search_volume": 96},
            {"keyword": "stretching app", "google_volume": 1000, "ai_search_volume": 392}]
    coll, noq = s3_ai_volume.artifacts(rows)
    assert [r["keyword"] for r in coll] == ["whering"]
    assert [r["keyword"] for r in noq] == ["uscis case tracker"]


# ---- aiprobe ------------------------------------------------------------------

def test_normalize_clamps_and_dedupes():
    out = aiprobe.normalize({"covers": "5", "brands": ["Gingr", " gingr ", "PetExec"], "diy": "magic",
                             "missing": ["a", "", "b"], "can_do": ["plan"], "reason": "r"})
    assert out["covers"] is None and out["brands"] == ["Gingr", "PetExec"] and out["diy"] == "none"
    assert out["missing"] == ["a", "b"] and out["can_do"] == ["plan"]
    assert aiprobe.normalize({"covers": 2})["covers"] == 2


def test_aggregate_takes_the_median_and_counts_brands():
    runs = [{"covers": 2, "brands": ["ChatGPT", "Grammarly"], "diy": "chatbot", "can_do": ["x"], "missing": [], "reason": "two"},
            {"covers": 1, "brands": ["Grammarly"], "diy": "none", "can_do": ["y"], "missing": ["m"], "reason": "one"},
            {"covers": 2, "brands": ["Quillbot", "grammarly"], "diy": "chatbot", "can_do": [], "missing": [], "reason": "two again"}]
    agg = aiprobe.aggregate(runs)
    assert agg["covers"] == 2 and agg["votes"] == [2, 1, 2] and agg["reason"] == "two" and agg["diy"] == "chatbot"
    assert agg["brands"][0] == "Grammarly"                  # named by all three answers
    assert aiprobe.aggregate([{"covers": 0, "brands": []}, {"covers": 2, "brands": []}])["covers"] == 0   # median_low
    assert aiprobe.aggregate([])["covers"] is None


def test_listed_named_matches_either_way():
    assert aiprobe.listed_named(["Gingr Pro", "Paprika 3"], ["Gingr", "PetExec", "Google Travel / Paprika (platform)"]) == \
        ["Gingr", "Google Travel / Paprika (platform)"]


def fake_chat_json(ws, messages, **kw):
    """Requests -> three buyer messages; answers echo the request; the judge rates by the niche in the context."""
    system, user = messages[0]["content"], messages[1]["content"]
    if system == aiprobe.REQUEST_SYSTEM:
        return {"requests": ["help me one", "help me two", "what app should I use"]}, False, {"prompt_tokens": 10, "completion_tokens": 5}
    if system == aiprobe.ANSWER_SYSTEM:
        return {"answer": f"Here is how: {user}. Try Gingr or Grammarly."}, False, {"prompt_tokens": 10, "completion_tokens": 50}
    covers = 2 if "Essay helpers" in user else 0
    if "what app should I use" in user:
        covers = max(0, covers - 1)
    return ({"can_do": ["write"], "missing": ["records"], "covers": covers, "reason": "because",
             "brands": ["Gingr", "Grammarly"], "diy": "chatbot" if covers else "none"}, False,
            {"prompt_tokens": 20, "completion_tokens": 20})


def test_probe_runs_three_requests_and_sums_usage(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    res = aiprobe.probe(ws, "Niche: Essay helpers", aiprobe.SOFTWARE_RUBRIC, "en")
    assert res["votes"] == [2, 2, 1] and res["covers"] == 2 and len(res["runs"]) == 3
    assert res["usage"] == {"in": 10 + 3 * 30, "out": 5 + 3 * 70}


def test_check_flags_only_a_chatbot_rated_above_the_manual_call():
    assert s5_ai_substitute.check(2, 1).startswith("review G3")
    assert s5_ai_substitute.check(2, 0).startswith("review G3")
    assert s5_ai_substitute.check(1, 0).startswith("consider P1")
    assert s5_ai_substitute.check(0, 2) == ""          # a veto from an OS feature is outside the probe
    assert s5_ai_substitute.check(1, 1) == "" and s5_ai_substitute.check(0, 1) == ""
    assert s5_ai_substitute.check(2, "") == "" and s5_ai_substitute.check(None, 2) == ""


def test_s5_ai_substitute_writes_csv_and_report(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    s5_ai_substitute.run(ws, argparse.Namespace(all=True, niches="", workers=2, dry=False))
    rows = {r["niche_id"]: r for r in read_csv(ws.out("ai_substitute.csv"))}
    assert rows["essay-helper"]["covers"] == "2" and rows["essay-helper"]["votes"] == "2/2/1"
    assert rows["essay-helper"]["check"].startswith("review G3")          # covers 2 > platform_risk 1
    assert rows["plant-id"]["check"] == ""                                # platform_risk 2, covers 0: not refuted
    assert rows["dog-daycare"]["covers"] == "0" and rows["dog-daycare"]["check"] == ""
    assert rows["dog-daycare"]["listed_named"] == "1" and rows["dog-daycare"]["listed_total"] == "2"
    answers = [json.loads(x) for x in open(ws.out("ai_substitute_answers.jsonl"), encoding="utf-8")]
    assert {a["niche_id"] for a in answers} == set(rows) and all(len(a["runs"]) == 3 for a in answers)
    report = ws.report("S5-ai-substitute.md").read_text(encoding="utf-8")
    assert "The chatbot delivers the outcome, the manual platform risk is lower" in report and "essay-helper" in report


def test_s5_ai_substitute_rejects_unknown_niches(tmp_path):
    ws = make_ws(tmp_path)
    with pytest.raises(SystemExit):
        s5_ai_substitute.run(ws, argparse.Namespace(all=False, niches="nope", workers=1, dry=True))


# ---- info_ai and the info_score flag ------------------------------------------

def test_info_ai_writes_ratings(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (tmp_path / "config" / "info_topics.yaml").write_text(yaml.safe_dump({
        "_settings": {"lang": "ru"}, "topics": [
            {"id": "essays", "q": ["essay"], "who": "students", "task": "write essays", "product": "Essay helpers guide"},
            {"id": "knitting", "q": ["knitting"], "who": "beginners", "task": "learn to knit", "product": "video course"}]}),
        encoding="utf-8")
    seen_langs = []

    def chat(ws_, messages, **kw):
        if messages[0]["content"] == aiprobe.REQUEST_SYSTEM:
            seen_langs.append("Language: Russian" in messages[1]["content"])
        return fake_chat_json(ws_, messages, **kw)

    monkeypatch.setattr(llm, "chat_json", chat)
    info_ai.run(ws, argparse.Namespace(topics="", workers=2, dry=False))
    rows = {r["topic_id"]: r for r in read_csv(ws.out("info_ai.csv"))}
    assert rows["essays"]["covers"] == "2" and rows["knitting"]["covers"] == "0"
    assert seen_langs and all(seen_langs)                                 # requests in the cohort language


def test_info_ai_without_topics_is_a_no_op(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: pytest.fail("LLM call"))
    info_ai.run(ws, argparse.Namespace(topics="", workers=1, dry=False))
    assert not ws.out("info_ai.csv").exists()


def test_info_score_flags_ai_answers_without_touching_the_score():
    base = {"status": "ok", "n_videos": "30", "views_median": "5000", "views_p90": "50000", "breakout_share": "0.1",
            "small_share": "0.2", "tg_channel_share": "0.3", "offer_share": "0.1", "top3_share": "0.2", "recent_ratio": "1"}
    rows = [{**base, "topic_id": "a", "ai_covers": "2"}, {**base, "topic_id": "b", "ai_covers": "1"},
            {**base, "topic_id": "c"}]
    scored = {r["topic_id"]: r for r in info_score.score_rows(rows, {}, 70)}
    assert "I:ai-answers" in scored["a"]["flags"]
    assert "I:ai-answers" not in scored["b"]["flags"] and "I:ai-answers" not in scored["c"]["flags"]
    assert scored["a"]["score"] == scored["b"]["score"] == scored["c"]["score"]
    off = {r["topic_id"]: r for r in info_score.score_rows(rows, {"flags": {"ai_answers": None}}, 70)}
    assert "I:ai-answers" not in off["a"]["flags"]


def test_ai_search_volume_parses_items_and_caches(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    calls = []

    def fake_request(method, path, body=None):
        calls.append(path)
        return {"cost": 0.0002, "tasks": [{"status_code": 20000, "result": [{"items": [
            {"keyword": "Dog Daycare Software", "ai_search_volume": 12, "ai_monthly_searches": []}]}]}]}

    monkeypatch.setattr(dfs, "_request", fake_request)
    data, cost = dfs.ai_search_volume(ws, ["dog daycare software"])
    assert data["dog daycare software"]["ai_search_volume"] == 12 and cost == 0.0002
    assert dfs.ai_search_volume_cached(ws, ["dog daycare software"])
    dfs.ai_search_volume(ws, ["dog daycare software"])
    assert len(calls) == 1 and calls[0].startswith("/ai_optimization/")
