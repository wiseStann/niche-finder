"""Offline tests for the Telegram side of the info cohort: links in descriptions (info_youtube) and info_telegram."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml

from nichefinder import http
from nichefinder.stages import info_telegram, info_youtube
from nichefinder.workspace import Workspace

PAD = "<!-- " + "x" * 2100 + " -->"     # real pages are ~10 KB; shorter responses are not cached


def page(extra: str = "", title: str = "T", desc: str = "") -> str:
    d = f'<div class="tgme_page_description" dir="auto">{desc}</div>' if desc else ""
    e = f'<div class="tgme_page_extra">{extra}</div>' if extra else ""
    return f'<html><meta property="og:title" content="{title}">{d}{e}{PAD}</html>'


def test_tg_links_from_descriptions():
    text = ("Канал: https://t.me/s/KnitSchool и t.me/+AbCdEf12 · ТГ @Knit_Club · почта knit@yandex.ru · "
            "Instagram @knit_insta · бот t.me/knit_lessons_bot · t.me/share/url?x=1 · https://t.me/knitschool")
    assert info_youtube.tg_links(text) == ["knitschool", "+AbCdEf12", "knit_club"]
    assert info_youtube.tg_links("", "Telegram - @Other_Chan") == ["other_chan"]


def test_parse_page_kinds_and_counts():
    ch = info_telegram.parse_page(page("12&nbsp;345 subscribers", "Школа вязания",
                                       'Курс <a href="https://school.getcourse.ru/pay">тут</a>'))
    assert (ch["kind"], ch["count"], ch["title"]) == ("channel", 12345, "Школа вязания")
    assert "getcourse.ru/pay" in ch["description"]
    grp = info_telegram.parse_page(page("1 234 members, 56 online"))
    assert (grp["kind"], grp["count"]) == ("group", 1234)
    user = info_telegram.parse_page(page("@someone"))
    assert (user["kind"], user["count"]) == ("other", None)


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["ru"], "as_of": "2026-11-21"}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "info_topics.yaml").write_text(yaml.safe_dump(
        {"_settings": {"lang": "ru", "region": "RU", "window_months": 12, "seeds": []},
         "topics": [{"id": "knit", "q": ["вязание"]}, {"id": "math", "q": ["математика"]}]}, allow_unicode=True),
        encoding="utf-8")
    (tmp_path / "config" / "score_info.yaml").write_text(yaml.safe_dump({"telegram": {"sleep": 0}}), encoding="utf-8")
    return Workspace(tmp_path)


def test_info_telegram_end_to_end(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    vids = [  # topic, channel, kind, links, pay
        ("knit", "A", "T", "knita", "0"), ("knit", "A", "T", "knita knita2", "0"),   # one author, two links
        ("knit", "B", "T", "knitb", "0"), ("knit", "C", "T", "", "1"),                # C sells, no Telegram
        ("knit", "D", "E", "knitd", "0"),                                             # a sketch: not counted
        ("knit", "E", "T", "sponsor", "0"), ("math", "F", "T", "sponsor mathf", "0"), # sponsor named by E and F
    ]
    with open(ws.out("info_youtube_videos.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=info_youtube.VIDEO_COLS, extrasaction="ignore")
        w.writeheader()
        for i, (t, ch, kind, links, pay) in enumerate(vids):
            w.writerow({"topic_id": t, "video_id": f"v{i}", "channel_id": ch, "kind": kind, "tg_links": links,
                        "pay": pay, "title": "x"})
    pages = {"knita": page("20 000 subscribers", "Вязание | Анна"), "knita2": page("500 subscribers"),
             "knitb": page("3 000 subscribers", desc='<a href="https://boosty.to/knitb">Boosty</a>'),
             "sponsor": page("590 000 subscribers"), "mathf": page("@mathf")}
    calls = []

    def fake(url, **kw):
        calls.append(url)
        return http.Response(200, pages[url.rsplit("/", 1)[-1]])
    monkeypatch.setattr(http, "request", fake)
    info_telegram.run(ws, argparse.Namespace())
    rows = {r["topic_id"]: r for r in csv.DictReader(open(ws.out("info_telegram.csv"), encoding="utf-8"))}
    knit = rows["knit"]
    assert (knit["yt_channels"], knit["tg_linked"]) == ("4", "2")       # A, B, C, E with teaching videos; D a sketch
    assert float(knit["tg_subs_median"]) == 11500 and knit["tg_subs_max"] == "20000"   # A counts once, its largest
    assert knit["tg_big"] == "1" and knit["pay_share"] == "0.5"          # B via its Telegram page, C via YouTube
    assert knit["top_channel"] == "Вязание / Анна (20000)"                 # the title, "|" would break a table
    assert rows["math"]["tg_linked"] == "0"                               # the sponsor is out, mathf is a user page
    chans = {r["link"]: r for r in csv.DictReader(open(ws.out("info_telegram_channels.csv"), encoding="utf-8"))}
    assert chans["sponsor"]["shared"] == "1" and chans["knitb"]["pay"] == "1" and "knitd" not in chans
    n = len(calls)
    info_telegram.run(ws, argparse.Namespace())
    assert len(calls) == n                                                # same month: from the cache


def test_info_score_shows_telegram_without_changing_the_score(tmp_path):
    from nichefinder.stages import info_score
    ws = make_ws(tmp_path)
    base = {"status": "ok", "phrases": "x", "window_from": "2025-11-01", "views_median": "20000", "views_p90": "100000",
            "breakout_share": "0.1", "small_share": "0.2", "tg_channel_share": "0.2", "offer_share": "0.1",
            "top3_share": "0.3", "recent_ratio": "1.0", "n_videos": "40"}
    with open(ws.out("info_youtube.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=info_youtube.TOPIC_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows([{**base, "topic_id": "knit"}, {**base, "topic_id": "math", "views_median": "90000"}])
    info_score.run(ws, argparse.Namespace())
    before = {r["topic_id"]: r["score"] for r in csv.DictReader(open(ws.out("info_score.csv"), encoding="utf-8"))}
    assert "Telegram funnels" not in ws.report("info.md").read_text(encoding="utf-8")
    with open(ws.out("info_telegram.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=info_telegram.TOPIC_COLS)
        w.writeheader()
        w.writerow({"topic_id": "knit", "yt_channels": 10, "tg_linked": 3, "tg_share": 0.3, "tg_subs_median": 12000,
                    "tg_subs_p90": 50000, "tg_subs_max": 50000, "tg_big": 2, "pay_share": 0.2,
                    "top_channel": "knitschool (50000)"})
    info_score.run(ws, argparse.Namespace())
    rows = {r["topic_id"]: r for r in csv.DictReader(open(ws.out("info_score.csv"), encoding="utf-8"))}
    assert {k: r["score"] for k, r in rows.items()} == before
    assert (rows["knit"]["tg_linked"], rows["knit"]["pay_share"], rows["math"]["tg_linked"]) == ("3", "0.2", "")
    md = ws.report("info.md").read_text(encoding="utf-8")
    assert "Telegram funnels" in md and "| knit | 10 | 3 | 12.0k | 50.0k | 2 | 20% | knitschool (50000) |" in md
    assert "- **Telegram**: 3 of 10 authors of teaching Shorts link a measurable channel" in md


def test_info_telegram_runs_between_youtube_and_score():
    from nichefinder.stages import STAGES
    names = [s.name for s in STAGES]
    assert names.index("info_youtube") + 1 == names.index("info_telegram") < names.index("info_score")
