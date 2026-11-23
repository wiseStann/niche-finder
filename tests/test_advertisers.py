"""Offline tests for s5_advertisers (Google Ads Transparency through DataForSEO)."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import yaml

from nichefinder.sources import dataforseo as dfs
from nichefinder.stages import s5_advertisers as adv
from nichefinder.workspace import Workspace

TODAY = dt.date(2026, 11, 23)


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us"], "as_of": TODAY.isoformat()}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": [{"id": "salons"}, {"id": "gyms"}]}), encoding="utf-8")
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": n, "who": "w", "task": "t", "product": "p", "geo": "global", "side": "b2b-smb", "tier": "A"} for n in ("salons", "gyms")]),
        encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "salons": {"en": [{"q": "vagaro", "i": "brand", "b": "Vagaro"}, {"q": "booksy", "i": "brand", "b": "Booksy"}]},
        "gyms": {"en": [{"q": "mindbody", "i": "brand", "b": "Mindbody"}, {"q": "glofox", "i": "brand", "b": "Glofox"}]}}),
        encoding="utf-8")
    ws = Workspace(tmp_path)
    with open(ws.out("serp_items.csv"), "w", newline="", encoding="utf-8") as f:
        f.write("niche_id,query,rank,domain,group,title,url\nsalons,q,1,www.vagaro.com,brand,t,u\nsalons,q,2,reddit.com,ugc,t,u\n")
    with open(ws.out("wayback_domains.csv"), "w", newline="", encoding="utf-8") as f:
        f.write("niche_id,rank,app,domain\nsalons,2,Booksy,booksy.com\nsalons,1,Vagaro,vagaro.com\nsalons,3,X,linktr.ee\n"
                "salons,4,eBay,ebay.com\ngyms,1,Mindbody,mindbody.io\ngyms,2,Glofox,glofox.com\n")
    return ws


def ad(first: str, last: str, fmt: str = "text", title: str = "Vagaro Inc") -> dict:
    return {"first_shown": f"{first} 10:00:00 +00:00", "last_shown": f"{last} 10:00:00 +00:00", "format": fmt, "title": title}


def test_competitor_domains_order_and_skip(tmp_path):
    doms = adv.competitor_domains(make_ws(tmp_path), ["salons", "gyms"], 5)
    assert doms["salons"] == [("vagaro.com", "serp"), ("booksy.com", "app")]       # brand domain first; linktr.ee and ebay.com out
    assert [d for d, _ in doms["gyms"]] == ["mindbody.io", "glofox.com"]


def test_domain_stats_running_and_long_runners():
    res = {"se_results_count": 300, "items": [ad("2026-06-01", "2026-11-22"), ad("2026-11-01", "2026-11-20", "video"),
                                              ad("2025-01-01", "2025-06-01")]}
    st = adv.domain_stats(res, TODAY, 30, 90)
    assert st["ads_total"] == 300 and st["ads_seen"] == 3 and st["active"] == 2
    assert st["longest_active_days"] == 174 and st["long_runners"] == 1 and st["text_share"] == 0.5
    assert adv.domain_stats({"items": []}, TODAY, 30, 90)["active"] == 0


def test_end_to_end_with_posting_polling_and_flags(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    posted, polls = [], {"n": 0}
    results = {"vagaro.com": [ad("2026-05-01", "2026-11-22")], "booksy.com": [ad("2026-07-01", "2026-11-21")],
               "mindbody.io": [], "glofox.com": []}

    def fake_request(method, path, body=None):
        assert path.endswith("task_post")
        posted.extend(t["target"] for t in body)
        return {"tasks": [{"id": f"id-{t['target']}", "status_code": 20100, "data": {"tag": t["target"]}} for t in body]}

    def fake_raw(method, path, body=None):
        polls["n"] += 1
        d = path.rsplit("id-", 1)[1]
        if polls["n"] <= 1:
            return {"tasks": [{"status_code": 40602, "status_message": "Task In Queue."}]}
        if not results[d]:
            return {"tasks": [{"status_code": 40102, "status_message": "No Search Results."}]}
        return {"tasks": [{"status_code": 20000, "result": [{"se_results_count": 12, "items": results[d]}]}]}

    monkeypatch.setattr(dfs, "_request", fake_request)
    monkeypatch.setattr(dfs, "_raw_request", fake_raw)
    monkeypatch.setattr(dfs, "balance", lambda: 10.0)
    monkeypatch.setattr(adv.time, "sleep", lambda s: None)
    adv.run(ws, argparse.Namespace(per_niche=5, active_days=30, long_days=90, wait=60, niches=None, dry=False))
    assert sorted(posted) == ["booksy.com", "glofox.com", "mindbody.io", "vagaro.com"]
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("advertisers.csv"), encoding="utf-8"))}
    assert rows["salons"]["advertisers_now"] == "2" and rows["salons"]["long_runner_advertisers"] == "2"
    assert rows["salons"]["flags"] == "A:ads-pay" and rows["gyms"]["advertisers_now"] == "0"
    assert not json.loads(adv._pending_path(ws).read_text(encoding="utf-8"))
    posted.clear()
    adv.run(ws, argparse.Namespace(per_niche=5, active_days=30, long_days=90, wait=60, niches=None, dry=False))
    assert posted == []                                                              # every domain cached: nothing paid


def test_account_refusal_stops_and_keeps_pending(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(dfs, "_request", lambda m, p, b=None: {"tasks": [{"id": f"id-{t['target']}", "status_code": 20100,
                                                                          "data": {"tag": t["target"]}} for t in b]})
    monkeypatch.setattr(dfs, "_raw_request", lambda *a, **k: {"tasks": [{"status_code": 40201, "status_message": "paused"}]})
    monkeypatch.setattr(dfs, "balance", lambda: 10.0)
    monkeypatch.setattr(adv.time, "sleep", lambda s: None)
    try:
        adv.run(ws, argparse.Namespace(per_niche=5, active_days=30, long_days=90, wait=60, niches=["salons"], dry=False))
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "40201" in str(e)
    assert len(json.loads(adv._pending_path(ws).read_text(encoding="utf-8"))) == 2  # collected by the next run, not re-paid
