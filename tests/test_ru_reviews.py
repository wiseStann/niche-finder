"""Offline tests for the Russian review stages (S10): RSS and Startpack parsing, app choice, fetch from cache, sampling,
LLM labels (with a fake model), the verdict rule with segments, and the report."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import pytest
import yaml

from nichefinder import http, llm, tools
from nichefinder.sources import startpack
from nichefinder.stages import s10_ru_reviews_classify as classify
from nichefinder.stages import s10_ru_reviews_fetch as fetch
from nichefinder.stages import s10_ru_reviews_report as report
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": "2026-11-17"}), encoding="utf-8")
    base = {"who": "people", "task": "do things", "product": "app", "side": "b2c", "tier": "A"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "budget", "name": "Budget apps", "geo": "both", **base},
        {"id": "habits", "name": "Habit trackers", "geo": "ru", **base},
        {"id": "usonly", "name": "US only", "geo": "global", **base},
    ]), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(
        yaml.safe_dump({"tier_a": [{"id": "budget"}, {"id": "usonly"}], "tier_b": ["habits"]}), encoding="utf-8")
    return Workspace(tmp_path)


def write_csv(path: Path, rows: list[dict], bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig" if bom else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def rss_entry(rid, date, rating, text, title="t"):
    return {"id": {"label": rid}, "updated": {"label": f"{date}T10:00:00-07:00"}, "im:rating": {"label": str(rating)},
            "title": {"label": title}, "content": {"label": text}, "im:version": {"label": "1.0"}, "im:voteSum": {"label": "2"}}


def test_parse_rss_list_single_and_missing():
    page = {"feed": {"entry": [{"im:name": {"label": "The app itself"}}, rss_entry("1", "2026-11-01", 2, "Crashes on start")]}}
    (r,) = fetch.parse_rss(page)
    assert (r["id"], r["date"], r["rating"], r["text"], r["thumbs"]) == ("1", "2026-11-01", 2, "Crashes on start", 2)
    assert len(fetch.parse_rss({"feed": {"entry": rss_entry("2", "2026-11-02", 5, "Fine")}})) == 1
    assert fetch.parse_rss({"feed": {"id": {"label": "x"}}}) == []


def apps_fixture(ws: Workspace) -> None:
    write_csv(ws.out("appstore_apps.csv"), [
        {"niche_id": "budget", "store": "ru", "track_id": "111", "name": "Money RU", "seller": "A", "ratings": 900, "rating": 4.5, "relevant": 1},
        {"niche_id": "budget", "store": "ru", "track_id": "112", "name": "Coins", "seller": "B", "ratings": 300, "rating": 4.1, "relevant": 1},
        {"niche_id": "budget", "store": "ru", "track_id": "113", "name": "Tiny", "seller": "C", "ratings": 5, "rating": 5.0, "relevant": 1},
        {"niche_id": "budget", "store": "ru", "track_id": "114", "name": "Off topic", "seller": "D", "ratings": 9000, "rating": 4.9, "relevant": 0},
        {"niche_id": "budget", "store": "us", "track_id": "115", "name": "US app", "seller": "E", "ratings": 9000, "rating": 4.9, "relevant": 1},
        {"niche_id": "usonly", "store": "ru", "track_id": "116", "name": "Stray", "seller": "F", "ratings": 9000, "rating": 4.9, "relevant": 1},
    ])
    write_csv(ws.out("gplay_apps.csv"), [
        {"niche_id": "habits", "country": "ru", "appId": "com.habit", "title": "Habit", "developer": "G", "ratings": 5000, "score": 4.2},
        {"niche_id": "habits", "country": "us", "appId": "com.habit.us", "title": "Habit US", "developer": "G", "ratings": 9000, "score": 4.2},
    ], bom=True)


def fake_fit(calls):
    """A fake product check: every listed app fits unless its name has "Game" in it."""
    def chat(ws, messages, **kw):
        calls.append(messages[1]["content"])
        lines = [x for x in messages[1]["content"].split("\n") if re.match(r"\d+: ", x)]
        return {"apps": [{"k": int(x.split(":")[0]), "fit": "no" if "Game" in x else "yes", "why": "w"} for x in lines]}, False, None
    return chat


def test_pick_apps_leading_relevant_russian_apps(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    apps_fixture(ws)
    calls = []
    monkeypatch.setattr(llm, "chat_json", fake_fit(calls))
    ids = fetch.target_niches(ws)
    assert ids == ["budget", "habits"]   # geo global is not measured
    st = {**fetch.DEFAULTS["fetch"], "apps_per_store": 1}
    apps, _ = fetch.pick_apps(ws, ids, st)
    assert [(a["niche_id"], a["store"], a["app_id"]) for a in apps] == [("budget", "appstore", "111"), ("habits", "gplay", "com.habit")]
    apps, fit = fetch.pick_apps(ws, ids, fetch.DEFAULTS["fetch"])
    assert [a["app_id"] for a in apps] == ["111", "112", "com.habit"]   # 113 has too few ratings, 114 is not relevant, 115 is the US store
    assert "Who: people" in calls[0] and "1: Money RU | A | -" in calls[0]   # one call per niche: the niche and the candidates
    assert {(r["app_id"], r["fit"], r["by"]) for r in fit} == {("111", "yes", "llm"), ("112", "yes", "llm"), ("com.habit", "yes", "llm")}


def test_product_check_drops_apps_and_config_overrides_it(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    write_csv(ws.out("appstore_apps.csv"), [
        {"niche_id": "budget", "store": "ru", "track_id": "201", "name": "Cookie Game", "seller": "G", "ratings": 9000, "rating": 4.5,
         "genre": "Games", "relevant": 1},
        {"niche_id": "budget", "store": "ru", "track_id": "202", "name": "Money RU", "seller": "A", "ratings": 900, "rating": 4.5, "relevant": 1},
        {"niche_id": "budget", "store": "ru", "track_id": "203", "name": "Coins", "seller": "B", "ratings": 300, "rating": 4.1, "relevant": 1},
    ])
    monkeypatch.setattr(llm, "chat_json", fake_fit([]))
    apps, fit = fetch.pick_apps(ws, ["budget"], fetch.DEFAULTS["fetch"])
    assert [a["app_id"] for a in apps] == ["202", "203"]   # the most-rated candidate is not a product of the niche
    assert {r["app_id"]: r["fit"] for r in fit} == {"201": "no", "202": "yes", "203": "yes"}
    (tmp_path / "config" / "ru_reviews.yaml").write_text(yaml.safe_dump({"apps": {"budget": {"keep": ["201"], "drop": [203]}}}), encoding="utf-8")
    apps, fit = fetch.pick_apps(ws, ["budget"], fetch.DEFAULTS["fetch"])
    assert [a["app_id"] for a in apps] == ["201", "202"]
    assert {r["app_id"]: (r["fit"], r["by"]) for r in fit}["203"] == ("no", "config")


def test_product_check_without_an_answer_keeps_no_app(tmp_path, monkeypatch, capsys):
    ws = make_ws(tmp_path)
    apps_fixture(ws)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (None, False, None))
    apps, fit = fetch.pick_apps(ws, ["budget"], fetch.DEFAULTS["fetch"])
    assert apps == [] and {r["fit"] for r in fit} == {""}
    assert "no answer for budget" in capsys.readouterr().out


def test_fetch_reads_cached_pages_and_applies_the_window(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    apps_fixture(ws)
    month = "2026-11"
    pages = {"111": [rss_entry("a1", "2026-11-10", 1, "Lost all my data after the update"), rss_entry("a2", "2025-01-01", 1, "Too old"),
                     rss_entry("a3", "2026-10-01", 5, "")],
             "112": [rss_entry("b1", "2026-09-09", 4, "Good, but needs export")]}
    for app_id, entries in pages.items():
        path = http.cache_file(ws.cache("ru_reviews"), f"{month}|appstore|{app_id}|1")
        path.write_text(json.dumps({"feed": {"entry": entries}}), encoding="utf-8")
    (ws.cache("gplay_reviews") / f"ru_com.habit_{month}.json").write_text(json.dumps({"reviews": [
        {"id": "g1", "date": "2026-11-15T08:00:00.000Z", "score": 2, "text": "Subscription is too expensive", "thumbsUp": 3}]}), encoding="utf-8")

    def no_node(*a, **k):
        raise AssertionError("the Node helper must not run when every app is cached")

    monkeypatch.setattr(tools, "run_node", no_node)
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call"))
    monkeypatch.setattr(llm, "chat_json", fake_fit([]))
    fetch.run(ws, argparse.Namespace(niches=""))
    docs = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8")]
    assert sorted(d["id"] for d in docs) == ["a1", "b1", "g1"]   # too old and empty text are dropped
    assert len(list(csv.DictReader(open(ws.out(fetch.FIT), encoding="utf-8")))) == 3
    g1 = next(d for d in docs if d["id"] == "g1")
    assert (g1["niche_id"], g1["store"], g1["date"], g1["rating"]) == ("habits", "gplay", "2026-11-15", 2)
    apps = {r["app_id"]: r for r in csv.DictReader(open(ws.out(fetch.APPS), encoding="utf-8"))}
    assert (apps["111"]["fetched"], apps["111"]["kept"], apps["111"]["oldest"], apps["111"]["status"]) == ("3", "1", "2026-11-10", "ok")

    # a partial run replaces only its own niches
    fetch.run(ws, argparse.Namespace(niches="habits"))
    docs = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8")]
    assert sorted(d["id"] for d in docs) == ["a1", "b1", "g1"]


def test_sample_round_robin_over_apps_and_min_chars():
    long = "x" * 50
    docs = ([{"store": "appstore", "app_id": "big", "id": f"b{i}", "text": long} for i in range(30)]
            + [{"store": "gplay", "app_id": "small", "id": f"s{i}", "text": long} for i in range(3)]
            + [{"store": "gplay", "app_id": "small", "id": "short", "text": "Super!"}])
    got = classify.sample(docs, 10, 40)
    assert len(got) == 10
    assert sum(1 for d in got if d["app_id"] == "small") == 3   # the small app gets its whole share, not 1 in 11
    assert all(d["id"] != "short" for d in got)
    assert [d["id"] for d in got] == [d["id"] for d in classify.sample(list(reversed(docs)), 10, 40)]   # deterministic


def fake_chat_json(ws, messages, **kw):
    """Labels by keyword: 'export' -> missing_feature, 'crash' -> bug, 'driver' -> service, else praise."""
    user = messages[-1]["content"]
    if messages[0]["content"] == classify.SYSTEM:
        items = []
        for j, body in re.findall(r"### item (\d+)\n[^\n]*\n(.*?)(?=\n\n### item|\Z)", user, re.S):
            low = body.lower()
            if "driver" in low:
                items.append({"i": j, "about": "service", "intent": "other"})
            elif "export" in low:
                items.append({"i": j, "about": "app", "intent": "missing_feature", "pain": "no export", "quote": body[:40], "wtp": "none"})
            elif "crash" in low:
                items.append({"i": j, "about": "app", "intent": "bug", "pain": "crashes", "from_to": "a -> b", "wtp": "none"})
            else:
                items.append({"i": j, "about": "app", "intent": "praise", "wtp": "worth_it"})
        return {"items": items}, False, {"prompt_tokens": 10, "completion_tokens": 5}
    return {"themes": [{"theme": "No export", "kind": "unmet", "count": 2, "quotes": ["q"]}]}, False, None


def test_classify_shares_over_reviews_about_the_app(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    texts = ["Please add export to Excel, I need it every month"] * 2 + ["It crashes every time I open the report screen"] \
        + ["The driver was late and rude, never again with them"] + ["Works great, simple and clean, I use it every day"]
    with open(ws.out(fetch.DOCS), "w", encoding="utf-8") as fh:
        for i, t in enumerate(texts):
            fh.write(json.dumps({"niche_id": "budget", "store": "gplay", "app_id": f"app{i % 2}", "app": f"App {i % 2}", "id": str(i),
                                 "date": "2026-11-01", "rating": 3, "title": "", "text": t}) + "\n")
    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    classify.run(ws, argparse.Namespace(niches="", dry=False))
    (row,) = csv.DictReader(open(ws.out("ru_reviews_llm.csv"), encoding="utf-8"))
    assert (row["classified"], row["about_app"], row["apps"]) == ("5", "4", "2")
    assert (float(row["unmet_share"]), float(row["quality_share"]), float(row["praise_share"])) == (0.5, 0.25, 0.25)
    assert row["top_theme"] == "No export" and row["top_switch"] == "a -> b"
    themes = json.loads(ws.out("ru_reviews_themes.json").read_text(encoding="utf-8"))["budget"]
    assert sum(a["n"] for a in themes["apps"].values()) == 4 and themes["about"]["service"] == 1


def llm_row(nid, about_app=120, apps=3, unmet=0.1, quality=0.2, praise=0.3, unmet_low=None, low=60, price_low=0.0):
    """A ru_reviews_llm.csv row plus the unhappy-review fields the report adds; the gap share defaults to `unmet`."""
    return {"niche_id": nid, "about_app": about_app, "apps": apps, "unmet_share": unmet, "quality_share": quality, "praise_share": praise,
            "missing_feature_share": unmet, "pricing_share": price_low, "switching_share": 0,
            "unmet_low_share": unmet if unmet_low is None else unmet_low, "low_reviews": low, "price_low_share": price_low}


def test_verdict_rule_is_relative_with_floors():
    cfg = fetch.DEFAULTS["verdict"]
    rows = {r["niche_id"]: r for r in [
        llm_row("gap", unmet=0.40), llm_row("gap_low_floor", unmet=0.12, quality=0.1), llm_row("quality", unmet=0.05, quality=0.60),
        llm_row("content", unmet=0.02, quality=0.05, praise=0.7), llm_row("mixed1", unmet=0.08), llm_row("mixed2", unmet=0.09, quality=0.25),
        llm_row("quiet", about_app=20, unmet=0.9)]}
    v = report.reviews_verdicts(rows, cfg)
    assert v["gap"]["verdict"] == "🟢 gap"
    assert v["gap_low_floor"]["verdict"] != "🟢 gap"   # second in the cohort, but under the 15 % floor
    assert v["quality"]["verdict"] == "🟡 quality"
    assert v["content"]["verdict"] == "🟡 content"
    assert v["mixed1"]["verdict"] == "🟡 mixed"
    assert v["quiet"]["verdict"] == "⚪ quiet" and v["gap"]["cohort"] == 6
    # a small cohort: the floors alone decide
    small = report.reviews_verdicts({k: rows[k] for k in ("gap", "mixed2")}, cfg)
    assert small["gap"]["verdict"] == "🟢 gap" and small["mixed2"]["verdict"] == "🟡 mixed"


def test_gap_counts_only_unhappy_reviews_and_few_of_them_is_unmeasured():
    cfg = fetch.DEFAULTS["verdict"]
    rows = {r["niche_id"]: r for r in [
        llm_row("wishlist", unmet=0.40, unmet_low=0.02, praise=0.6),        # feature wishes in five-star reviews
        llm_row("unhappy", unmet=0.30, unmet_low=0.20),
        llm_row("few_low", unmet=0.40, unmet_low=0.05, praise=0.8, low=10),
        llm_row("few_low_bad", unmet=0.40, unmet_low=0.05, quality=0.5, low=10)]}
    v = report.reviews_verdicts(rows, cfg)
    assert v["wishlist"]["verdict"] == "🟡 content"
    assert v["unhappy"]["verdict"] == "🟢 gap" and "in all reviews: features 30%" in v["unhappy"]["reason"]
    assert v["few_low"]["verdict"] == "⚪ unmeasured" and "only 10 of 120 reviews" in v["few_low"]["reason"]   # not "content"
    assert v["few_low_bad"]["verdict"] == "🟡 quality" and "cannot be read" in v["few_low_bad"]["reason"]
    assert v["few_low"]["unmet_pct"] == "" and v["unhappy"]["gap_cohort"] == 2


def test_gap_percentiles_only_among_niches_where_the_gap_can_be_read():
    cfg = fetch.DEFAULTS["verdict"]
    rows = {f"r{i}": llm_row(f"r{i}", unmet_low=0.16 + 0.01 * i) for i in range(6)}      # readable: 0.16 .. 0.21
    v = report.reviews_verdicts(rows, cfg)
    assert v["r3"]["verdict"] != "🟢 gap" and v["r5"]["verdict"] == "🟢 gap"
    rows.update({f"u{i}": llm_row(f"u{i}", unmet_low=0.0, low=5) for i in range(6)})     # unreadable niches must not lift the ranks
    v = report.reviews_verdicts(rows, cfg)
    assert v["r3"]["verdict"] != "🟢 gap" and v["r5"]["gap_cohort"] == 6 and v["r5"]["cohort"] == 12
    assert all(v[f"u{i}"]["verdict"] == "⚪ unmeasured" for i in range(6))


def test_unhappy_unmet_from_labeled_items(tmp_path):
    ws = make_ws(tmp_path)
    recs = [("app", 1, "missing_feature"), ("app", 3, "pricing"), ("app", 2, "bug"), ("app", 5, "missing_feature"),
            ("app", 4, "switching"), ("service", 1, "other"), ("app", None, "pricing")]
    with open(ws.out("ru_reviews_items.jsonl"), "w", encoding="utf-8") as fh:
        for about, rating, intent in recs:
            fh.write(json.dumps({"niche_id": "budget", "about": about, "rating": rating, "intent": intent}) + "\n")
    got = report.unhappy_unmet(ws, 3)["budget"]
    # 6 about the app, 3 rated <= 3: one missing feature (the gap), one price complaint (the paywall share), one bug
    assert got == {"low_reviews": 3, "unmet_low_share": round(1 / 6, 3), "price_low_share": round(1 / 6, 3)}


def test_price_is_not_a_gap_but_a_paywall_mark():
    cfg = fetch.DEFAULTS["verdict"]
    rows = {r["niche_id"]: r for r in [
        llm_row("clones", unmet=0.30, unmet_low=0.02, price_low=0.30, praise=0.2),   # a saturated clone market: paywall anger
        llm_row("gap", unmet=0.25, unmet_low=0.20, price_low=0.05),
        *(llm_row(f"m{i}", unmet=0.1, unmet_low=0.03, price_low=0.05) for i in range(4))]}
    v = report.reviews_verdicts(rows, cfg)
    assert v["clones"]["verdict"] == "🟡 mixed" and v["clones"]["paywall"] == report.PAYWALL and "a mark, not a gap" in v["clones"]["reason"]
    assert v["gap"]["verdict"] == "🟢 gap" and v["gap"]["paywall"] == ""
    assert v["m0"]["paywall"] == "" and v["clones"]["price_pct"] > 0.9
    rows["few"] = llm_row("few", unmet_low=0.0, price_low=0.4, low=10)   # the paywall share needs readable unhappy reviews too
    assert report.reviews_verdicts(rows, cfg)["few"]["paywall"] == ""


def test_report_writes_verdicts_and_a_draft_banner(tmp_path):
    ws = make_ws(tmp_path)
    write_csv(ws.out(fetch.APPS), [{"niche_id": "budget", "store": "gplay", "app_id": "a", "app": "App", "developer": "D", "ratings": 100,
                                    "rating": 4.0, "fetched": 2, "kept": 2, "oldest": "2026-10-01", "status": "ok"}])
    with open(ws.out(fetch.DOCS), "w", encoding="utf-8") as fh:
        for i, r in enumerate((1, 5)):
            fh.write(json.dumps({"niche_id": "budget", "store": "gplay", "app_id": "a", "app": "App", "id": str(i), "date": "2026-11-01",
                                 "rating": r, "title": "", "text": "y" * 60}) + "\n")
    row = {**llm_row("budget", unmet=0.3), "sampled": 2, "classified": 2, "app_share": 1, "bug_share": 0, "ux_share": 0, "ads_share": 0,
           "support_share": 0, "too_expensive": 0, "worth_it": 0, "wants_free": 0, "cancelled": 0, "themes": 0, "top_theme": "",
           "top_theme_kind": "", "top_theme_count": "", "top_switch": ""}
    for k in ("unmet_low_share", "low_reviews", "price_low_share"):   # the report counts these from the labeled items
        row.pop(k)
    write_csv(ws.out("ru_reviews_llm.csv"), [row])
    with open(ws.out("ru_reviews_items.jsonl"), "w", encoding="utf-8") as fh:
        for i in range(40):
            fh.write(json.dumps({"niche_id": "budget", "about": "app", "rating": 2 if i < 32 else 5,
                                 "intent": "missing_feature" if i < 12 else "pricing" if i < 16 else "praise"}) + "\n")
    report.run(ws, argparse.Namespace())
    md = ws.report("S10-ru-reviews.md").read_text(encoding="utf-8")
    assert "DRAFT" in md and "Budget apps" in md and "| 2 (2) | 50% |" in md
    (v,) = csv.DictReader(open(ws.out("ru_reviews_verdict.csv"), encoding="utf-8"))
    assert v["verdict"] == "🟢 gap" and v["status"] == "draft"
    assert (v["low_reviews"], v["unmet_low_share"], v["price_low_share"]) == ("32", "0.3", "0.1")


# ---- Startpack ----------------------------------------------------------------

def sp_card(code, name, reviews, stars=5):
    return (f'<div class="app-list-panel professional-plan">'
            f"<h2 class=\"app-list-name\"><a href='/application/{code}'>{name}</a></h2><div class=\"app-list-ratings\">"
            + '<span class="rating-star-15-full "></span>' * stars
            + f"<span class=\"rating-count-tag\"><a href='/application/{code}/reviews'\n title='x'>{reviews} reviews</a></span></div>"
            f'<div class="app-list-brief"><p>{name} does things</p></div>'
            f'<input type="checkbox" data-id="1" data-code="{code}"\n data-name=\'{name}\' data-cat="c"/></div>')


def sp_review(day, slug, rating, pros, cons, text):
    return (f'<article itemprop="review" id="review-1" class="review-content " data-strcode="{day}-{slug}" itemid="/review/x">'
            f'<div class="review-content-name" itemprop="headline name">{slug} title</div>'
            f"<meta itemprop=\"ratingValue\" itemscope itemtype=\"https://schema.org/Number\"\n content='{rating}' />"
            f'<div class="review-content-pluses"><h4>P</h4><div class="editor-view-text"><p>{pros}</p></div></div>'
            f'<div class="review-content-minuses"><h4>C</h4><div class="editor-view-text"><p>{cons}</p></div></div>'
            f'<div class="review-content-text with-margin"><div class="editor-view-text"><p>{text}</p></div></div></article>')


def sp_page(name, count, *reviews):
    meta = (f'<div itemprop="aggregateRating" itemscope><meta itemprop="name" content="{name}" />'
            f'<meta itemprop="ratingValue" content="4.25"/><meta itemprop="ratingCount" content="{count}" /></div>')
    return meta + "".join(reviews) + " " * startpack.MIN_PAGE   # padded: shorter pages are not served from the cache


def test_startpack_parsers():
    page = '<div class="app-list-panel start"></div>' + sp_card("prod-a", "Prod A", "1 583", 4) + sp_card("prod-b", "Prod B", 7) + '<a href="?page=3">3</a>'
    apps, last = startpack.parse_category(page)
    assert [(a["code"], a["name"], a["reviews"], a["stars"]) for a in apps] == [("prod-a", "Prod A", 1583, 4), ("prod-b", "Prod B", 7, 5)]
    assert last == 3 and apps[0]["brief"] == "Prod A does things"
    html = sp_page("Prod &amp; Co", 77, sp_review("20261101", "good", 4, "fast &amp; simple", "no export", "We use it daily."))
    (r,) = startpack.parse_reviews(html)
    assert (r["id"], r["date"], r["rating"], r["pros"], r["cons"], r["text"]) == ("20261101-good", "2026-11-01", 4, "fast & simple", "no export", "We use it daily.")
    assert startpack.review_text(r) == "Pros: fast & simple\nCons: no export\nWe use it daily."
    assert startpack.parse_meta(html) == {"name": "Prod & Co", "reviews": 77, "rating": 4.25}


def test_fetch_startpack_from_map_and_cache(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (tmp_path / "config" / "startpack_map.yaml").write_text(yaml.safe_dump({
        "budget": {"apps": ["prod-a"], "categories": ["finance"], "exclude": ["prod-x"]},
        "usonly": {"apps": ["prod-a"]}}), encoding="utf-8")
    month, cache = "2026-11", ws.cache("startpack")

    def put(key, text):
        http.cache_file(cache, key, ".html").write_text(text, encoding="utf-8")

    put(f"{month}|category|finance|1", sp_card("prod-x", "X", 900) + sp_card("prod-b", "Prod B", 40) + sp_card("prod-c", "Tiny", 2) + " " * startpack.MIN_PAGE)
    put(f"{month}|reviews|prod-a|1", sp_page("Prod A", 3, sp_review("20261101", "new", 2, "cheap", "no export", "Lacks export to Excel"),
                                             sp_review("20220101", "old", 5, "ok", "", "Too old for the window")))
    put(f"{month}|reviews|prod-b|1", sp_page("Prod B", 1, sp_review("20250505", "mid", 5, "", "", "Works well for our team")))
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call"))
    fetch.run(ws, argparse.Namespace(niches=""))
    docs = [json.loads(x) for x in open(ws.out(fetch.DOCS), encoding="utf-8")]
    assert sorted((d["app_id"], d["id"]) for d in docs) == [("prod-a", "20261101-new"), ("prod-b", "20250505-mid")]   # 36-month window
    assert all(d["niche_id"] == "budget" and d["store"] == "startpack" for d in docs)
    assert next(d for d in docs if d["app_id"] == "prod-a")["text"].startswith("Pros: cheap\nCons: no export")
    apps = {r["app_id"]: r for r in csv.DictReader(open(ws.out(fetch.APPS), encoding="utf-8"))}
    assert set(apps) == {"prod-a", "prod-b"}   # prod-x excluded, prod-c under startpack_min_reviews, usonly is geo global
    assert (apps["prod-a"]["app"], apps["prod-a"]["ratings"], apps["prod-a"]["rating"]) == ("Prod A", "3", "3.5")   # mean of the fetched reviews, not the site aggregate


def test_verdict_cohorts_per_segment_and_top_app_caution():
    cfg = fetch.DEFAULTS["verdict"]
    rows = {f"c{i}": llm_row(f"c{i}", unmet=0.10 + 0.02 * i) for i in range(6)}            # B2C: 0.10 .. 0.20
    rows.update({f"b{i}": llm_row(f"b{i}", unmet=0.16 + 0.01 * i) for i in range(6)})     # B2B: 0.16 .. 0.21
    segs = {k: ("B2C" if k.startswith("c") else "B2B") for k in rows}
    v = report.reviews_verdicts(rows, cfg, segs)
    assert v["b5"]["verdict"] == "🟢 gap" and v["b5"]["segment"] == "B2B" and v["b5"]["cohort"] == 6
    assert v["b0"]["verdict"] != "🟢 gap"            # above the floor, but at the bottom of its own segment
    assert v["c4"]["verdict"] == "🟢 gap"            # 0.18 is low against B2B, high within B2C
    pooled = report.reviews_verdicts(rows, cfg)
    assert pooled["c4"]["verdict"] != "🟢 gap"       # in one pooled cohort it would not be
    rows["b5"].update(top_app="startpack:Prod A", top_app_share=0.8)
    assert "80% of these reviews are about one product (Prod A)" in report.reviews_verdicts(rows, cfg, segs)["b5"]["reason"]
