"""Offline tests for the VK client (sources/vk.py) and s8_vk_audience: token in the body only, month cache, expired
user token, the LLM community check with keep / drop, metrics and the passport block (fake API and model)."""
from __future__ import annotations

import argparse
import csv
import urllib.parse
from pathlib import Path

import pytest
import yaml

from nichefinder import evidence, keys, llm
from nichefinder.sources import vk
from nichefinder.stages import s8_vk_audience as stage
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": "2026-11-23"}), encoding="utf-8")
    base = {"who": "families", "task": "plan a budget", "product": "budget app", "side": "b2c", "tier": "A"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "budget", "name": "Budget apps", "geo": "both", **base},
        {"id": "usonly", "name": "US only", "geo": "global", **base},
    ]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "budget": {"ru": [{"q": "budget ru", "i": "category", "anchor": True}], "en": [{"q": "budget app", "i": "category", "anchor": True}]},
        "usonly": {"en": [{"q": "us thing", "i": "category", "anchor": True}]}}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": ["budget", "usonly"]}), encoding="utf-8")
    (tmp_path / "config" / "vk_audience.yaml").write_text(yaml.safe_dump(
        {"phrases_llm": 2, "niches": {"budget": {"phrases": ["family money"], "drop": ["bigblog"]}}}), encoding="utf-8")
    return Workspace(tmp_path)


GROUPS = {1: ("Family budget club", "bigclub", 250_000), 2: ("Money blog", "bigblog", 90_000), 3: ("Shop of wallets", "walletshop", 40_000),
          4: ("Tiny budget", "tiny", 300), 5: ("Savings people", "savers", 12_000)}


class FakeVK:
    def __init__(self, expired=False):
        self.calls, self.expired = [], expired

    def __call__(self, method, body):
        p = dict(urllib.parse.parse_qsl(body))
        self.calls.append((method, p))
        if self.expired:
            return {"error": {"error_code": 5, "error_msg": "User authorization failed"}}
        if method == "groups.search":
            assert p["access_token"] == "user-tok"
            items = [{"id": i, "name": GROUPS[i][0], "screen_name": GROUPS[i][1], "type": "page", "is_closed": 0} for i in GROUPS]
            items.append({"id": 9, "name": "Budget meetup", "screen_name": "meetup", "type": "event", "is_closed": 0})
            return {"response": {"count": len(items), "items": items}}
        assert p["access_token"] == "svc-tok"
        ids = [int(x) for x in p["group_ids"].split(",")]
        return {"response": {"groups": [{"id": i, "name": GROUPS[i][0], "screen_name": GROUPS[i][1], "members_count": GROUPS[i][2],
                                         "activity": "Finance", "description": "d"} for i in ids if i in GROUPS]}}


def fake_llm(ws, messages, **kw):
    system, user = messages[0]["content"], messages[1]["content"]
    if system == stage.PHRASE_SYSTEM:
        return {"phrases": ["family money", "budget"]}, False, None
    lines = [x for x in user.split("\n") if x[:1].isdigit()]
    return {"items": [{"k": int(x.split(":")[0]), "fit": "no" if "Shop" in x else "yes", "why": "w"} for x in lines]}, False, None


@pytest.fixture
def env(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("VK_SERVICE_TOKEN", "svc-tok")
    monkeypatch.setenv("VK_USER_TOKEN", "user-tok")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(vk, "PACE", 0)
    monkeypatch.setattr(llm, "chat_json", fake_llm)
    return ws


def test_audience_checks_communities_and_sums_the_largest(env, monkeypatch):
    fake = FakeVK()
    monkeypatch.setattr(vk, "_post", fake)
    stage.run(env, argparse.Namespace(niches=""))
    rows = {r["niche_id"]: r for r in csv.DictReader(open(env.out("vk_audience.csv"), encoding="utf-8"))}
    assert set(rows) == {"budget"}   # geo global is not a Russian niche
    b = rows["budget"]
    # kept: the club (250k) and the savers (12k); the shop fails the check, the blog is dropped by hand, tiny is too small
    assert (b["communities"], b["members_top10"], b["top1_members"], b["n_100k"], b["n_10k"]) == ("2", "262000", "250000", "1", "2")
    groups = {r["screen_name"]: r for r in csv.DictReader(open(env.out("vk_groups.csv"), encoding="utf-8"))}
    assert (groups["bigblog"]["fit"], groups["bigblog"]["by"]) == ("no", "config") and groups["walletshop"]["fit"] == "no"
    assert "tiny" not in groups and "meetup" not in groups
    assert [m for m, _ in fake.calls].count("groups.search") == 2   # the hand phrase and the LLM phrase "budget"; repeats once
    # a re-run in the same month is served from the cache: no calls, and no token in any cache file name or body
    n = len(fake.calls)
    stage.run(env, argparse.Namespace(niches=""))
    assert len(fake.calls) == n
    for f in env.cache("vk").iterdir():
        assert "tok" not in f.name and "svc-tok" not in f.read_text(encoding="utf-8")
    lines = evidence.Evidence(env).vk_lines("budget")
    assert lines[0].startswith("## Audience in VK") and "262,000 members" in lines[2]
    assert "vk:262k" in evidence.Evidence(env).tags("budget")


def test_expired_user_token_says_how_to_renew(env, monkeypatch):
    monkeypatch.setattr(vk, "_post", FakeVK(expired=True))
    with pytest.raises(keys.MissingKey) as e:
        stage.run(env, argparse.Namespace(niches=""))
    assert "VK_USER_TOKEN" in str(e.value) and "oauth.vk.com/authorize" in str(e.value) and "expired" in str(e.value)
