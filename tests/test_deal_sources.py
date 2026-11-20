"""Offline tests for the Product Hunt (GraphQL API) and Empire Flippers (JSON API) S0 stages."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import pytest
import yaml

from nichefinder import http
from nichefinder.stages import s0_empireflippers, s0_producthunt
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us"], "as_of": "2026-11-17"}), encoding="utf-8")
    return Workspace(tmp_path)


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---- Product Hunt --------------------------------------------------------------

def post(slug: str, votes: int, topics: tuple[str, ...] = ("Productivity",)) -> dict:
    return {"node": {"name": slug.title(), "slug": slug, "tagline": f"{slug} for teams", "votesCount": votes,
                     "topics": {"edges": [{"node": {"name": t}} for t in topics]}}}


def page(posts: list[dict], cursor: str | None = None) -> str:
    return json.dumps({"data": {"posts": {"pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}, "edges": posts}}})


def test_ph_periods_and_bounds():
    ps = s0_producthunt.periods(dt.date(2026, 11, 17))
    assert ps[0] == (2025, 11, "monthly") and ps[11] == (2026, 10, "monthly") and len(ps) == 64
    assert ps[-1] == (2026, 45, "weekly")                         # the week of 2026-11-03, two weeks before the run
    assert s0_producthunt.bounds(2025, 12, "monthly") == ("2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z")
    assert s0_producthunt.bounds(2026, 45, "weekly") == ("2026-11-02T00:00:00Z", "2026-11-09T00:00:00Z")


def test_ph_parse_keeps_four_topics():
    rows = s0_producthunt.parse(json.loads(page([post("inkly", 412, ("A", "B", "C", "D", "E"))]))["data"]["posts"], "m2026-10")
    assert rows == [{"period": "m2026-10", "name": "Inkly", "slug": "inkly", "tagline": "inkly for teams", "votes": 412, "topics": "A|B|C|D"}]


def test_ph_run_paginates_dedupes_and_waits_out_rate_limit(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("PRODUCTHUNT_TOKEN", "test-token")
    monkeypatch.setattr(s0_producthunt.time, "sleep", lambda s: None)
    calls: list[dict] = []
    limited = {"done": False}

    def api(url, **kw):
        assert kw["headers"]["Authorization"] == "Bearer test-token"
        v = kw["data"]["variables"]
        calls.append(v)
        if not limited["done"]:
            limited["done"] = True
            return http.Response(429, json.dumps({"errors": [{"error": "rate_limit_reached", "details": {"reset_in": 30}}]}))
        if v["postedAfter"].startswith("2026-10-01"):             # the last month: two pages
            return http.Response(200, page([post("billo", 900)], "c1") if v["after"] is None else page([post("inkly", 400)]))
        return http.Response(200, page([post("billo", 900)]))      # every other period repeats one post

    monkeypatch.setattr(http, "request", api)
    s0_producthunt.run(ws, argparse.Namespace(top_month=60, top_week=20))
    rows = read_csv(ws.raw("ph_top.csv"))
    assert [(r["slug"], r["period"]) for r in rows] == [("billo", "m2025-11"), ("inkly", "m2026-10")]
    assert len(calls) == 1 + 64 + 1                               # the rate-limited try, one page per period, one extra page
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call"))
    s0_producthunt.run(ws, argparse.Namespace(top_month=60, top_week=20))   # everything comes from the cache


def test_ph_rejected_token_is_an_error_and_not_cached(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("PRODUCTHUNT_TOKEN", "bad")
    monkeypatch.setattr(http, "request", lambda *a, **k: http.Response(401, '{"error":"invalid_oauth_token"}'))
    with pytest.raises(RuntimeError, match="PRODUCTHUNT_TOKEN"):
        s0_producthunt.run(ws, argparse.Namespace(top_month=60, top_week=20))
    assert not any(ws.cache("producthunt").iterdir())


def test_ph_without_token_is_skipped(tmp_path, monkeypatch):
    from nichefinder import keys
    monkeypatch.delenv("PRODUCTHUNT_TOKEN", raising=False)
    with pytest.raises(keys.MissingKey):
        s0_producthunt.run(make_ws(tmp_path), argparse.Namespace(top_month=60, top_week=20))


# ---- Empire Flippers -------------------------------------------------------------

def listing(n: int, title: str, status: str = "Sold", mons: tuple[str, ...] = ("SaaS",)) -> dict:
    return {"listing_number": n, "public_title": title, "summary": f"{title} summary", "listing_status": status,
            "monetizations": [{"monetization": m} for m in mons], "niches": [{"niche": "Business"}, {"niche": "Technology"}],
            "customer_type": None, "country": "US", "average_monthly_net_profit": 4200, "average_monthly_gross_revenue": 9000,
            "listing_price": 160000, "listing_multiple": 38, "listing_multiple_type": "SDE", "first_made_money_at": "2019-01-01",
            "first_listed_at": "2026-05-18T11:00:00.000Z", "days_on_marketplace": 12, "updated_at": "2026-11-01T00:00:00.000Z",
            "mrr": None, "churn_percent": None, "metrics": [{"month": "2026-01-01"}]}


def test_ef_trim_flattens_tags_and_builds_url():
    row = s0_empireflippers.trim(listing(97871, "$9K Per Month SaaS Business in the Business Niche"))
    assert row["monetizations"] == "SaaS" and row["niches"] == "Business|Technology"
    assert row["monthly_net_profit"] == 4200 and row["mrr"] == "" and "metrics" not in row
    assert row["url"] == "https://empireflippers.com/listing/97871/" and row["kind"] == "software"
    assert s0_empireflippers.kind("Subscription|SaaS") == "software" and s0_empireflippers.kind("Info Product") == "digital"
    assert s0_empireflippers.kind("Amazon FBA|eCommerce") == "other" and s0_empireflippers.kind("") == "other"


def test_ef_run_walks_pages_dedupes_and_caches(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(s0_empireflippers.time, "sleep", lambda s: None)
    pages = {1: [listing(1, "Invoicing SaaS"), listing(2, "Kennel app", "For Sale", ("Application",))],
             2: [listing(2, "Kennel app", "For Sale", ("Application",)), listing(3, "Pet blog", mons=("Display Advertising",))]}

    def api(url, **kw):
        p = int(url.rsplit("page=", 1)[1])
        return http.Response(200, json.dumps({"data": {"listings": pages[p], "count": 4, "pages": 2, "page": p, "limit": 100}, "errors": []}))

    monkeypatch.setattr(http, "request", api)
    s0_empireflippers.run(ws, argparse.Namespace())
    rows = read_csv(ws.raw("ef_listings.csv"))
    assert [r["listing_number"] for r in rows] == ["1", "2", "3"]
    assert rows[1]["listing_status"] == "For Sale" and rows[2]["monetizations"] == "Display Advertising"
    assert (ws.cache("empireflippers") / "ef_2026-11_l100_p1.json").is_file()   # the run month is in the cache key
    monkeypatch.setattr(http, "request", lambda *a, **k: pytest.fail("network call"))
    s0_empireflippers.run(ws, argparse.Namespace())
