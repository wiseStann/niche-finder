"""Offline tests for the BetaList, Product Radar, Kickstarter and Hacker News stages and their shared helpers."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
from pathlib import Path

import yaml

from nichefinder import http, niches
from nichefinder.stages import s0_betalist, s0_kickstarter, s0_merge, s0_productradar, s5_deals, s8_hn_hiring, s8_hn_mentions
from nichefinder.workspace import Workspace

DAY = int(dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc).timestamp())


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us"], "as_of": "2026-11-17"}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "deal_keywords.yaml").write_text(yaml.safe_dump({
        "invoicing": r"\binvoic(e|ing)\b",
        "pets": {"re": r"\b(dog grooming|kennel)\b", "not": r"\bdocker\b"},
    }), encoding="utf-8")
    (tmp_path / "config" / "coverage_keywords.yaml").write_text(yaml.safe_dump({
        "invoicing": ["invoice", "счет"], "pets": ["dog grooming"], "tattoo": ["tattoo", "тату"],
    }, allow_unicode=True), encoding="utf-8")
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"A": [{"id": "invoicing"}, {"id": "tattoo"}]}), encoding="utf-8")
    return Workspace(tmp_path)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# ---- shared helpers ----------------------------------------------------------

def test_text_matchers_regex_not_and_fallback(tmp_path):
    ws = make_ws(tmp_path)
    mx = niches.text_matchers(ws)
    assert set(mx) == {"invoicing", "pets", "tattoo"}           # deal regexes + shortlisted fallback
    assert mx["invoicing"]("Simple invoicing for freelancers")
    assert not mx["invoicing"]("Invoices are boring")             # the regex, not the coverage phrase
    assert mx["pets"]("Kennel booking app") and not mx["pets"]("Kennel: a docker image scanner")
    assert mx["tattoo"]("Tattoo studio booking")                  # fallback to coverage phrases
    ru = niches.text_matchers(ws, with_coverage=True)
    assert ru["invoicing"]("Выставляйте счета клиентам") and not mx["invoicing"]("Выставляйте счета клиентам")
    assert ru["tattoo"]("Запись в тату-салон")


def test_download_streams_to_file_and_skips_existing(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 3_000_000)
    dst = tmp_path / "cache" / "dump.bin"
    assert http.download(src.as_uri(), dst, progress=False) == dst
    assert dst.read_bytes() == src.read_bytes()
    assert not (tmp_path / "cache" / "dump.bin.part").exists()
    src.write_bytes(b"changed")
    http.download(src.as_uri(), dst, progress=False)              # an existing file is the cache
    assert dst.stat().st_size == 3_000_000


# ---- BetaList ----------------------------------------------------------------

BETALIST_PAGE = f"""
<div data-duplicate-id="day_{DAY + 86400}"><strong>Sunday</strong> November 15th</div>
<div class="relative startup-row">
  <a class="absolute inset-0" href="/startups/inkly"></a>
  <span class="name">Inkly <a href="/testflight">TESTFLIGHT</a></span>
  <span class="tagline">Booking &amp; deposits for tattoo studios</span>
  <form action="/startups/inkly/follow"><span class="heart"><svg></svg></span></form>
</div>
<div data-duplicate-id="day_{DAY}"><strong>Saturday</strong> November 14th</div>
<div class="relative startup-row">
  <a class="absolute inset-0" href="/startups/billo"></a>
  <span class="name">Billo</span><span class="tagline">Invoicing for plumbers</span>
