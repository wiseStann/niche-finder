"""Offline tests for the S5 supply fixes: the LLM product check (appfit) and its use in s5_appstore, missing directory
data in s5_merge, and Capterra block pages."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import yaml

from nichefinder import appfit, http, keys, llm
from nichefinder.stages import s5_appstore, s5_capterra, s5_merge, s5_pricing_b2b, s8_gplay_filter
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path, side: str = "b2c") -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us"], "as_of": "2026-11-21"}), encoding="utf-8")
    base = {"who": "people", "task": "do things", "product": "app", "geo": "global", "tier": "A"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "budget", "name": "Budget apps", "side": side, **base},
        {"id": "crm", "name": "Tiny CRM", "side": "b2b-smb", **base},
    ]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "budget": {"en": [{"q": "budget app", "i": "category", "anchor": True}]},
        "crm": {"en": [{"q": "tiny crm", "i": "category", "anchor": True}]}}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": ["budget", "crm"]}), encoding="utf-8")
    return Workspace(tmp_path)


def fake_fit(calls):
    """Every listed app fits unless its name has "Game" in it; records each request's numbered lines."""
    def chat(ws, messages, **kw):
        lines = [x for x in messages[1]["content"].split("\n") if re.match(r"\d+: ", x)]
        calls.append(lines)
        return {"apps": [{"k": int(x.split(":")[0]), "fit": "no" if "Game" in x else "yes", "why": "w"} for x in lines]}, False, None
    return chat


def test_appfit_batches_and_numbers_each_batch_from_one(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    calls = []
    monkeypatch.setattr(llm, "chat_json", fake_fit(calls))
    apps = [{"app": f"Game {i}" if i % 2 else f"App {i}", "developer": "D", "genre": "G"} for i in range(130)]
    got = appfit.check(ws, {"id": "budget", "who": "people"}, apps)
    assert [len(c) for c in calls] == [60, 60, 10] and calls[1][0].startswith("1: ")
    assert got[0] == ("yes", "w") and got[1] == ("no", "w") and len(got) == 130
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"apps": [{"k": 1, "fit": "yes", "why": "ok"}]}, False, None))
    assert appfit.check(ws, {}, apps[:2]) == [("yes", "ok"), ("", "no answer from the model")]


def itunes(*apps):
    return {"results": [{"trackId": tid, "trackName": name, "sellerName": "S", "userRatingCount": n, "averageUserRating": 4.5,
                         "primaryGenreName": "Finance"} for tid, name, n in apps]}


def test_appstore_product_check_drops_non_products_and_include_wins(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    results = {"budget app": itunes((1, "Money", 900), (2, "Cookie Game", 90000), (3, "Coins", 300)),
               "tiny crm": itunes((4, "Leads", 50))}
    monkeypatch.setattr(s5_appstore, "search", lambda ws, q, country: results[q])
    monkeypatch.setattr(keys, "get", lambda name, *a, **k: "key" if name == "LLM_API_KEY" else None)
    calls = []
    monkeypatch.setattr(llm, "chat_json", fake_fit(calls))
    s5_appstore.run(ws, argparse.Namespace())
    rows = {r["track_id"]: r for r in csv.DictReader(open(ws.out("appstore_apps.csv"), encoding="utf-8"))}
    assert (rows["2"]["auto"], rows["2"]["fit"], rows["2"]["relevant"]) == ("1", "no", "0")   # top position, not a product
    assert (rows["1"]["relevant"], rows["3"]["relevant"]) == ("1", "1")
    assert calls[0][0].startswith("1: Cookie Game")   # candidates sorted by ratings
    assert "Dropped by the product check" in ws.out("appstore_review.md").read_text(encoding="utf-8")
    (tmp_path / "config" / "appstore_relevance.yaml").write_text(yaml.safe_dump({"budget": {"us": {"include": [2]}}}), encoding="utf-8")
    s5_appstore.run(ws, argparse.Namespace())
    rows = {r["track_id"]: r for r in csv.DictReader(open(ws.out("appstore_apps.csv"), encoding="utf-8"))}
    assert rows["2"]["relevant"] == "1"   # a manual include wins over the check
    # without a key the check is skipped and relevance is by position only
    monkeypatch.setattr(keys, "get", lambda name, *a, **k: None)
    (tmp_path / "config" / "appstore_relevance.yaml").unlink()
    s5_appstore.run(ws, argparse.Namespace())
    rows = {r["track_id"]: r for r in csv.DictReader(open(ws.out("appstore_apps.csv"), encoding="utf-8"))}
    assert (rows["2"]["fit"], rows["2"]["relevant"]) == ("", "1")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_merge_missing_directory_share_is_no_data_not_a_failed_gate(tmp_path):
    ws = make_ws(tmp_path, side="b2b-smb")
    # Capterra pages that did not parse: a row without a top-1 share, for both niches
    write_csv(ws.out("capterra_categories_stats.csv"), [
        {"niche_id": nid, "slug": "x-software", "products_total": "", "products_100plus": 0, "products_10plus": 0, "top1": "",
         "top1_share": "", "top3_share": "", "hhi": "", "generic_present": ""} for nid in ("budget", "crm")])
    write_csv(ws.out("appstore_metrics.csv"), [{"niche_id": "budget", "store": "us", "na": 0, "players_1k": 12, "players_10k": 3,
                                                "top1": "Money", "top1_share": 0.2, "top3_share": 0.4, "hhi": 0.1}])
    s5_merge.run(ws, argparse.Namespace())
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("supply_deep.csv"), encoding="utf-8"))}
    assert (rows["budget"]["supply_src"], rows["budget"]["gate_s5"]) == ("appstore", "PASS")   # falls back to the App Store
    assert (rows["crm"]["supply_src"], rows["crm"]["gate_s5"]) == ("na", "NA")                # no source: not FAIL:top1


