"""Offline tests for the Telegram chats voice (S10): the cached gateway, chat search with the LLM check, message
search, the FloodWait stop, labels and the report (fake Telegram and fake model; telethon is not needed)."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import yaml

from nichefinder import evidence, llm, telegram
from nichefinder.stages import s10_tg_classify as classify
from nichefinder.stages import s10_tg_fetch as fetch
from nichefinder.stages import s10_tg_report as report
from nichefinder.workspace import Workspace

EXAMPLE_CFG = Path(fetch.__file__).resolve().parents[1] / "examples" / "default" / "config" / "tg_voice.yaml"


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": "2026-11-23"}), encoding="utf-8")
    base = {"who": "salon owners", "task": "book clients", "product": "booking app", "tier": "A"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "salons", "name": "Salon booking", "geo": "both", "side": "b2b-smb", **base},
        {"id": "garages", "name": "Garage CRM", "geo": "ru", "side": "b2b-smb", **base},
        {"id": "usonly", "name": "US only", "geo": "global", "side": "b2c", **base},
    ]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "salons": {"ru": [{"q": "программа для салона", "i": "category", "anchor": True}, {"q": "юклаентс", "i": "brand", "b": "YCLIENTS"}],
                   "en": [{"q": "salon booking app", "i": "category", "anchor": True}]},
        "garages": {"ru": [{"q": "crm для автосервиса", "i": "category", "anchor": True}]},
        "usonly": {"en": [{"q": "us thing", "i": "category", "anchor": True}]},
    }, allow_unicode=True), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": ["salons", "garages", "usonly"]}), encoding="utf-8")
    cfg = yaml.safe_load(EXAMPLE_CFG.read_text(encoding="utf-8"))
    cfg["fetch"].update({"terms": ["crm", "app"], "pace_s": 0})
    cfg["niches"] = {"garages": {"phrases": ["garage owners"], "keep": ["@garage_club"]}}
    (tmp_path / "config" / "tg_voice.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return Workspace(tmp_path)


CHATS = {
    "salon owners chat": [
        {"id": 1, "username": "owners_big", "title": "Salon owners chat", "members": 20000, "megagroup": 1, "broadcast": 0},
        {"id": 2, "username": "news_channel", "title": "Salon news", "members": 50000, "megagroup": 0, "broadcast": 1},   # a channel
        {"id": 3, "username": "tiny", "title": "Salon owners tiny", "members": 50, "megagroup": 1, "broadcast": 0},         # too small
        {"id": 4, "username": "clients_chat", "title": "Salon clients deals", "members": 9000, "megagroup": 1, "broadcast": 0},
        {"id": 5, "username": "owners_small", "title": "Salon owners club", "members": 800, "megagroup": 1, "broadcast": 0},
        {"id": 6, "username": "lux_salon", "title": "Salon owners Lux", "members": 1500, "megagroup": 1, "broadcast": 0},   # a customer chat
    ],
    "garage owners": [{"id": 9, "username": "garage_club", "title": "Garage owners clients", "members": 400, "megagroup": 1, "broadcast": 0}],
}


class FakeGateway:
    def __init__(self, flood_on: str = ""):
        self.calls, self.flood_on, self.live, self.offline = [], flood_on, 0, False

    def search_chats(self, q, limit=50):
        self.calls.append(("chats", q))
        return CHATS.get(q, [])

    def chat_about(self, username):
        self.calls.append(("about", username))
        return {"about": "chat for the customers of our salon" if username == "lux_salon" else "owners share experience", "members": 1}

    def search_messages(self, username, term, since, limit=100):
        self.calls.append(("msgs", username, term, since))
        if username == self.flood_on:
            raise telegram.FloodStop("wait 9999 s")
        if username == "owners_small":
            raise telegram.ChatUnavailable("ChannelPrivateError")
        same = {"id": 100, "date": "2026-10-01", "text": "Which CRM do you use? We left YCLIENTS over the price", "reply": 0, "fwd": 0}
        own = {"crm": 201, "app": 202}.get(term, 203)
        return [same, {"id": own, "date": "2026-09-01", "text": f"{term}: the app has no Avito sync", "reply": 1, "fwd": 0}]

    def close(self):
        pass


def fake_llm(calls):
    def chat(ws, messages, **kw):
        system, user = messages[0]["content"], messages[1]["content"]
        calls.append(system[:20])
        if system == fetch.PHRASE_SYSTEM:
            return ({"phrases": ["salon owners chat"]} if "Salon booking" in user else {"phrases": []}), False, None
        if system == fetch.CHECK_SYSTEM:
            lines = [x for x in user.split("\n") if x[:1].isdigit()]
            return {"chats": [{"k": int(x.split(":")[0]), "fit": "no" if "clients" in x or "customers" in x else "yes", "why": "w"}
                              for x in lines]}, False, None
        if system == classify.SYSTEM:
            n = user.count("### item")
            labels = [{"i": i, "about": ["niche", "ad", "niche"][i % 3], "kind": ["price", "other", "product_request"][i % 3],
                       "pain": "too expensive", "products": ["YCLIENTS"]} for i in range(n)]
            return {"items": labels}, False, {"prompt_tokens": 10, "completion_tokens": 5}
        return {"themes": [{"theme": "Price of booking apps", "kind": "unmet", "description": "d", "ids": [0], "quotes": ["q"]}]}, False, None
    return chat


def test_gateway_caches_per_month_and_stops_offline(tmp_path):
    ws = make_ws(tmp_path)
    gw = telegram.Gateway(ws, pace=0)
    gw._connect = lambda: object()
    got = gw._cached("chats|x", lambda client: [{"id": 1}])
    assert got == [{"id": 1}] and gw.live == 1
    assert gw._cached("chats|x", lambda client: 1 / 0) == [{"id": 1}] and gw.live == 1   # a cache hit makes no call
    gw.offline = True
    try:
        gw._cached("chats|y", lambda client: [])
        raise AssertionError("expected FloodStop")
    except telegram.FloodStop:
        pass
    assert gw._cached("chats|x", lambda client: 1 / 0) == [{"id": 1}]   # cache hits still work offline


def test_problem_names_the_missing_piece(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(telegram.importlib.util, "find_spec", lambda name: object())
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)
    assert "TG_API_ID" in telegram.problem(ws)
    monkeypatch.setenv("TG_API_ID", "1")
    monkeypatch.setenv("TG_API_HASH", "h")
    assert "nf setup telegram" in telegram.problem(ws)
    telegram.session_base(ws).parent.mkdir(parents=True)
    telegram.session_base(ws).with_suffix(".session").write_bytes(b"")
    assert telegram.problem(ws) is None


def test_fetch_finds_groups_checks_chats_and_reads_messages(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "k")
    gw = FakeGateway()
    monkeypatch.setattr(fetch, "make_gateway", lambda ws, cfg: gw)
    calls = []
    monkeypatch.setattr(llm, "chat_json", fake_llm(calls))
    fetch.run(ws, argparse.Namespace(niches=""))
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out(fetch.FETCH), encoding="utf-8"))}
    assert set(rows) == {"salons", "garages"}   # geo global is not a Russian niche
    chats = {r["username"]: r for r in csv.DictReader(open(ws.out(fetch.CHATS), encoding="utf-8"))}
    assert "news_channel" not in chats and "tiny" not in chats                 # a channel; too few members
    assert (chats["clients_chat"]["fit"], chats["clients_chat"]["picked"]) == ("no", "0")
    assert chats["owners_big"]["picked"] == "1" and chats["owners_small"]["status"].startswith("unavailable")
    assert (chats["garage_club"]["fit"], chats["garage_club"]["by"]) == ("yes", "config")   # keep wins over the check
    assert (chats["lux_salon"]["confirm"], chats["lux_salon"]["fit"], chats["lux_salon"]["picked"]) == ("no", "no", "0")   # description
    assert chats["owners_big"]["confirm"] == "yes" and ("about", "garage_club") not in gw.calls   # a hand keep needs no confirm
    docs = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8")]
    big = [d for d in docs if d["username"] == "owners_big"]
    assert len(big) == 4   # terms crm, app, YCLIENTS (the brand); the message shared by all terms is kept once
    assert {d["term"] for d in big} == {"crm", "app", "YCLIENTS"}
    assert not {"author", "from_id", "sender", "user_id"} & set(docs[0])
    assert ("msgs", "owners_big", "YCLIENTS", "2024-11-01") in gw.calls        # window: 24 months from the run month
    assert rows["salons"]["status"] == "ok" and rows["garages"]["phrases"] == "garage owners"


def test_fetch_flood_stop_keeps_earlier_rows(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "chat_json", fake_llm([]))
    monkeypatch.setattr(fetch, "make_gateway", lambda ws, cfg: FakeGateway())
    fetch.run(ws, argparse.Namespace(niches=""))
    before = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8") if '"salons"' in x]
    gw = FakeGateway(flood_on="owners_big")
    monkeypatch.setattr(fetch, "make_gateway", lambda ws, cfg: gw)
    fetch.run(ws, argparse.Namespace(niches=""))
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out(fetch.FETCH), encoding="utf-8"))}
    assert rows["salons"]["status"] == "ok" and gw.offline   # the earlier row survives, live calls stopped
    after = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8") if '"salons"' in x]
    assert after == before


def test_classify_and_report_write_shares_verdicts_and_passport_lines(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "chat_json", fake_llm([]))
    monkeypatch.setattr(fetch, "make_gateway", lambda ws, cfg: FakeGateway())
    fetch.run(ws, argparse.Namespace(niches=""))
    classify.run(ws, argparse.Namespace(niches="", dry=False, workers=1))
    lr = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("tg_llm.csv"), encoding="utf-8"))}
    s = lr["salons"]
    assert int(s["about_ad"]) >= 1 and float(s["price_share"]) > 0 and s["niche_chats"] == "1"
    report.run(ws, argparse.Namespace(workers=1))
    v = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("tg_voice.csv"), encoding="utf-8"))}
    assert v["salons"]["verdict"] == "⚪ quiet" and "messages about the niche in 1 chats" in v["salons"]["reason"]
    text = ws.report("S10-telegram.md").read_text(encoding="utf-8")
    assert "DRAFT" in text and "t.me/owners_big" in text and "Price of booking apps" in text
    lines = evidence.Evidence(ws).tg_lines("salons")
    assert lines[0] == "## Buyer voice (Telegram chats, S10)" and "quiet" in lines[2]
