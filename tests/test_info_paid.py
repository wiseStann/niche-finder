"""info_paid: the paid info market per info topic (Stepik courses, Litres books). Offline: http.request is faked."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import urllib.parse
from pathlib import Path

import yaml

from nichefinder import http
from nichefinder.stages import info_paid
from nichefinder.workspace import Workspace

TOPICS = [
    {"id": "english", "q": ["английский язык"], "must": "англи"},
    {"id": "law", "q": ["право"], "must": "право"},
    {"id": "knitting", "q": ["вязание спицами"]},                  # no must: the phrase words decide
]


def make_ws(tmp_path: Path, paid_cfg: dict | None = None) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["ru"], "as_of": "2026-11-21"}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "info_topics.yaml").write_text(yaml.safe_dump(
        {"_settings": {"lang": "ru", "region": "RU"}, "topics": TOPICS}, allow_unicode=True), encoding="utf-8")
    if paid_cfg is not None:
        (tmp_path / "config" / "info_paid.yaml").write_text(yaml.safe_dump(paid_cfg, allow_unicode=True),
                                                            encoding="utf-8")
    return Workspace(tmp_path)


def course(cid, title, learners, paid, price=None, published="2025-06-01", lang="ru"):
    return {"id": cid, "title": title, "summary": "", "language": lang, "learners_count": learners, "is_paid": paid,
            "price": price, "currency_code": "RUB" if paid else None, "became_published_at": f"{published}T10:00:00Z",
            "is_public": True, "review_summary": cid * 10, "canonical_url": f"https://stepik.org/course/{cid}/"}


COURSES = {
    1: course(1, "Английский с нуля", 5000, True, "2000.00"),
    2: course(2, "Грамматика английского", 90000, False),
    3: course(3, "Python для начинающих", 200000, True, "3000.00"),      # not in the title filter
    4: course(4, "English for IT", 700, True, "990.00", "2020-01-01", lang="en"),   # English-language: dropped
    5: course(5, "Английский для путешествий", 300, True, "1500.00", "2020-01-01"),
}
SEARCH = {"английский язык": [3, 1, 2, 4, 5], "право": [3], "вязание спицами": [3]}


def book(bid, title, ratings, price=300.0, free=False, available="2025-03-01", publisher=True, subtitle=None):
    persons = [{"role": "author", "full_name": "A"}] + ([{"role": "publisher", "full_name": "P"}] if publisher else [])
    return {"type": "text_book", "instance": {
        "id": bid, "title": title, "subtitle": subtitle, "language_code": "ru", "is_free": free,
        "prices": {"full_price": price, "final_price": price, "currency": "RUB"},
        "rating": {"rated_total_count": ratings}, "available_from": f"{available}T10:00:00", "persons": persons,
        "url": f"/book/x/{bid}/"}}


BOOKS = {
    "английский язык": [book(11, "Английский для всех", 800, publisher=False), book(12, "Самоучитель английского", 400,
                        available="2018-01-01"), book(13, "Английский бесплатно", 900, price=0, free=True),
                        book(14, "Английский: мало оценок", 2), book(15, "Шпион из Лондона", 5000),
                        book(16, "Английский разговорник", 50)],                  # withdrawn: the lookup answers 404
    "право": [book(21, "Право Черной Розы", 4700), book(22, "Право для чайников", 60), book(23, "Трудовое право", 3)],
    "вязание спицами": [book(31, "Вязание спицами для начинающих", 1)],
}
GENRES = {11: "иностранные языки", 12: "самоучители", 21: "любовное фэнтези", 22: "юриспруденция / право"}


class FakeApi:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url, headers=None, **kw):
        self.calls.append(url)
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        if u.netloc == "stepik.org":
            if u.path.endswith("/search-results"):
                if q["page"] == ["2"]:
                    raise http.HttpError(404, url, '{"detail": "Not found"}')       # past the end of the results
                hits = [{"target_id": i, "target_type": "course", "course_title": COURSES[i]["title"]}
                        for i in SEARCH[q["query"][0]]]
                body = {"meta": {"page": 1, "has_next": True}, "search-results": hits}
            elif u.path.endswith("/courses"):
                body = {"courses": [COURSES[int(i)] for i in q["ids[]"]]}
            else:
                body = {"course-review-summaries": [{"course": int(i) // 10, "count": 7} for i in q["ids[]"]]}
        elif u.path.endswith("/search"):
            data = BOOKS[q["q"][0]]
            body = {"payload": {"data": data, "extra": {"counters": {"text_book": 1000 + len(data)},
                                                        "pagination": {"next_offset": None}}}}
        else:
            bid = int(u.path.rstrip("/").rsplit("/", 1)[-1])
            if bid not in GENRES:
                raise http.HttpError(404, url, '{"status": 404}')
            body = {"payload": {"data": {"genres": [{"name": "прочее"}, {"name": GENRES[bid], "is_main": True}]}}}
        return http.Response(200, json.dumps(body, ensure_ascii=False))


def args(**kw):
    return argparse.Namespace(**{"topics": "", "sources": "stepik,litres", "dry": False, **kw})


def read(ws: Workspace, name: str) -> list[dict]:
    return list(csv.DictReader(open(ws.out(name), encoding="utf-8")))


def test_info_paid_metrics_flags_and_cache(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    api = FakeApi()
    monkeypatch.setattr(http, "request", api)
    monkeypatch.setattr(info_paid, "SLEEP", 0)
    info_paid.run(ws, args())
    rows = {r["topic_id"]: r for r in read(ws, "info_paid.csv")}

    en = rows["english"]
    assert en["sp_status"] == "ok" and en["sp_hits"] == "5"
    # Python (title filter) and the English-language course are dropped; 1 and 5 are paid, 2 is free
    assert (en["sp_courses"], en["sp_paid"], en["sp_paid_learners"], en["sp_paid_reviews"]) == ("3", "2", "5300", "14")
    assert en["sp_price_median"] == "1750" and en["sp_paid_new"] == "1" and en["sp_top"].startswith("Английский с нуля")
    # free book 13 and book 14 (2 ratings) do not count; "Шпион из Лондона" fails the title filter
    # book 16 is gone from the store (genre lookup 404): its genre is unknown and it still counts
    assert (en["lr_total"], en["lr_hits"], en["lr_books"]) == ("1006", "6", "5")
    assert (en["lr_paid"], en["lr_ratings"], en["lr_new"], en["lr_selfpub"], en["lr_fiction"]) == ("3", "1250", "2", "1", "0")
    assert en["paid_flag"] == "I:paid-market"              # 5,300 paid learners >= 5,000

    law = rows["law"]
    assert law["lr_fiction"] == "1" and law["lr_paid"] == "1" and law["lr_ratings"] == "60"   # the novel is dropped
    assert law["sp_paid"] == "0" and law["paid_flag"] == "I:no-paid"   # 1 book sold < 3, no paid course

    kn = rows["knitting"]                                   # phrase words: "вязан" + "спиц"
    assert kn["lr_books"] == "1" and kn["lr_paid"] == "0" and kn["paid_flag"] == "I:no-paid"

    items = read(ws, "info_paid_items.csv")
    novel = next(i for i in items if i["id"] == "21")
    assert novel["note"] == "fiction: любовное фэнтези"
    assert {i["id"] for i in items if i["topic_id"] == "english"} == {"1", "2", "5", "11", "12", "16"}

    # the second run is served from the cache: no network calls
    n = len(api.calls)
    info_paid.run(ws, args())
    assert len(api.calls) == n
    assert {r["topic_id"]: r["paid_flag"] for r in read(ws, "info_paid.csv")} == {
        "english": "I:paid-market", "law": "I:no-paid", "knitting": "I:no-paid"}


def test_info_paid_overrides_thresholds_and_sources(tmp_path, monkeypatch):
    cfg = {"flags": {"paid_market": {"stepik_learners": 10_000, "litres_ratings": 50}, "no_paid": {"litres_books": 1}},
           "topics": {"law": {"must": "чайник"}}}
    ws = make_ws(tmp_path, cfg)
    monkeypatch.setattr(http, "request", FakeApi())
    monkeypatch.setattr(info_paid, "SLEEP", 0)
    info_paid.run(ws, args(topics="law,english", sources="litres"))
    rows = {r["topic_id"]: r for r in read(ws, "info_paid.csv")}
    assert set(rows) == {"law", "english"} and rows["law"]["sp_status"] == ""
    assert rows["law"]["lr_books"] == "1" and rows["law"]["lr_fiction"] == "0"   # override: only "...для чайников"
    assert rows["law"]["paid_flag"] == "I:paid-market"      # 60 ratings >= 50
    # Stepik not read: no I:no-paid without both sources, and the 5,300 learners are unknown
    assert rows["english"]["paid_flag"] == "I:paid-market"  # 1,250 ratings >= 50


def test_info_paid_source_error_is_reported(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)

    def broken(url, **kw):
        if "stepik" in url:
            raise OSError("connection refused")
        return FakeApi()(url, **kw)
    monkeypatch.setattr(http, "request", broken)
    monkeypatch.setattr(info_paid, "SLEEP", 0)
    info_paid.run(ws, args(topics="knitting"))
    row = read(ws, "info_paid.csv")[0]
    assert row["sp_status"].startswith("error") and row["lr_status"] == "ok"
    assert row["paid_flag"] == ""                           # one source failed: no I:no-paid


def test_matcher_and_paid_flag_rules():
    m = info_paid.matcher({"id": "x", "q": ["вязание спицами", "вязание крючком"]})
    assert m.search("Спицы и вязание") and m.search("Вязание КРЮЧКОМ для детей") and not m.search("Вязание")
    assert info_paid.matcher({"id": "x", "q": ["x"], "must": "англи"}).search("АНГЛИЙСКИЙ")
    flags = info_paid.DEFAULTS["flags"]
    ok = {"sp_status": "ok", "lr_status": "ok"}
    assert info_paid.paid_flag({**ok, "sp_paid": "0", "lr_paid": "2", "lr_ratings": "20"}, flags) == "I:no-paid"
    assert info_paid.paid_flag({**ok, "sp_paid": "1", "lr_paid": "0", "sp_paid_learners": "10"}, flags) == ""
    assert info_paid.paid_flag({**ok, "sp_paid": "0", "lr_paid": "40", "lr_ratings": "3500"}, flags) == "I:paid-market"
    assert info_paid.paid_flag({**ok, "sp_paid": "0", "lr_paid": "2", "lr_ratings": "300"}, flags) == ""   # 2 books sell
    strip = info_paid.DEFAULTS["phrase_strip"]
    assert info_paid.paid_phrases({"q": ["танцы для начинающих", "танцы", "Python с нуля"]}, strip) == ["танцы", "Python"]
    assert info_paid.months_back(dt.date(2026, 11, 21), 24) == dt.date(2024, 11, 1)


def test_info_paid_without_topics_does_nothing(tmp_path):
    (tmp_path / "nf.yaml").write_text("markets: [ru]\n", encoding="utf-8")
    ws = Workspace(tmp_path)
    info_paid.run(ws, args())
    assert not ws.out("info_paid.csv").exists()