BLOCK = "<!DOCTYPE html><html><head><title>Security Check</title></head><body>" + "x" * 40000 + "</body></html>"
REAL = '<html><script>{"numberOfItems":321}</script>' + "y" * 20000 + "</html>"


class Resp:
    def __init__(self, text):
        self.text = text


def test_capterra_block_pages_are_not_data_and_not_cached(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(s5_capterra.time, "sleep", lambda s: None)
    cached = ws.cache("capterra") / "x-software_p1.html"
    cached.write_text(BLOCK, encoding="utf-8")   # cached by an earlier version
    monkeypatch.setattr(http, "request", lambda *a, **k: Resp(BLOCK))
    assert s5_capterra.fetch(ws, "x-software", 1) == "" and not cached.exists()
    monkeypatch.setattr(http, "request", lambda *a, **k: Resp(REAL))
    assert s5_capterra.parse(s5_capterra.fetch(ws, "x-software", 1))[0] == 321 and cached.exists()


def score_inputs(tmp_path: Path, ws: Workspace, sides: dict, **supply) -> None:
    """score.yaml, metrics_quick.csv and supply_deep.csv for s6_score; `sides` maps niche id -> side."""
    (tmp_path / "config" / "score.yaml").write_text(yaml.safe_dump({
        "cpc_band": {"en": [0.5, 8.0], "en_b2b": [1.0, 1000.0]}, "cpc_below": 0.3, "cpc_above": 0.6,
        "trend_up": 0.05, "trend_down": -0.05}), encoding="utf-8")
    write_csv(ws.out("metrics_quick.csv"), [{"id": nid, "us_yoy": 0.1, "us_momentum": 1.0, "us_cagr_3y": 0.05} for nid in sides])
    base = {"tier": "A", "geo": "global", "demand_us": 1000, "demand_2023": 900, "gates_s3": "", "trend_kp": "FLAT",
            "trend_gt": "FLAT", "comp_idx": 50, "tinyseed": 0, "ph_12m": 1, "yc": 0, "topgross_us": 0, "cpc": 5, "hhi_brand": 0.3,
            "b2b_price_public": 0.5, "b2b_under100": 0.5, "b2c_with_monthly": 0, "b2c_n": 0, "expertise_flag": 0,
            "b2c_median_monthly": "", "b2b_median_monthly": 60, "gate_s5": "NA:proxy", "supply_src": "capterra",
            "supply_players": 3, "supply_top1": "Big", "supply_top1_share": 0.6, "supply_top3_share": 0.8, **supply}
    write_csv(ws.out("supply_deep.csv"), [{"niche_id": nid, **base, "side": side} for nid, side in sides.items()])


def test_s5_manual_flag_only_with_a_manual_estimate(tmp_path):
    from nichefinder.stages import s6_score
    ws = make_ws(tmp_path, side="b2b-smb")
    (tmp_path / "config" / "overrides.yaml").write_text(yaml.safe_dump({"budget": {"supply_manual": "ten players, no leader"}}),
                                                       encoding="utf-8")
    score_inputs(tmp_path, ws, {"budget": "b2b-smb", "crm": "b2b-smb"})
    s6_score.run(ws, argparse.Namespace())
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("score_final.csv"), encoding="utf-8"))}
    assert (rows["budget"]["gate_s5"], rows["budget"]["flags"], rows["budget"]["gates_failed"]) == ("PASS*", "S5:manual", "")
    assert (rows["crm"]["gate_s5"], rows["crm"]["gates_failed"], rows["crm"]["verdict"]) == ("NA", "S5:unmeasured", "red")
    assert "S5:manual" not in rows["crm"]["flags"]   # no manual estimate: the flag would read "manual estimate" in passports
    assert rows["budget"]["s_frag"] == rows["crm"]["s_frag"]   # both get the neutral half-credit for players / top-3



