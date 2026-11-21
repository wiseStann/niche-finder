"""Offline tests for s5_ecosystems (Chrome Web Store, Atlassian Marketplace) and s5_oss (GitHub substitutes)."""
from __future__ import annotations

import argparse
import csv
import json
import urllib.parse
from pathlib import Path

import yaml

from nichefinder import http
from nichefinder.stages import s5_ecosystems, s5_oss
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us"], "as_of": "2026-11-21"}), encoding="utf-8")
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": [{"id": "focus"}, {"id": "feedback"}]}), encoding="utf-8")
    (cfg / "deal_keywords.yaml").write_text(yaml.safe_dump({"feedback": r"\b(feature requests?|feedback board)\b"}), encoding="utf-8")
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([{"id": "focus"}, {"id": "feedback"}, {"id": "other"}]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "focus": {"en": [{"q": "free screen time app for kids", "i": "category", "anchor": True}, {"q": "opal", "i": "brand", "b": "Opal"}]},
        "feedback": {"en": [{"q": "feature request software", "i": "category", "anchor": True}]},
    }), encoding="utf-8")
    return Workspace(tmp_path)


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8")))


# ---- Chrome Web Store / Atlassian ------------------------------------------------

def cws_item(ext_id: str, name: str, users, desc: str = "") -> list:
    o = [None] * 20
    o[0], o[2], o[3], o[4], o[6], o[11], o[14] = ext_id, name, 4.5, 10, desc, ["productivity/tools", None, 5], users
    return o


def cws_payload(items: list[list], token: str | None, total: int) -> list:
    return [[[[None, None, None, None, None, [[[[[it]] for it in items]]]]]], None, [token, None, None, total]]


def rpc_body(payload) -> str:
    inner = json.dumps(payload)
    line = json.dumps([["wrb.fr", "zTyKYc", inner, None, None, None, "generic"], ["di", 10]])
    return ")]}'\n\n" + str(len(line)) + "\n" + line + "\n25\n[[\"e\",4,null,null,1]]\n"


def test_cws_parsers_read_items_tail_and_page():
    a, b = "a" * 32, "b" * 32
    data = cws_payload([cws_item(a, "BlockSite", 1_000_000, "Block websites"), cws_item(b, "Tiny", None)], "TOK", 735)
    items = s5_ecosystems.cws_items(data)
    assert [(i["id"], i["name"], i["size"]) for i in items] == [(a, "BlockSite", 1_000_000), (b, "Tiny", 0)]
    assert s5_ecosystems.cws_tail(data) == ("TOK", 735)
    assert s5_ecosystems.parse_rpc(rpc_body(data)) == data
    assert s5_ecosystems.parse_rpc(")]}'\n\n103\n[[\"wrb.fr\",\"zTyKYc\",null,null,null,[3],\"generic\"]]") is None
    html = "<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:" + json.dumps(data) + ", sideChannel: {}});</script>"
    assert s5_ecosystems.parse_search_page(html) == data


def test_concentration_matches_shopify_style_metrics():
    rows = [{"name": n, "size": s, "ratings": 1, "free": f} for n, s, f in (("A", 600, 1), ("B", 300, 0), ("C", 100, 0), ("D", 0, 1))]
    m = s5_ecosystems.concentration(rows)
    assert m["products"] == 4 and m["users_total"] == 1000 and m["top1"] == "A"
    assert m["top1_share"] == 0.6 and m["top3_share"] == 1.0 and m["hhi"] == 0.46
    assert m["players_100"] == 3 and m["players_1k"] == 0 and m["free_share"] == 0.5
    assert s5_ecosystems.concentration([])["top1_share"] == ""