</div>
"""


def test_betalist_parse_page():
    rows = s0_betalist.parse_page(BETALIST_PAGE)
    assert [(r["name"], r["slug"], r["date"]) for r in rows] == [("Inkly", "inkly", "2026-11-15"), ("Billo", "billo", "2026-11-14")]
    assert rows[0]["tagline"] == "Booking & deposits for tattoo studios"
    assert rows[1]["url"] == "https://betalist.com/startups/billo"


# ---- Product Radar -----------------------------------------------------------

PR_CARD = """<time class="products__period">Октябрь 2026</time>
<article class="products__item card"><a class="product-bg-link" href="https://productradar.ru/product/schetovod/"></a>
<div class="card__body"><h2 class="card__title"><a href="https://productradar.ru/product/schetovod/"> Счетовод </a></h2>
<p class="card__description"> Счета и акты для самозанятых </p></div>
<div class="card__footer"><a class="card__comments" href="https://productradar.ru/product/schetovod/#comments-top"> 12 </a>
<ul class="card__categories categories"><li><a href="https://productradar.ru/category/seeking-investors/?groupby=week">Ищу инвестиции</a></li>
<li><a href="https://productradar.ru/category/finansy/">Финансы</a></li></ul></div>
<button class="upvote" data-votes="87" data-id="1"></button></article>"""


def test_productradar_parse_cards_and_months():
    [c] = s0_productradar.parse_cards(PR_CARD)
    assert (c["name"], c["slug"], c["votes"], c["comments"]) == ("Счетовод", "schetovod", "87", "12")
    assert c["categories"] == "Финансы" and c["asks"] == "investors"
    assert s0_productradar.header_month(PR_CARD) == "2026-10"
    assert s0_productradar.header_month("<time>23.11.2026</time>") == ""
    assert s0_productradar.shift_month(2026, 1, 1) == "2025-12"


# ---- Kickstarter -------------------------------------------------------------

def ks_record(pid, launched, state, pledged, backers=300, sub="Hardware", parent="Technology", name="Gadget", blurb="A gadget"):
    ts = int(dt.datetime.fromisoformat(launched).replace(tzinfo=dt.timezone.utc).timestamp())
    return {"data": {"id": pid, "name": name, "blurb": blurb, "state": state, "goal": 1000, "static_usd_rate": 1.1,
                     "usd_pledged": str(pledged), "backers_count": backers, "launched_at": ts, "deadline": ts + 30 * 86400,
                     "country": "US", "category": {"name": sub, "parent_name": parent},
                     "urls": {"web": {"project": f"https://www.kickstarter.com/projects/x/{pid}"}}}}


def test_kickstarter_dump_parsing_and_stats(tmp_path):
    page = '<li>2026-11-16 [<a href=https://s3.amazonaws.com/weruns/forfun/Kickstarter/Kickstarter_2026-11-16T07_32_37_797Z.json.gz>JSON</a>]'
    assert list(s0_kickstarter.dumps(page)) == ["2026-11-16"]
    path = tmp_path / "dump.json.gz"
    recs = [ks_record(1, "2026-03-01", "successful", 5000), ks_record(1, "2026-03-01", "successful", 5000),   # duplicate id
            ks_record(2, "2026-04-01", "failed", 100), ks_record(3, "2026-11-10", "live", 900),
            ks_record(4, "2025-06-01", "successful", 800), ks_record(5, "2023-01-01", "successful", 1)]           # outside 24 months
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(r) for r in recs) + "\nnot json\n")
    rows, lines, bad = s0_kickstarter.read_dump(path, "2024-11-17", "2026-11-17")
    assert (len(rows), lines, bad) == (4, 7, 1)
    r1 = next(r for r in rows if r["id"] == 1)
    assert r1["goal_usd"] == 1100 and r1["category"] == "Technology" and r1["launched"] == "2026-03-01"
    [s] = s0_kickstarter.category_stats(rows, dt.date(2026, 11, 17))
    assert (s["launched_12m"], s["launched_prev12m"], s["finished_12m"], s["successful_12m"]) == (3, 1, 2, 1)
    assert s["success_rate_12m"] == 0.5 and s["pledged_usd_12m"] == 5000 and s["top_project"] == "Gadget"


# ---- Hacker News -------------------------------------------------------------

def test_hn_trend_rule_and_hiring_posting():
    assert s8_hn_mentions.hn_trend(4, 5) == "NA"
    assert s8_hn_mentions.hn_trend(15, 10) == "UP"
    assert s8_hn_mentions.hn_trend(8, 10) == "DOWN"
    assert s8_hn_mentions.hn_trend(10, 10) == "FLAT"
    assert s8_hn_mentions.kind(["story", "show_hn"]) == "show" and s8_hn_mentions.kind(["story", "ask_hn"]) == "ask"
    p = s8_hn_hiring.posting({"id": 7, "text": "Acme Invoicing | Backend Engineer | REMOTE<p>We build invoic&#x2F;ing tools."}, "2026-11")
    assert p["company"] == "Acme Invoicing" and p["headline"].startswith("Acme Invoicing | Backend")
    assert "invoic/ing" in p["text"] and p["url"].endswith("id=7")
    assert s8_hn_hiring.posting({"id": 8, "text": None}, "2026-11") is None
    assert s8_hn_hiring.TITLE.match("Ask HN: Who is hiring? (November 2026)").groups() == ("November", "2026")


# ---- merge and deals over the new corpora -------------------------------------

def test_merge_and_deals_use_new_sources(tmp_path):
    ws = make_ws(tmp_path)
    write_csv(ws.raw("betalist.csv"), [
        {"name": "Billo", "slug": "billo", "tagline": "Invoicing for plumbers", "date": "2026-10-01", "url": "u1"},
        {"name": "Old", "slug": "old", "tagline": "Invoicing, years ago", "date": "2025-01-01", "url": "u2"}])
    write_csv(ws.raw("productradar.csv"), [
        {"name": "Счетовод", "slug": "s", "description": "Счета для самозанятых", "month": "2026-10", "votes": "87",
         "comments": "12", "categories": "Финансы", "asks": "investors", "url": "u3"}])
    write_csv(ws.raw("kickstarter_projects.csv"), [
        {"id": "1", "name": "Tattoo kit", "blurb": "A tattoo kit", "category": "Art", "subcategory": "Tattoo", "state": "successful",
         "goal_usd": "1000", "pledged_usd": "25000", "backers": "400", "launched": "2026-05-01", "deadline": "2026-06-01", "country": "US", "url": "u4"},
        {"id": "2", "name": "Tiny", "blurb": "tattoo stickers", "category": "Art", "subcategory": "Tattoo", "state": "failed",
         "goal_usd": "1000", "pledged_usd": "10", "backers": "2", "launched": "2026-05-01", "deadline": "2026-06-01", "country": "US", "url": "u5"}])
    ef = {"listing_number": "", "public_title": "", "summary": "", "listing_status": "Sold", "monetizations": "", "niches": "Business",
          "customer_type": "", "country": "US", "monthly_net_profit": "", "monthly_gross_revenue": "", "listing_price": "160000",
          "listing_multiple": "", "multiple_type": "SDE", "first_made_money_at": "", "first_listed_at": "2024-03-18T00:00:00Z",
          "days_on_marketplace": "", "updated_at": "", "mrr": "", "churn_percent": "", "kind": "", "url": "u6"}
    write_csv(ws.raw("ef_listings.csv"), [
        {**ef, "listing_number": "1", "public_title": "$9K Per Month SaaS Business", "summary": "Invoicing software for agencies",
         "monetizations": "SaaS", "monthly_net_profit": "4000", "listing_multiple": "30", "kind": "software", "customer_type": "B2B"},
        {**ef, "listing_number": "2", "public_title": "$5K Per Month SaaS Business", "summary": "Invoicing plugin", "listing_status": "For Sale",
         "monetizations": "SaaS", "monthly_net_profit": "2000", "listing_multiple": "40", "kind": "software"},
        {**ef, "listing_number": "3", "public_title": "$90K Per Month Amazon FBA Business", "summary": "Invoices handled by an accountant; invoicing",
         "monetizations": "Amazon FBA", "monthly_net_profit": "9000", "listing_multiple": "35", "kind": "other"},
        {**ef, "listing_number": "4", "public_title": "$3K Per Month Info Product Business", "summary": "A course on invoicing",
         "monetizations": "Info Product", "monthly_net_profit": "1500", "listing_multiple": "28", "kind": "digital"}])
    s0_merge.run(ws, argparse.Namespace())
    uni = list(csv.DictReader(open(ws.out("universe.csv"), encoding="utf-8")))
    assert sorted(r["source"] for r in uni) == ["betalist", "betalist", "ef:digital", "ef:software", "ef:software", "kickstarter:Art", "productradar"]
    # the failed Kickstarter project and the Amazon FBA listing are left out
    assert next(r for r in uni if r["source"] == "ef:software")["side"] == "b2b"
    assert next(r for r in uni if r["source"] == "productradar")["geo"] == "ru"
    s5_deals.run(ws, argparse.Namespace())
    deals = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("deals.csv"), encoding="utf-8"))}
    assert deals["invoicing"]["betalist_12m"] == "1"            # the 2025 launch is outside 12 months
    assert deals["invoicing"]["productradar_12m"] == "1"        # matched through the Russian coverage phrase
    assert (deals["tattoo"]["kickstarter_12m"], deals["tattoo"]["kickstarter_success_12m"], deals["tattoo"]["kickstarter_pledged_12m"]) == ("2", "1", "25000")
    # Empire Flippers: software listings only (the FBA and info-product listings also say "invoicing")
    assert (deals["invoicing"]["ef_software"], deals["invoicing"]["ef_software_sold"]) == ("2", "1")
    assert (deals["invoicing"]["ef_median_profit"], deals["invoicing"]["ef_median_multiple"]) == ("3000", "35")
    assert deals["tattoo"]["ef_software"] == "0" and deals["tattoo"]["ef_median_profit"] == ""
    assert "flippa_listings" not in deals["invoicing"]
