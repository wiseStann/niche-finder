"""Offline tests for the Yandex Direct forecast client (sources/direct.py) and s8_direct_forecast: the report cycle,
click-weighted prices, phrase selection, whole niches per report, the month cache without the token, and the access
errors (fake API)."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pytest
import yaml

from nichefinder import evidence, tools
from nichefinder.sources import direct
from nichefinder.stages import s8_direct_forecast as stage
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": "2026-11-23"}), encoding="utf-8")
    base = {"who": "shops", "task": "t", "product": "p", "side": "b2b-smb", "tier": "A"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "garage", "name": "Garage CRM", "geo": "both", **base},
        {"id": "salon", "name": "Salon CRM", "geo": "ru", **base},
        {"id": "usonly", "name": "US only", "geo": "global", **base},
    ]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "garage": {"ru": [{"q": "crm garage", "i": "category", "anchor": True}, {"q": "garage program", "i": "category"},
                          {"q": "how to run a garage", "i": "problem"}, {"q": "brandx", "i": "brand", "b": "BrandX"},
                          {"q": "a b c d e f g h", "i": "category"}, {"q": "garage (crm)", "i": "category"}],
                   "en": [{"q": "garage crm", "i": "category", "anchor": True}]},
        "salon": {"ru": [{"q": "salon booking", "i": "category", "anchor": True}]},
        "usonly": {"en": [{"q": "us thing", "i": "category", "anchor": True}]}}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": ["garage", "salon", "usonly"]}), encoding="utf-8")
    (tmp_path / "config" / "direct_forecast.yaml").write_text(yaml.safe_dump({"poll_s": 0}), encoding="utf-8")
    return Workspace(tmp_path)


PRICES = {"crm garage": (1000, 40, 10, 120.0, 300.0), "garage program": (500, 20, 5, 80.0, 200.0),
          "how to run a garage": (2000, 30, 0, 50.0, 0.0), "salon booking": (3000, 90, 30, 60.0, 150.0)}


class FakeDirect:
    def __init__(self, error: int = 0):
        self.calls, self.error, self.pending = [], error, 1

    def __call__(self, body):
        env = json.loads(body)
        assert env["token"] == "tok" and env["locale"] == "en"
        m = env["method"]
        self.calls.append((m, env.get("param")))
        if self.error:
            return {"error_code": self.error, "error_str": "x", "error_detail": "y"}
        if m == "CreateNewForecast":
            assert env["param"]["Currency"] == "RUB" and env["param"]["GeoID"] == [225]
            self.last = env["param"]["Phrases"]
            return {"data": 77}
        if m == "GetForecastList":
            self.pending -= 1
            return {"data": [{"ForecastID": 77, "StatusForecast": "Pending" if self.pending >= 0 else "Done"}]}
        if m == "GetForecast":
            rows = [{"Phrase": p, "Shows": PRICES[p][0], "Clicks": PRICES[p][1], "PremiumClicks": PRICES[p][2], "Min": PRICES[p][3],
                     "PremiumMin": PRICES[p][4], "Currency": "RUB"} for p in self.last]
            return {"data": {"Phrases": rows, "Common": {"Shows": 1}}}
        if m == "DeleteForecastReport":
            return {"data": 1}
        raise AssertionError(m)


@pytest.fixture
def env(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "tok")
    monkeypatch.setattr(direct, "WAIT", 0)
    return ws


def test_phrases_and_whole_niche_batches():
    rows = [{"q": "x a", "intent": "category", "anchor": 0}, {"q": "anchor", "intent": "category", "anchor": 1},
            {"q": "b", "intent": "brand", "anchor": 0}, {"q": "1 2 3 4 5 6 7 8", "intent": "problem", "anchor": 0},
            {"q": "bad (x)", "intent": "problem", "anchor": 0}, {"q": "X  A", "intent": "problem", "anchor": 0}]
    got = stage.niche_phrases(rows, ["category", "problem"], 7)
    assert [p["q"] for p in got] == ["anchor", "x a"]   # anchor first; brand, too long, bad characters and repeats out
    plan = [("a", [{}] * 60), ("b", [{}] * 50), ("c", [{}] * 30)]
    assert [[n for n, _ in g] for g in stage.batches(plan)] == [["a"], ["b", "c"]]   # a niche is never split


def test_forecast_cycle_weighted_prices_cache_and_evidence(env, monkeypatch):
    fake = FakeDirect()
    monkeypatch.setattr(direct, "_post", fake)
    stage.run(env, argparse.Namespace(niches=""))
    assert [m for m, _ in fake.calls] == ["CreateNewForecast", "GetForecastList", "GetForecastList", "GetForecast", "DeleteForecastReport"]
    assert fake.last == ["crm garage", "garage program", "how to run a garage", "salon booking"]   # both niches in one report
    rows = {r["niche_id"]: r for r in csv.DictReader(open(env.out("direct_niche.csv"), encoding="utf-8"))}
    assert set(rows) == {"garage", "salon"}
    g = rows["garage"]
    # guarantee: (40*120 + 20*80 + 30*50) / 90 = 87.78; premium: (10*300 + 5*200) / 15 = 266.67; budget 4000
    assert (g["cpc_guarantee"], g["cpc_premium"], g["budget_premium"], g["anchor_cpc_premium"]) == ("87.78", "266.67", "4000", "300.0")
    n = len(fake.calls)
    stage.run(env, argparse.Namespace(niches=""))
    assert len(fake.calls) == n   # the month cache answers
    assert all("tok" not in f.read_text(encoding="utf-8") for f in env.cache("direct").iterdir())
    lines = evidence.Evidence(env).direct_lines("garage")
    assert lines[0] == "## Yandex Direct forecast (S8, evidence)" and "267 RUB in the premium block" in lines[2]


def test_access_errors(env, monkeypatch):
    monkeypatch.setattr(direct, "_post", FakeDirect(error=58))
    with pytest.raises(tools.ToolMissing) as e:   # a skip with the hint, not a "missing key"
        stage.run(env, argparse.Namespace(niches=""))
    assert "not approved yet" in str(e.value)
    monkeypatch.setattr(direct, "_post", FakeDirect(error=31))
    with pytest.raises(direct.DirectError) as e:
        stage.run(env, argparse.Namespace(niches=""))
    assert e.value.code == 31 and "five forecast reports" in str(e.value)