def test_ecosystems_run_filters_dedups_and_marks_free(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (ws.config("ecosystems_map.yaml")).write_text(yaml.safe_dump({
        "_settings": {"cws_pages": 2, "atlassian_pages": 1},
        "focus": {"cws": ["website blocker", "focus mode"], "match": r"\b(block|focus)", "not": r"\bad ?block"},
        "feedback": {"atlassian": ["feature request"]},                 # no match: falls back to deal_keywords
        "other": {"cws": ["x"]},                                          # not shortlisted: skipped
    }), encoding="utf-8")
    a, b, c, d = "a" * 32, "b" * 32, "c" * 32, "d" * 32
    pages = {
        ("website blocker", None): cws_payload([cws_item(a, "BlockSite", 1000, "Block sites"), cws_item(b, "AdBlock Pro", 9000, "block ads")], "T1", 500),
        ("website blocker", "T1"): cws_payload([cws_item(c, "Focus Timer", 200, "")], None, 500),
        ("focus mode", None): cws_payload([cws_item(a, "BlockSite", 1000, "Block sites"), cws_item(d, "Weather", 50, "")], None, 40),
    }
    calls = []

    def fake_request(url, method="GET", data=None, **kw):
        assert "batchexecute" in url and method == "POST"
        freq = json.loads(urllib.parse.unquote(data[len("f.req="):]))
        req = json.loads(freq[0][0][1])
        q, size = req[0][1][3][0], req[0][1][3][1]
        calls.append((q, size[1] if len(size) > 1 else None))
        return http.Response(200, rpc_body(pages[(q, size[1] if len(size) > 1 else None)]))

    addons = {"": [("jira.canny", "Canny for Jira", 500, "Collect feature requests"), ("jira.tempo", "Tempo", 25000, "Time tracking"),
                   ("jira.vote", "Votes", 100, "Feature requests and voting")],
              "free": [("jira.vote", "Votes", 100, "Feature requests and voting")]}

    def fake_get_json(url, **kw):
        cost = "free" if "cost=free" in url else ""
        return {"count": 3, "_embedded": {"addons": [
            {"key": k, "name": n, "tagLine": t, "summary": "", "_links": {"alternate": {"href": f"/apps/{k}"}},
             "_embedded": {"distribution": {"totalInstalls": i}, "reviews": {"count": 2, "averageStars": 4.0}, "categories": []}}
            for k, n, i, t in addons[cost]]}}

    monkeypatch.setattr(http, "request", fake_request)
    monkeypatch.setattr(http, "get_json", fake_get_json)
    monkeypatch.setattr(s5_ecosystems.time, "sleep", lambda s: None)
    monkeypatch.setattr(s5_ecosystems, "CWS_PAGE", 2)              # a full page means "there may be more"
    s5_ecosystems.run(ws, argparse.Namespace(niche=[], store=[]))
    assert calls == [("website blocker", None), ("website blocker", "T1"), ("focus mode", None)]
    rows = {(r["niche_id"], r["store"]): r for r in read_csv(ws.out("ecosystems_metrics.csv"))}
    assert set(rows) == {("focus", "cws"), ("feedback", "atlassian")}
    f = rows[("focus", "cws")]
    assert (f["fetched"], f["products"], f["users_total"], f["top1"], f["top1_share"]) == ("4", "2", "1200", "BlockSite", "0.833")
    assert f["free_share"] == "" and "website blocker=500" in f["reported"]
    fb = rows[("feedback", "atlassian")]
    assert (fb["products"], fb["users_total"], fb["top1"], fb["free_share"], fb["unit"]) == ("2", "600", "Canny for Jira", "0.5", "installs")
    items = read_csv(ws.out("ecosystems_items.csv"))
    assert {i["name"]: i["relevant"] for i in items if i["store"] == "cws"} == {"BlockSite": "1", "Focus Timer": "1", "AdBlock Pro": "0", "Weather": "0"}
    # a second run in the same month is served from the cache
    monkeypatch.setattr(http, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    s5_ecosystems.run(ws, argparse.Namespace(niche=["focus"], store=["cws"]))


# ---- GitHub OSS substitutes ------------------------------------------------------

def test_strip_phrase_and_phrase_regex():
    st = s5_oss.DEFAULTS
    assert s5_oss.strip_phrase("free invoice app for small business", st) == "invoice"
    assert s5_oss.strip_phrase("app blocker", st) == "app blocker"
    assert s5_oss.strip_phrase("website builder", st) == "website builder"
    assert s5_oss.strip_phrase("software", st) == ""
    rx = s5_oss.phrase_regex("feature request")
    assert rx.search("Fider - open platform to collect feature-requests")
    assert rx.search(s5_oss.repo_text({"name": "featureRequestBoard", "description": None, "topics": []}))
    assert not rx.search("features to request")


def repo(name, stars, pushed, desc="", archived=False, topics=()):
    return {"full_name": f"o/{name}", "name": name, "stargazers_count": stars, "pushed_at": f"{pushed}T00:00:00Z", "archived": archived,
            "description": desc, "topics": list(topics), "license": {"spdx_id": "MIT"}, "html_url": f"https://github.com/o/{name}", "language": "Go"}


def test_oss_run_counts_maintained_and_flags(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    ws.config("oss.yaml").write_text(yaml.safe_dump({"queries": {"focus": ["screen time"]}}), encoding="utf-8")
    answers = {
        "screen time": [repo("Olauncher", 4000, "2026-11-20", "Reduce your screen time"),
                        repo("awesome-screen-time", 2000, "2026-10-01", "Awesome list about screen time"),
                        repo("old-blocker", 1500, "2023-01-01", "Screen time limits", archived=True),
                        repo("timelapse", 900, "2026-01-01", "Screen recorder with time stamps")],
        "feature request": [repo("fider", 3000, "2025-06-01", "Collect feature requests")],
    }
    seen_urls, seen_headers = [], []

    def fake_get_json(url, *, cache=None, cache_key=None, headers=None, **kw):
        seen_urls.append(url)
        seen_headers.append(headers or {})
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0]
        phrase = q.split('"')[1]
        return {"total_count": len(answers[phrase]), "items": answers[phrase]}

    monkeypatch.setattr(http, "get_json", fake_get_json)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    s5_oss.run(ws, argparse.Namespace(niche=[]))
    assert all("test-token" not in u for u in seen_urls) and seen_headers[0]["Authorization"] == "Bearer test-token"
    rows = {r["niche_id"]: r for r in read_csv(ws.out("oss_substitutes.csv"))}
    f = rows["focus"]
    assert (f["relevant"], f["stars_1k"], f["maintained_1k"], f["top_repo"], f["flags"]) == ("2", "2", "1", "o/Olauncher", "O:oss-substitute")
    fb = rows["feedback"]                                   # 3,000 stars but last pushed 17 months before as_of
    assert fb["phrases"] == "feature request" and fb["stars_1k"] == "1" and fb["maintained_1k"] == "0" and fb["flags"] == ""
    repos = {r["full_name"]: r for r in read_csv(ws.out("oss_repos.csv"))}
    assert repos["o/awesome-screen-time"]["relevant"] == "0" and repos["o/timelapse"]["relevant"] == "0"
    assert repos["o/old-blocker"]["maintained"] == "0"


def test_oss_one_word_phrase_needs_name_or_topic_and_not_regex(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    ws.config("oss.yaml").write_text(yaml.safe_dump({"queries": {"focus": ["recipe"], "feedback": ["feedback board"]},
                                                     "not": {"feedback": r"issues and feature requests for"}}), encoding="utf-8")
    answers = {
        "recipe": [repo("claude-cookbooks", 50000, "2026-11-01", "Notebooks and recipes for LLM apps"),
                   repo("mealie", 14000, "2026-11-20", "Self-hosted recipe manager", topics=["recipe-manager"]),
                   repo("tandoor-recipes", 5000, "2026-11-20", "Self-hosted application")],
        "feedback board": [repo("logchimp", 1100, "2026-11-21", "Open-source feedback board"),
                           repo("tracker", 2000, "2026-11-21", "Bugs, issues and feature requests for SomeApp feedback board")],
    }

    def fake_get_json(url, **kw):
        phrase = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0].split('"')[1]
        return {"total_count": len(answers[phrase]), "items": answers[phrase]}

    monkeypatch.setattr(http, "get_json", fake_get_json)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    s5_oss.run(ws, argparse.Namespace(niche=[]))
    repos = {r["full_name"]: r["relevant"] for r in read_csv(ws.out("oss_repos.csv"))}
    assert repos == {"o/mealie": "1", "o/tandoor-recipes": "1", "o/claude-cookbooks": "0", "o/logchimp": "1", "o/tracker": "0"}
    rows = {r["niche_id"]: r for r in read_csv(ws.out("oss_substitutes.csv"))}
    assert rows["focus"]["top_repo"] == "o/mealie" and rows["feedback"]["top_repo"] == "o/logchimp"
    s5_oss.run(ws, argparse.Namespace(niche=["focus"]))                 # a partial run keeps the other niches
    assert {r["niche_id"] for r in read_csv(ws.out("oss_substitutes.csv"))} == {"focus", "feedback"}
