"""Offline tests for ru_ecosystems: keyword stemming, MoySklad sitemap / category / app page parsing, the amoCRM
showcase, category mapping and the per niche x marketplace metrics."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import pytest
import yaml

from nichefinder import http
from nichefinder.stages import ru_ecosystems as eco
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["ru"], "as_of": "2026-11-21"}), encoding="utf-8")
    (tmp_path / "niches.yaml").write_text("[]", encoding="utf-8")
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "ru_b2b_niches.yaml").write_text(yaml.safe_dump([
        {"id": "ru-sellers", "bitrix": ["wildberries", "ozon", "маркетплейс"]},
        {"id": "ru-bots", "bitrix": ["чат-бот", "telegram бот"]},
        {"id": "ru-auto", "bitrix": ["автосервис", "сто"]},
        {"id": "ru-lms", "bitrix": ["курсы"]},
    ], allow_unicode=True), encoding="utf-8")
    (cfg / "ru_ecosystems.yaml").write_text(yaml.safe_dump({
        "sleep": 0, "keywords": {"ru-lms": ["обучение сотрудников"]},
        "categories": {"moysklad": {"ru-bots": ["chaty"]}, "amocrm": {"ru-bots": ["chats"]}}}, allow_unicode=True),
        encoding="utf-8")
    return Workspace(tmp_path)


def test_keyword_regex_stems_and_short_words():
    rx = re.compile(eco.keyword_regex("салон красоты"), re.I)
    assert rx.search("CRM для салонов красоты") and rx.search("салон-красоты")
    sto = re.compile(eco.keyword_regex("сто"), re.I)
    assert sto.search("запись в СТО онлайн") and not sto.search("стоимость доставки") and not sto.search("просто")
    tg = re.compile(eco.keyword_regex("telegram бот"), re.I)
    assert tg.search("Telegram-бот для заказов") and not tg.search("telegram канал")
    assert re.compile(eco.keyword_regex("чат-бот"), re.I).search("чат бот для магазина")


def ms_app(name, paid="Платное решение", dev="ДевСтудия", up="2026-03-01", desc="Описание"):
    return (f'<span class="d-none" data-ms-upload-date="{up}T08:17:08+03:00"></span><div class="fw-bold">{paid}</div>'
            f'<div class="fw-bold mb-1">Разработчик</div>\n<a href="https://x.ru/">\n {dev} </a><h1 class="mb-5">{name}</h1>'
            f"<p>{desc}</p><h2>Другие решения этого разработчика</h2><p>Интеграция с Wildberries</p>")


def ms_tiles(*apps):
    tiles = "".join(f'<h3 class="card-title mb-1"><a class="stretched-link" href="/integratsii/apps/{s}/">{n}</a></h3>\n'
                    f'<p class="mb-0">{d}</p>' for s, n, d in apps)
    return f'<div data-load-more="container">{tiles}</div><div data-load-more="skeleton"></div>'


def amo_tile(slug, desc):
    return (f'<a class="extensions__item-link" href="/extensions/{slug}/"><div class="extensions__item-image"></div>'
            f'<div class="extensions__item-description"><p>{desc}</p>\n</div></a>')


PAGES = {
    "https://www.moysklad.ru/sitemap.xml": "<urlset><url><loc>https://www.moysklad.ru/integratsii/apps/ozon-x/</loc></url>"
                                           "<url><loc>https://www.moysklad.ru/integratsii/apps/bot-y/</loc></url>"
                                           "<url><loc>https://www.moysklad.ru/integratsii/apps/rates-z/</loc></url></urlset>",
    "https://www.moysklad.ru/integratsii/": '<a class="x" href="/integratsii/chaty/">\n Чаты </a>'
                                            '<a href="/integratsii/populyarnoe/">Популярное</a><a href="/integratsii/apps/ozon-x/">x</a>',
    "https://www.moysklad.ru/integratsii/chaty/": ms_tiles(("bot-y", "Бот Y", "Ответы в мессенджерах")),
    "https://www.moysklad.ru/integratsii/populyarnoe/": ms_tiles(("ozon-x", "Ozon X", "Заказы с маркетплейса")),
    "https://www.moysklad.ru/integratsii/apps/ozon-x/": ms_app("Интеграция с OZON", desc="Заказы и остатки"),
    "https://www.moysklad.ru/integratsii/apps/bot-y/": ms_app("Бот Y", paid="Бесплатное решение", dev="Другой", up="2024-01-01",
                                                              desc="Уведомления клиентам"),
    "https://www.moysklad.ru/integratsii/apps/rates-z/": ms_app("Курсы валют", dev="ДевСтудия", desc="Курсы ЦБ"),
    "https://www.amocrm.ru/extensions/": amo_tile("wazzup", "Чат-бот и WhatsApp в amoCRM") + amo_tile("1c", "Обмен с 1С"),
    "https://www.amocrm.ru/extensions/?group=chats": amo_tile("wazzup", "Чат-бот и WhatsApp в amoCRM")
                                                     + amo_tile("radist", "Мессенджеры в карточке"),
}


def test_parsers():
    a = eco.parse_ms_app(PAGES["https://www.moysklad.ru/integratsii/apps/ozon-x/"])
    assert (a["name"], a["paid"], a["developer"], a["upload_date"]) == ("Интеграция с OZON", 1, "ДевСтудия", "2026-03-01")
    assert "Wildberries" not in a["description"]                     # the developer's other apps are cut off
    assert eco.parse_ms_app(ms_app("B", paid="Бесплатное решение"))["paid"] == 0
    assert eco.parse_ms_tiles(PAGES["https://www.moysklad.ru/integratsii/chaty/"]) == [("bot-y", "Бот Y", "Ответы в мессенджерах")]
    assert eco.parse_ms_categories(PAGES["https://www.moysklad.ru/integratsii/"]) == {"chaty": "Чаты", "populyarnoe": "Популярное"}
    assert eco.parse_amo(PAGES["https://www.amocrm.ru/extensions/"])[0] == ("wazzup", "Чат-бот и WhatsApp в amoCRM")


def test_run_matches_catalogs_to_niches(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(http, "get_text", lambda url, **kw: PAGES.get(url, ""))
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call"))
    eco.run(ws, argparse.Namespace(marketplace="all", max_apps=0))
    rows = {(r["niche_id"], r["marketplace"]): r for r in csv.DictReader(open(ws.out("ru_ecosystems.csv"), encoding="utf-8"))}
    s = rows[("ru-sellers", "moysklad")]
    assert (s["catalog"], s["apps"], s["paid_share"], s["popular"], s["top_developer"]) == ("3", "1", "1.0", "1", "ДевСтудия")
    assert s["updated_12m"] == "1"
    b = rows[("ru-bots", "moysklad")]
    assert b["apps"] == "1" and b["paid_share"] == "0.0" and b["updated_12m"] == "0"   # by the chaty category, free, old
    assert rows[("ru-bots", "amocrm")]["apps"] == "2" and rows[("ru-bots", "amocrm")]["catalog"] == "3"
    assert rows[("ru-lms", "moysklad")]["apps"] == "0"                 # the keyword override drops the currency-rate app
    assert rows[("ru-auto", "amocrm")]["apps"] == "0"
    apps = list(csv.DictReader(open(ws.out("ru_ecosystems_apps.csv"), encoding="utf-8")))
    by = {(a["marketplace"], a["niche_id"], a["slug"]): a["matched_by"] for a in apps}
    assert by[("moysklad", "ru-sellers", "ozon-x")] == "kw:ozon"
    assert by[("moysklad", "ru-bots", "bot-y")] == "cat:chaty"
    assert by[("amocrm", "ru-bots", "wazzup")] == "kw:чат-бот cat:chats"
