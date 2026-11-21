"""Offline tests for s0_trustmrr (RSC payload parsing, API rows, merge, both modes) and the TrustMRR columns of s5_deals."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pytest
import yaml

from nichefinder import http, keys
from nichefinder.stages import s0_trustmrr, s5_deals
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us"], "as_of": "2026-11-21"}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "deal_keywords.yaml").write_text(yaml.safe_dump({"invoicing": r"\binvoic(e|ing)\b"}), encoding="utf-8")
    (tmp_path / "config" / "coverage_keywords.yaml").write_text(yaml.safe_dump({"tattoo": ["tattoo"]}), encoding="utf-8")
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"A": [{"id": "invoicing"}, {"id": "tattoo"}]}), encoding="utf-8")
    return Workspace(tmp_path)


def push(payload: str) -> str:
    """One Next.js flight chunk as it appears in the HTML."""
    return f'<script>self.__next_f.push([1,{json.dumps(payload)}])</script>'


START = {"_id": "a1", "name": "Billo", "icon": None, "description": "Invoicing for\nplumbers", "currentTotalRevenue": 54831.45,
         "currentMrr": 1758.3, "currentLast30DaysRevenue": 2100.6, "slug": "billo", "onSale": True, "askingPrice": 60000,
         "cachedGrowth30d": 12.345, "founder": {"_id": "f1", "name": "Ann"}}
OTHER = {"_id": "b2", "name": "Inkly", "description": "Tattoo studio booking", "currentLast30DaysRevenue": 0, "currentMrr": 0,
         "slug": "inkly", "onSale": False}


def page(*objs) -> str:
    body = "5:[\"$\",\"$L23\",null,{\"initialStartups\":" + json.dumps(list(objs), separators=(",", ":")) + "}]\n"
    half = len(body) // 2
    # a payload split across two chunks, as Next.js does, plus an unrelated object with _id but no revenue
    return "<html>" + push(body[:half]) + push(body[half:]) + push('6:{"_id":"x","slug":"s","name":"not a startup"}') + "</html>"


def test_rsc_payload_and_startups():
    found = s0_trustmrr.rsc_startups(s0_trustmrr.rsc_payload(page(START, OTHER)))
    assert [o["slug"] for o in found] == ["billo", "inkly"]
    r = s0_trustmrr.row_from_rsc(found[0], "category", "saas")
    assert (r["revenue_30d"], r["mrr"], r["revenue_total"], r["growth_30d"]) == (2101, 1758, 54831, 12.3)
    assert (r["on_sale"], r["asking_price"], r["category"], r["description"]) == (1, 60000, "saas", "Invoicing for plumbers")
    assert r["url"] == "https://trustmrr.com/startup/billo"
    assert s0_trustmrr.row_from_rsc(found[1], "home")["on_sale"] == 0


def test_api_rows_cents_vs_dollars_and_merge():
    o = {"name": "Billo", "slug": "billo", "description": "Invoices", "category": "Health & Fitness", "targetAudience": "B2B",
         "country": "US", "foundedDate": "2024-03-01T00:00:00.000Z", "revenue": {"last30Days": 425000, "mrr": 180000, "total": 9800000},
         "askingPrice": 5000000, "growth30d": 24.04, "multiple": 0.98, "onSale": True}
    v1 = s0_trustmrr.row_from_api(o, "api", 100.0)                 # /api/v1 money is in cents
    assert (v1["revenue_30d"], v1["mrr"], v1["revenue_total"], v1["asking_price"]) == (4250, 1800, 98000, 50000)
    assert (v1["category"], v1["target_audience"], v1["founded"], v1["growth_30d"]) == ("health-fitness", "b2b", "2024-03-01", 24.0)
    ai = s0_trustmrr.row_from_api(o, "ai_market", 1.0)             # the public /api/ai endpoints use dollars
    assert ai["mrr"] == 180000
    rsc = s0_trustmrr.row_from_rsc(START, "category", "saas")
    merged = s0_trustmrr.merge([ai, rsc, s0_trustmrr.row_from_rsc(START, "category", "fintech")])
    m = merged["billo"]
    assert m["founded"] == "2024-03-01" and m["mrr"] == 180000      # the first non-empty value wins
    assert m["category"] == "health-fitness|saas|fintech" and m["source"] == "ai_market|category"


def test_public_mode_writes_csv(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.delenv("TRUSTMRR_API_KEY", raising=False)
    pages = {"/": page(START), "/category": '<a href="/category/saas">SaaS</a><a href="/category/legal">Legal</a>',
             "/category/saas": page(START, OTHER), "/category/legal": page()}
    calls = []

    def fake_text(url, **kw):
        calls.append(url)
        return pages[url.replace("https://trustmrr.com", "")]

    def fake_json(url, **kw):
        calls.append(url)
        if url.endswith("/api/ai/discovery"):
            return {"recentlyAddedStartups": [{"name": "New", "slug": "new", "revenue": {"last30Days": 5, "mrr": 0, "total": 5}}],
                    "fastestGrowingStartups": []}
        return {"metricAccess": {}, "recentlyListedStartups": [], "bestDeals": []}

    monkeypatch.setattr(http, "get_text", fake_text)
    monkeypatch.setattr(http, "get_json", fake_json)
    s0_trustmrr.run(ws, argparse.Namespace(mode="auto", min_revenue=100, max_pages=5))
    rows = list(csv.DictReader(open(ws.raw("trustmrr.csv"), encoding="utf-8")))
    assert [r["slug"] for r in rows] == ["billo", "new", "inkly"]   # sorted by revenue of the last 30 days
    assert rows[0]["category"] == "saas" and rows[0]["source"] == "home|category"
    assert not any("/startups/page" in u or "/startup/" in u for u in calls)   # bounded: no directory walk, no detail pages


def test_api_mode_pages_until_has_more_false(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setenv("TRUSTMRR_API_KEY", "tmrr_test")
    seen = []

    def fake_json(url, **kw):
        seen.append((url, kw["headers"]["Authorization"]))
        pg = int(url.split("page=")[1].split("&")[0])
        data = [{"name": f"S{pg}", "slug": f"s{pg}", "revenue": {"last30Days": 100000 * pg, "mrr": 0, "total": 0}}]
        return {"data": data, "meta": {"total": 2, "page": pg, "limit": 10, "hasMore": pg < 2}}

    monkeypatch.setattr(http, "get_json", fake_json)
    s0_trustmrr.run(ws, argparse.Namespace(mode="auto", min_revenue=100, max_pages=10))
    assert len(seen) == 2 and "minRevenue=10000" in seen[0][0] and seen[0][1] == "Bearer tmrr_test"
    assert "tmrr_test" not in seen[0][0]                               # the key never goes into the URL
    rows = list(csv.DictReader(open(ws.raw("trustmrr.csv"), encoding="utf-8")))
    assert [(r["slug"], r["revenue_30d"]) for r in rows] == [("s2", "2000"), ("s1", "1000")]


def test_api_mode_without_key_is_skipped(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.delenv("TRUSTMRR_API_KEY", raising=False)
    with pytest.raises(keys.MissingKey):
        s0_trustmrr.run(ws, argparse.Namespace(mode="api", min_revenue=100, max_pages=1))


def test_deals_trustmrr_columns(tmp_path):
    ws = make_ws(tmp_path)
    rows = [{"slug": "billo", "name": "Billo", "description": "Invoicing for plumbers", "revenue_30d": "2100", "mrr": "1800",
             "on_sale": "1", "asking_price": "60000"},
            {"slug": "inv2", "name": "Inv2", "description": "Simple invoicing", "revenue_30d": "500", "mrr": "200",
             "on_sale": "0", "asking_price": ""},
            {"slug": "dead", "name": "Dead", "description": "Invoicing, no revenue", "revenue_30d": "0", "mrr": "0",
             "on_sale": "", "asking_price": ""},
            {"slug": "inkly", "name": "Inkly", "description": "Tattoo studio booking", "revenue_30d": "90", "mrr": "",
             "on_sale": "", "asking_price": ""}]
    path = ws.raw("trustmrr.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s5_deals.run(ws, argparse.Namespace())
    deals = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("deals.csv"), encoding="utf-8"))}
    inv = deals["invoicing"]
    assert (inv["trustmrr_n"], inv["trustmrr_mrr_sum"], inv["trustmrr_mrr_median"]) == ("2", "2000", "1000")   # zero-revenue row left out
    assert (inv["trustmrr_rev30_sum"], inv["trustmrr_for_sale"]) == ("2600", "1")
    assert (deals["tattoo"]["trustmrr_n"], deals["tattoo"]["trustmrr_mrr_median"]) == ("1", "0")
    matches = [r for r in csv.DictReader(open(ws.out("deals_matches.csv"), encoding="utf-8")) if r["source"] == "trustmrr"]
    assert [m["name"] for m in matches if m["niche_id"] == "invoicing"] == ["Billo", "Inv2"]    # by revenue, high first
    assert matches[0]["extra"] == "$1,800 MRR, $2,100/30d, for sale $60,000"