def test_second_platform_rule_only_for_consumer_niches(tmp_path):
    from nichefinder.stages import s6_score
    ws = make_ws(tmp_path)
    score_inputs(tmp_path, ws, {"budget": "b2c", "crm": "b2b-smb"}, gate_s5="FAIL:top1", supply_src="appstore")
    # Google Play US: leader at 30 %, 10 apps above 100k installs, for both niches
    write_csv(ws.out("offsearch.csv"), [{"niche_id": nid, "gp_us_top1_share": 0.3, "gp_us_players_100k": 10} for nid in ("budget", "crm")])
    s6_score.run(ws, argparse.Namespace())
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("score_final.csv"), encoding="utf-8"))}
    assert (rows["budget"]["gate_s5"], rows["budget"]["flags"], rows["budget"]["gates_failed"]) == ("PASS:android", "S5:android", "")
    assert (rows["crm"]["gate_s5"], rows["crm"]["gates_failed"], rows["crm"]["verdict"]) == ("FAIL:top1", "S5:top1", "red")


def test_gplay_filter_product_check_frees_places_and_keep_wins(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (tmp_path / "config" / "deal_keywords.yaml").write_text(yaml.safe_dump({"budget": "budget|money"}), encoding="utf-8")
    (tmp_path / "config" / "coverage_keywords.yaml").write_text(yaml.safe_dump({}), encoding="utf-8")
    monkeypatch.setattr(s8_gplay_filter, "MAX_APPS", 2)
    search = [{"niche_id": "budget", "country": "us", "query": "budget app", "pos": pos, "appId": aid, "title": title, "developer": "D",
               "score": 4.5, "priceText": "", "free": "true", "summary": summary}
              for pos, aid, title, summary in [(1, "g.cookie", "Money Game", "idle budget tycoon"), (2, "a.one", "Budget One", "track money"),
                                               (3, "a.two", "Budget Two", "plan money"), (4, "x.off", "Weather", "rain radar")]]
    write_csv(ws.out("gplay_search.csv"), search)
    monkeypatch.setattr(keys, "get", lambda name, *a, **k: "key" if name == "LLM_API_KEY" else None)
    calls = []
    monkeypatch.setattr(llm, "chat_json", fake_fit(calls))
    s8_gplay_filter.run(ws, argparse.Namespace())
    match = [r["appId"] for r in csv.DictReader(open(ws.out("gplay_match.csv"), encoding="utf-8"))]
    assert match == ["a.one", "a.two"]   # the game left, so the second real product got its place
    assert calls[0][0] == "1: Money Game | D | - | idle budget tycoon" and len(calls[0]) == 3   # the off-topic app is not a candidate
    fit = {r["appId"]: r for r in csv.DictReader(open(ws.out("gplay_fit.csv"), encoding="utf-8"))}
    assert (fit["g.cookie"]["fit"], fit["g.cookie"]["by"]) == ("no", "llm")
    (tmp_path / "config" / "gplay_keep.yaml").write_text(yaml.safe_dump({"budget": ["g.cookie"]}), encoding="utf-8")
    s8_gplay_filter.run(ws, argparse.Namespace())
    match = [r["appId"] for r in csv.DictReader(open(ws.out("gplay_match.csv"), encoding="utf-8"))]
    assert match == ["g.cookie", "a.one"]   # a manual keep wins over the check
    monkeypatch.setattr(keys, "get", lambda name, *a, **k: None)
    (tmp_path / "config" / "gplay_keep.yaml").unlink()
    s8_gplay_filter.run(ws, argparse.Namespace())
    match = [r["appId"] for r in csv.DictReader(open(ws.out("gplay_match.csv"), encoding="utf-8"))]
    assert match == ["g.cookie", "a.one"]   # without a key: regex and position only


def test_getapp_block_page_stops_b2b_pricing_without_output(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, side="b2b-smb")
    (tmp_path / "config" / "capterra_map.yaml").write_text(yaml.safe_dump({"crm": {"slugs": ["crm-software"]}}), encoding="utf-8")
    (tmp_path / "config" / "getapp_categories.yaml").write_text(yaml.safe_dump({"crm": "customer-management-software"}), encoding="utf-8")
    write_csv(ws.out("capterra_products.csv"), [{"slug": "crm-software", "product": "Leads", "reviews": 500, "generic": "0"}])
    calls = []
    monkeypatch.setattr(s5_pricing_b2b.time, "sleep", lambda s: None)
    monkeypatch.setattr(http, "request", lambda *a, **k: calls.append(a[0]) or Resp(BLOCK))
    s5_pricing_b2b.run(ws, argparse.Namespace(agg=False))
    assert len(calls) == 1   # no retries: the first block page stops the stage
    assert not ws.out("pricing_b2b.csv").exists() and not ws.out("pricing_b2b_niche.csv").exists()
    assert not any(ws.cache("getapp").iterdir())
