"""Offline tests for s8_freelance: Kwork stateData and FL.ru list parsing, dates and budgets, the history merge across
runs, keyword candidates with config overrides, LLM labels (fake model) and the no-LLM path."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import pytest
import yaml

from nichefinder import http, llm
from nichefinder.stages import s8_freelance as fr
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path, as_of: str = "2026-11-21") -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": as_of}), encoding="utf-8")
    base = {"side": "b2c", "tier": "A", "geo": "both"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "recipes", "who": "home cooks", "task": "save recipes", "product": "recipe app", **base},
        {"id": "cards", "who": "professionals", "task": "share contacts", "product": "digital business card", **base},
        {"id": "repair", "who": "car repair shops", "task": "work orders", "product": "SaaS", **base},
    ]), encoding="utf-8")
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": [{"id": "recipes"}, {"id": "cards"}, {"id": "repair"}]}),
                                        encoding="utf-8")
    (cfg / "coverage_keywords.yaml").write_text(yaml.safe_dump({
        "recipes": ["рецепт"], "cards": ["визитк"], "repair": ["автосервис", "сто"]}, allow_unicode=True), encoding="utf-8")
    (cfg / "freelance.yaml").write_text(yaml.safe_dump({
        "sleep": 0, "match": {"repair": "автосервис|(?<![а-яё])сто(?![а-яё])"}}, allow_unicode=True), encoding="utf-8")
    return Workspace(tmp_path)


def kwork_page(wants: list[dict]) -> str:
    state = {"categories": {"11": {"name": "Разработка и IT", "cats": [{"CATID": "41", "name": "Мобильные приложения"}]}},
             "wantsListData": {"wants": wants, "pagination": {"total": len(wants)}},
             "exchangeStats": {"projects": 4940, "orders": 2671, "value": 51689500, "period": 30}}
    return "<html><script>window.stateData=" + json.dumps(state, ensure_ascii=False) + ";window.x=1;</script></html>"


def want(i, name, desc="", price="5000.00", offers=7):
    return {"id": i, "name": name, "description": desc, "priceLimit": price, "possiblePriceLimit": float(price) * 3,
            "kwork_count": offers, "views_dirty": "100", "date_create": "2026-11-20 08:43:19", "category_id": "41",
            "user": {"data": {"wants_count": "3", "wants_hired_percent": "50"}}}


def fl_item(pid, title, desc, price, kind="Заказ", when="18 ноября, 14:25", answers="5 ответов"):
    return (f'<div class="b-post" id="project-item{pid}"><h2 class="b-post__title"><a id="prj_name_{pid}" '
            f'href="/projects/{pid}/slug.html">{title}</a></h2>'
            f'<div class="d-flex b-post__price p-0"><span class="text-4">{price}</span></div>'
            f'<div class="b-post__txt text-5 ">{desc}</div>'
            f'<span class="b-post__bold b-layout__txt_inline-block text-7 text-dark mr-4">{kind}</span>'
            f'<span class="text-gray-opacity-4 text-7 mr-16">{when}</span><span>{answers}</span></div>')


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8")))


def args(**kw) -> argparse.Namespace:
    return argparse.Namespace(**{"no_llm": False, "source": "all", "fl_pages": None, "offline": False, **kw})


def test_kwork_state_and_posts():
    st = fr.state_data(kwork_page([want(1, "Сделать &mdash; приложение рецептов", "Нужно приложение")]))
    cats = fr.kwork_subcategories(st)
    assert cats == {"41": "Разработка и IT / Мобильные приложения"}
    (p,) = fr.kwork_posts(st, cats)
    assert p["title"] == "Сделать — приложение рецептов" and p["budget"] == 5000 and p["budget_max"] == 15000
    assert p["url"] == "https://kwork.ru/projects/1/view" and p["offers"] == 7 and p["buyer_hired_pct"] == "50"
    assert fr.state_data("<html>no state</html>") is None


def test_fl_dates_and_prices():
    today = dt.date(2026, 11, 21)
    assert fr.parse_fl_date("3 часа 42 минуты назад", today) == "2026-11-21"
    assert fr.parse_fl_date("вчера, 14:25", today) == "2026-11-20"
    assert fr.parse_fl_date("18 ноября, 14:25", today) == "2026-11-18"
    assert fr.parse_fl_date("2 мая, 10:00", today) == "2026-05-02"
    assert fr.parse_fl_date("25 декабря, 10:00", today) == "2025-12-25"        # no year, later than today: last year
    assert fr.parse_fl_date("3 марта 2024", today) == "2024-03-03"
    assert fr.parse_fl_date("непонятно", today) == ""
    assert fr.parse_fl_price("по договоренности") == (None, None, "")
    assert fr.parse_fl_price("2&nbsp;000&nbsp;&#8381;") == (2000, 2000, "RUB")
    assert fr.parse_fl_price("40&nbsp;000&nbsp;₽ – 50&nbsp;000&nbsp;₽") == (40000, 50000, "RUB")
    assert fr.parse_fl_price("до 999&nbsp;999&nbsp;₽") == (None, None, "RUB")
    assert fr.parse_fl_price("300 $")[2] == "USD"


def test_parse_fl_list_page():
    page = fl_item(10, "Электронная визитка", "Сделать визитку с QR", "2&nbsp;000&nbsp;&#8381;") + \
        fl_item(11, "Менеджер", "Вакансия", "по договоренности", kind="\n Вакансия&nbsp;(Россия) ", answers="Нет ответов")
    a, b = fr.parse_fl(page, dt.date(2026, 11, 21))
    assert (a["id"], a["title"], a["budget"], a["offers"], a["date"]) == ("10", "Электронная визитка", 2000, 5, "2026-11-18")
    assert a["url"] == "https://www.fl.ru/projects/10/slug.html"
    assert b["kind"].startswith("Вакансия") and b["offers"] == 0 and b["budget"] is None


def fake_network(kwork_wants: list[dict], fl_pages: list[str]):
    def get_text(url, **kw):
        if url.startswith("https://kwork.ru/projects"):
            return kwork_page(kwork_wants if "?c=" not in url else kwork_wants[:1])
        if url == fr.FL:
            return fl_pages[0]
        n = int(url.rstrip("/").rsplit("-", 1)[1])
        return fl_pages[n - 1] if n <= len(fl_pages) else "<html>404</html>"
    return get_text


def fake_llm(calls: list):
    def chat_json(ws, messages, **kw):
        user = messages[-1]["content"]
        calls.append(user)
        labels = {}
        for nid in ("recipes", "cards", "repair"):
            if f"- {nid}:" in user:
                low = user.lower()
                labels[nid] = "build" if "приложение" in low else "service" if "визитк" in low else "topic"
        return {"labels": labels}, False, None
    return chat_json


def test_run_labels_matches_and_accumulates_history(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    wants = [want(1, "Приложение для рецептов", "iOS и Android", price="60000.00", offers=12),
             want(2, "Иллюстрации к рецептам", "10 картинок блюд", price="3000.00"),
             want(3, "Расчёт стоимости доставки", "скрипт", price="2000.00")]          # the stem of the car repair niche must not match
    fl_pages = [fl_item(10, "Электронная визитка", "Сделать визитку с QR", "2&nbsp;000&nbsp;&#8381;")
                + fl_item(11, "Нужен автосервис-менеджер", "Вакансия", "по договоренности", kind="Вакансия&nbsp;(Россия)")]
    monkeypatch.setattr(http, "get_text", fake_network(wants, fl_pages))
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call"))
    monkeypatch.setenv("LLM_API_KEY", "test")
    calls: list = []
    monkeypatch.setattr(llm, "chat_json", fake_llm(calls))
    fr.run(ws, args())
    rows = {r["niche_id"]: r for r in read_csv(ws.out("freelance.csv"))}
    assert rows["recipes"]["kwork_candidates"] == "2" and rows["recipes"]["kwork_matched"] == "1"
    assert rows["recipes"]["kwork_build"] == "1" and rows["recipes"]["kwork_budget_med"] == "60000"
    assert rows["cards"]["fl_service"] == "1" and rows["cards"]["fl_budget_med"] == "2000" and rows["cards"]["matched"] == "1"
    assert rows["repair"]["matched"] == "0" and rows["repair"]["fl_candidates"] == "0"    # vacancy not counted, stem override
    assert rows["recipes"]["verified"] == "1.0" and rows["recipes"]["kwork_posts"] == "3" and rows["repair"]["verified"] == ""
    assert "Приложение для рецептов" in rows["recipes"]["examples"]
    labels = {(m["niche_id"], m["id"]): m["label"] for m in read_csv(ws.out("freelance_matches.csv"))}
    assert labels == {("recipes", "1"): "build", ("recipes", "2"): "topic", ("cards", "10"): "service"}
    assert "Evidence only" in ws.report("freelance.md").read_text(encoding="utf-8")
    # a later run sees a new request; the old ones stay in the history with their first_seen date
    ws2 = make_ws(tmp_path, as_of="2026-11-23")
    wants2 = [want(4, "Ещё одно приложение рецептов", "Android", price="30000.00")]
    monkeypatch.setattr(http, "get_text", fake_network(wants2, fl_pages))
    fr.run(ws2, args(source="kwork"))
    hist = {(r["source"], r["id"]): r for r in read_csv(ws2.out("freelance_history.csv"))}
    assert hist[("kwork", "1")]["first_seen"] == "2026-11-21" and hist[("kwork", "1")]["last_seen"] == "2026-11-21"
    assert hist[("kwork", "4")]["first_seen"] == "2026-11-23" and ("fl", "10") in hist
    rows = {r["niche_id"]: r for r in read_csv(ws2.out("freelance.csv"))}
    assert rows["recipes"]["kwork_matched"] == "2" and rows["recipes"]["kwork_snapshots"] == "2"


def test_run_without_llm_counts_unverified_candidates(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(http, "get_text", fake_network([want(2, "Иллюстрации к рецептам", "блюда")], ["<html></html>"]))
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: pytest.fail("LLM call"))
    fr.run(ws, args(no_llm=True))
    rows = {r["niche_id"]: r for r in read_csv(ws.out("freelance.csv"))}
    assert rows["recipes"]["verified"] == "0.0" and rows["recipes"]["kwork_matched"] == "1"
    assert "NOT verified" in ws.report("freelance.md").read_text(encoding="utf-8")


def test_offline_rematches_history_without_fetching(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(http, "get_text", fake_network([want(1, "Приложение рецептов", "")], ["<html></html>"]))
    fr.run(ws, args(no_llm=True))
    monkeypatch.setattr(http, "get_text", lambda *a, **k: pytest.fail("network call"))
    fr.run(ws, args(no_llm=True, offline=True))
    rows = {r["niche_id"]: r for r in read_csv(ws.out("freelance.csv"))}
    assert rows["recipes"]["kwork_matched"] == "1"


def test_dead_llm_is_probed_once_and_falls_back_to_keywords(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    wants = [want(1, "Приложение рецептов", ""), want(2, "Рецепты для блога", ""), want(3, "Визитка", "")]
    monkeypatch.setattr(http, "get_text", fake_network(wants, ["<html></html>"]))
    monkeypatch.setenv("LLM_API_KEY", "test")
    calls: list = []
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (calls.append(1), (None, False, None))[1])
    fr.run(ws, args())
    assert len(calls) == 1
    rows = {r["niche_id"]: r for r in read_csv(ws.out("freelance.csv"))}
    assert rows["recipes"]["kwork_matched"] == "2" and rows["recipes"]["verified"] == "0.0"
    assert "NOT verified (the LLM gave no answer" in ws.report("freelance.md").read_text(encoding="utf-8")
