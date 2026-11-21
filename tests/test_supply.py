"""Offline tests for the S5 supply fixes: the LLM product check (appfit) and its use in s5_appstore, missing directory
data in s5_merge, and Capterra block pages."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import yaml

from nichefinder import appfit, http, keys, llm
from nichefinder.stages import s5_appstore, s5_capterra, s5_merge
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
