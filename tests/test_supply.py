"""Offline tests for the S5 supply fixes: the LLM product check (appfit) and its use in s5_appstore, missing directory
data in s5_merge, and Capterra block pages."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import yaml

from nichefinder import appfit, http, keys, llm
from nichefinder.stages import s5_appstore, s5_capterra, s5_merge, s5_pricing_b2b, s6_passports, s8_gplay_filter
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path, side: str = "b2c") -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us"], "as_of": "2026-11-21"}), encoding="utf-8")
    base = {"who": "people", "task": "do things", "product": "app", "geo": "global", "tier": "A"}
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "budget", "name": "Budget apps", "side": side, **base},
        {"id": "crm", "name": "Tiny CRM", "side": "b2b-smb", **base},
    ]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "budget": {"en": [{"q": "budget app", "i": "category", "anchor": True}]},
        "crm": {"en": [{"q": "tiny crm", "i": "category", "anchor": True}]}}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": ["budget", "crm"]}), encoding="utf-8")
    return Workspace(tmp_path)


def fake_fit(calls):
    """Every listed app fits unless its name has "Game" in it; records each request's numbered lines."""
    def chat(ws, messages, **kw):
        lines = [x for x in messages[1]["content"].split("\n") if re.match(r"\d+: ", x)]
        calls.append(lines)
        return {"apps": [{"k": int(x.split(":")[0]), "fit": "no" if "Game" in x else "yes", "why": "w"} for x in lines]}, False, None
    return chat


def test_appfit_batches_and_numbers_each_batch_from_one(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    calls = []
    monkeypatch.setattr(llm, "chat_json", fake_fit(calls))
    apps = [{"app": f"Game {i}" if i % 2 else f"App {i}", "developer": "D", "genre": "G"} for i in range(130)]
    got = appfit.check(ws, {"id": "budget", "who": "people"}, apps)
    assert [len(c) for c in calls] == [60, 60, 10] and calls[1][0].startswith("1: ")
    assert got[0] == ("yes", "w") and got[1] == ("no", "w") and len(got) == 130
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"apps": [{"k": 1, "fit": "yes", "why": "ok"}]}, False, None))
    assert appfit.check(ws, {}, apps[:2]) == [("yes", "ok"), ("", "no answer from the model")]


def itunes(*apps):
    return {"results": [{"trackId": tid, "trackName": name, "sellerName": "S", "userRatingCount": n, "averageUserRating": 4.5,
                         "primaryGenreName": "Finance"} for tid, name, n in apps]}


def test_appstore_product_check_drops_non_products_and_include_wins(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    results = {"budget app": itunes((1, "Money", 900), (2, "Cookie Game", 90000), (3, "Coins", 300)),
               "tiny crm": itunes((4, "Leads", 50))}
    monkeypatch.setattr(s5_appstore, "search", lambda ws, q, country: results[q])
    monkeypatch.setattr(keys, "get", lambda name, *a, **k: "key" if name == "LLM_API_KEY" else None)
    calls = []
    monkeypatch.setattr(llm, "chat_json", fake_fit(calls))
    s5_appstore.run(ws, argparse.Namespace())
    rows = {r["track_id"]: r for r in csv.DictReader(open(ws.out("appstore_apps.csv"), encoding="utf-8"))}
    assert (rows["2"]["auto"], rows["2"]["fit"], rows["2"]["relevant"]) == ("1", "no", "0")   # top position, not a product
    assert (rows["1"]["relevant"], rows["3"]["relevant"]) == ("1", "1")
    assert calls[0][0].startswith("1: Cookie Game")   # candidates sorted by ratings
    assert "Dropped by the product check" in ws.out("appstore_review.md").read_text(encoding="utf-8")
    (tmp_path / "config" / "appstore_relevance.yaml").write_text(yaml.safe_dump({"budget": {"us": {"include": [2]}}}), encoding="utf-8")
    s5_appstore.run(ws, argparse.Namespace())
    rows = {r["track_id"]: r for r in csv.DictReader(open(ws.out("appstore_apps.csv"), encoding="utf-8"))}
    assert rows["2"]["relevant"] == "1"   # a manual include wins over the check
    # without a key the check is skipped and relevance is by position only
    monkeypatch.setattr(keys, "get", lambda name, *a, **k: None)
    (tmp_path / "config" / "appstore_relevance.yaml").unlink()
    s5_appstore.run(ws, argparse.Namespace())
    rows = {r["track_id"]: r for r in csv.DictReader(open(ws.out("appstore_apps.csv"), encoding="utf-8"))}
    assert (rows["2"]["fit"], rows["2"]["relevant"]) == ("", "1")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_merge_missing_directory_share_is_no_data_not_a_failed_gate(tmp_path):
    ws = make_ws(tmp_path, side="b2b-smb")
    # Capterra pages that did not parse: a row without a top-1 share, for both niches
    write_csv(ws.out("capterra_categories_stats.csv"), [
        {"niche_id": nid, "slug": "x-software", "products_total": "", "products_100plus": 0, "products_10plus": 0, "top1": "",
         "top1_share": "", "top3_share": "", "hhi": "", "generic_present": ""} for nid in ("budget", "crm")])
    write_csv(ws.out("appstore_metrics.csv"), [{"niche_id": "budget", "store": "us", "na": 0, "players_1k": 12, "players_10k": 3,
                                                "top1": "Money", "top1_share": 0.2, "top3_share": 0.4, "hhi": 0.1}])
    s5_merge.run(ws, argparse.Namespace())
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("supply_deep.csv"), encoding="utf-8"))}
    assert (rows["budget"]["supply_src"], rows["budget"]["gate_s5"]) == ("appstore", "PASS")   # falls back to the App Store
    assert (rows["crm"]["supply_src"], rows["crm"]["gate_s5"]) == ("na", "NA")                # no source: not FAIL:top1


BLOCK = "<!DOCTYPE html><html><head><title>Security Check</title></head><body>" + "x" * 40000 + "</body></html>"
REAL = '<html><script>{"numberOfItems":321}</script>' + "y" * 20000 + "</html>"


class Resp:
    def __init__(self, text):
        self.text = text


def test_capterra_block_pages_are_not_data_and_not_cached(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(s5_capterra.time, "sleep", lambda s: None)
    cached = ws.cache("capterra") / "x-software_p1.html"
    cached.write_text(BLOCK, encoding="utf-8")   # cached by an earlier version
    monkeypatch.setattr(http, "request", lambda *a, **k: Resp(BLOCK))
    assert s5_capterra.fetch(ws, "x-software", 1) == "" and not cached.exists()
    monkeypatch.setattr(http, "request", lambda *a, **k: Resp(REAL))
    assert s5_capterra.parse(s5_capterra.fetch(ws, "x-software", 1))[0] == 321 and cached.exists()


def listing(total: int, cards: list[tuple[str, int]]) -> str:
    """A category page that s5_capterra.parse reads: numberOfItems and cards of name, rating, (reviews)."""
    body = "".join(f"<h2>{name}</h2><b>4.5</b><i>(</i><i>{n:,}</i><i>)</i>" for name, n in cards)
    return f'<html><script>{{"numberOfItems":{total}}}</script>{body}' + "z" * 12000 + "</html>"


def capterra_site(monkeypatch, pages: dict[int, str]) -> list[str]:
    """Serve category pages by number (a missing page is a block page); returns the requested URLs."""
    asked = []

    def request(url, **kw):
        asked.append(url)
        page = int(url.rsplit("=", 1)[1]) if "?page=" in url else 1
        return Resp(pages.get(page, BLOCK))
    monkeypatch.setattr(http, "request", request)
    monkeypatch.setattr(s5_capterra.time, "sleep", lambda s: None)
    return asked


def capterra_ws(tmp_path: Path, brands: list[str] = ()) -> Workspace:
    ws = make_ws(tmp_path, side="b2b-smb")
    (tmp_path / "config" / "capterra_map.yaml").write_text(yaml.safe_dump({"crm": {"slugs": ["crm-software"]}}), encoding="utf-8")
    (tmp_path / "config" / "capterra_generic.yaml").write_text(yaml.safe_dump({"generic": ["Bigsuite", "Deputy"]}), encoding="utf-8")
    qs = [{"q": "tiny crm", "i": "category", "anchor": True}] + [{"q": b.lower(), "i": "brand", "b": b} for b in brands]
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({"crm": {"en": qs}}), encoding="utf-8")
    return ws


def stats_of(ws: Workspace) -> dict:
    return next(csv.DictReader(open(ws.out("capterra_categories_stats.csv"), encoding="utf-8")))


def test_capterra_category_cut_short_by_a_block_page_is_no_data(tmp_path, monkeypatch):
    ws = capterra_ws(tmp_path)
    # page 1 has the leaders; page 2 is a block page: the shares of 3 products out of 400 would be far too high
    capterra_site(monkeypatch, {1: listing(400, [("Ad", 0), ("Leads", 900), ("Pipes", 500), ("Deals", 300)])})
    s5_capterra.run(ws, argparse.Namespace())
    st = stats_of(ws)
    assert (st["complete"], st["pages"], st["stop"], st["products_seen"], st["products_total"]) == ("0", "1", "blocked p2", "4", "400")
    assert (st["top1"], st["top1_share"], st["top3_share"], st["products_100plus"], st["reviews_niche"]) == ("Leads", "", "", "", "")
    # the bounds settle nothing here: top-1 <= 53 % and only 3 players read, while unread products may hold 300 reviews each
    assert (st["top1_share_max"], st["products_100plus_min"], st["tail_reviews"]) == ("0.529", "3", "300")
    write_csv(ws.out("appstore_metrics.csv"), [{"niche_id": "crm", "store": "us", "na": 0, "players_1k": 9, "players_10k": 3,
                                                "top1": "Pocket CRM", "top1_share": 0.3, "top3_share": 0.6, "hhi": 0.2}])
    s5_merge.run(ws, argparse.Namespace())
    row = next(r for r in csv.DictReader(open(ws.out("supply_deep.csv"), encoding="utf-8")) if r["niche_id"] == "crm")
    assert (row["supply_src"], row["gate_s5"], row["cap_stop"], row["supply_partial"]) == ("appstore", "PASS", "blocked p2", "0")


def bound_row(**kw) -> dict:
    row = {"niche_id": "crm", "slug": "crm-software", "products_total": 700, "products_seen": 25, "complete": 0, "pages": 1,
           "stop": "blocked p2", "products_100plus": "", "products_10plus": "", "top1": "Leads", "top1_share": "",
           "top3_share": "", "hhi": "", "generic_present": "", "top1_share_max": 0.3, "products_100plus_min": 12, "tail_reviews": 150}
    return {**row, **kw}


def test_merge_settles_the_gate_from_the_bounds_of_an_incomplete_category(tmp_path):
    ws = make_ws(tmp_path, side="b2b-smb")
    write_csv(ws.out("appstore_metrics.csv"), [{"niche_id": "crm", "store": "us", "na": 0, "players_1k": 2, "players_10k": 1,
                                                "top1": "Pocket CRM", "top1_share": 0.9, "top3_share": 1, "hhi": 0.8}])
    cases = [({}, ("capterra", "PASS", "1")),                                            # top-1 can only fall, players only grow
             ({"products_100plus_min": 5, "tail_reviews": 40}, ("capterra", "FAIL:players", "1")),   # all 100+ products read
             ({"products_100plus_min": 5}, ("appstore", "FAIL:top1", "0")),                # unread products may still be players
             ({"top1_share_max": 0.7}, ("appstore", "FAIL:top1", "0"))]                    # the share may still fall below 50 %
    for kw, want in cases:
        write_csv(ws.out("capterra_categories_stats.csv"), [bound_row(**kw)])
        s5_merge.run(ws, argparse.Namespace())
        row = next(r for r in csv.DictReader(open(ws.out("supply_deep.csv"), encoding="utf-8")) if r["niche_id"] == "crm")
        assert (row["supply_src"], row["gate_s5"], row["supply_partial"]) == want, kw
        if want[2] == "1":   # players and top-3 stay empty: the score gives them neutral half-credit
            assert (row["supply_players"], row["supply_top3_share"], row["supply_top1"]) == ("", "", "Leads")


def test_capterra_page_one_ending_without_reviews_completes_the_category(tmp_path, monkeypatch):
    ws = capterra_ws(tmp_path)
    cards = [("Ad", 40), ("Leads", 90), ("Pipes", 30)] + [(f"P{i}", 0) for i in range(22)] + [("Related", 15)]
    asked = capterra_site(monkeypatch, {1: listing(51, cards)})
    s5_capterra.run(ws, argparse.Namespace())
    st = stats_of(ws)
    assert len(asked) == 1 and (st["complete"], st["stop"], st["products_100plus"]) == ("1", "end", "0")


def test_capterra_paging_stops_at_the_reviewless_tail_and_keeps_own_brands(tmp_path, monkeypatch):
    ws = capterra_ws(tmp_path, brands=["Deputy"])
    asked = capterra_site(monkeypatch, {
        1: listing(90, [("Ad", 0), ("Bigsuite", 5000), ("Deputy", 1200), ("Leads", 600), ("Pipes", 400)]),
        2: listing(90, [("Deals", 150), ("Tiny", 20), ("Nothing", 0)]),   # ends in a product without reviews
    })
    s5_capterra.run(ws, argparse.Namespace())
    assert len(asked) == 2   # page 3 would only hold products without reviews: not requested
    st = stats_of(ws)
    assert (st["complete"], st["stop"], st["pages"]) == ("1", "end", "2")
    # Bigsuite is a horizontal substitute; Deputy is generic elsewhere but a brand of this niche, so it stays a player
    assert (st["generic_present"], st["generic_kept"], st["top1"]) == ("Bigsuite", "Deputy", "Deputy")
    assert st["top1_share"] == str(round(1200 / (1200 + 600 + 400 + 150 + 20), 3)) and st["products_100plus"] == "4"
    prods = {r["product"]: r["generic"] for r in csv.DictReader(open(ws.out("capterra_products.csv"), encoding="utf-8"))}
    assert (prods["Bigsuite"], prods["Deputy"]) == ("1", "0")   # s5_pricing_b2b prices the niche's own brands too


def test_capterra_own_brand_match_is_a_name_not_a_substring():
    assert s5_capterra.is_own("Wix Studio", {"wix"}) and s5_capterra.is_own("When I Work", {"when i work"})
    assert not s5_capterra.is_own("Box", {"warmup inbox"}) and not s5_capterra.is_own("Loom", {"bloomerang"})
    assert not s5_capterra.is_own("Wixel", {"wix"})


def score_inputs(tmp_path: Path, ws: Workspace, sides: dict, **supply) -> None:
    """score.yaml, metrics_quick.csv and supply_deep.csv for s6_score; `sides` maps niche id -> side."""
    (tmp_path / "config" / "score.yaml").write_text(yaml.safe_dump({
        "cpc_band": {"en": [0.5, 8.0], "en_b2b": [1.0, 1000.0]}, "cpc_below": 0.3, "cpc_above": 0.6,
        "trend_up": 0.05, "trend_down": -0.05}), encoding="utf-8")
    write_csv(ws.out("metrics_quick.csv"), [{"id": nid, "us_yoy": 0.1, "us_momentum": 1.0, "us_cagr_3y": 0.05} for nid in sides])
    base = {"tier": "A", "geo": "global", "demand_us": 1000, "demand_2023": 900, "gates_s3": "", "trend_kp": "FLAT",
            "trend_gt": "FLAT", "comp_idx": 50, "tinyseed": 0, "ph_12m": 1, "yc": 0, "topgross_us": 0, "cpc": 5, "hhi_brand": 0.3,
            "b2b_price_public": 0.5, "b2b_under100": 0.5, "b2c_with_monthly": 0, "b2c_n": 0, "expertise_flag": 0,
            "b2c_median_monthly": "", "b2b_median_monthly": 60, "gate_s5": "NA:proxy", "supply_src": "capterra",
            "supply_players": 3, "supply_top1": "Big", "supply_top1_share": 0.6, "supply_top3_share": 0.8, **supply}
    write_csv(ws.out("supply_deep.csv"), [{"niche_id": nid, **base, "side": side} for nid, side in sides.items()])


def test_s5_manual_flag_only_with_a_manual_estimate(tmp_path):
    from nichefinder.stages import s6_score
    ws = make_ws(tmp_path, side="b2b-smb")
    (tmp_path / "config" / "overrides.yaml").write_text(yaml.safe_dump({"budget": {"supply_manual": "ten players, no leader"}}),
                                                       encoding="utf-8")
    score_inputs(tmp_path, ws, {"budget": "b2b-smb", "crm": "b2b-smb"})
    s6_score.run(ws, argparse.Namespace())
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("score_final.csv"), encoding="utf-8"))}
    assert (rows["budget"]["gate_s5"], rows["budget"]["flags"], rows["budget"]["gates_failed"]) == ("PASS*", "S5:manual", "")
    assert (rows["crm"]["gate_s5"], rows["crm"]["gates_failed"], rows["crm"]["verdict"]) == ("NA", "S5:unmeasured", "red")
    assert "S5:manual" not in rows["crm"]["flags"]   # no manual estimate: the flag would read "manual estimate" in passports
    assert rows["budget"]["s_frag"] == rows["crm"]["s_frag"]   # both get the neutral half-credit for players / top-3



def test_second_platform_rule_only_for_consumer_niches(tmp_path):
    from nichefinder.stages import s6_score
    ws = make_ws(tmp_path)
    score_inputs(tmp_path, ws, {"budget": "b2c", "crm": "b2b-smb"}, gate_s5="FAIL:top1", supply_src="appstore")
    # Google Play US: leader at 30 %, 10 apps above 100k installs, for both niches
    write_csv(ws.out("offsearch.csv"), [{"niche_id": nid, "gp_us_top1_share": 0.3, "gp_us_players_100k": 10} for nid in ("budget", "crm")])
    s6_score.run(ws, argparse.Namespace())
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("score_final.csv"), encoding="utf-8"))}
    assert (rows["budget"]["gate_s5"], rows["budget"]["flags"], rows["budget"]["gates_failed"]) == ("PASS:android", "S5:android", "")
    assert (rows["crm"]["gate_s5"], rows["crm"]["gates_failed"], rows["crm"]["verdict"]) == ("FAIL:top1", "S5:top1", "red")


def test_gplay_filter_product_check_frees_places_and_keep_wins(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (tmp_path / "config" / "deal_keywords.yaml").write_text(yaml.safe_dump({"budget": "budget|money"}), encoding="utf-8")
    (tmp_path / "config" / "coverage_keywords.yaml").write_text(yaml.safe_dump({}), encoding="utf-8")
    monkeypatch.setattr(s8_gplay_filter, "MAX_APPS", 2)
    search = [{"niche_id": "budget", "country": "us", "query": "budget app", "pos": pos, "appId": aid, "title": title, "developer": "D",
               "score": 4.5, "priceText": "", "free": "true", "summary": summary}
              for pos, aid, title, summary in [(1, "g.cookie", "Money Game", "idle budget tycoon"), (2, "a.one", "Budget One", "track money"),
                                               (3, "a.two", "Budget Two", "plan money"), (4, "x.off", "Weather", "rain radar")]]
    write_csv(ws.out("gplay_search.csv"), search)
    monkeypatch.setattr(keys, "get", lambda name, *a, **k: "key" if name == "LLM_API_KEY" else None)
    calls = []
    monkeypatch.setattr(llm, "chat_json", fake_fit(calls))
    s8_gplay_filter.run(ws, argparse.Namespace())
    match = [r["appId"] for r in csv.DictReader(open(ws.out("gplay_match.csv"), encoding="utf-8"))]
    assert match == ["a.one", "a.two"]   # the game left, so the second real product got its place
    assert calls[0][0] == "1: Money Game | D | - | idle budget tycoon" and len(calls[0]) == 3   # the off-topic app is not a candidate
    fit = {r["appId"]: r for r in csv.DictReader(open(ws.out("gplay_fit.csv"), encoding="utf-8"))}
    assert (fit["g.cookie"]["fit"], fit["g.cookie"]["by"]) == ("no", "llm")
    (tmp_path / "config" / "gplay_keep.yaml").write_text(yaml.safe_dump({"budget": ["g.cookie"]}), encoding="utf-8")
    s8_gplay_filter.run(ws, argparse.Namespace())
    match = [r["appId"] for r in csv.DictReader(open(ws.out("gplay_match.csv"), encoding="utf-8"))]
    assert match == ["g.cookie", "a.one"]   # a manual keep wins over the check
    monkeypatch.setattr(keys, "get", lambda name, *a, **k: None)
    (tmp_path / "config" / "gplay_keep.yaml").unlink()
    s8_gplay_filter.run(ws, argparse.Namespace())
    match = [r["appId"] for r in csv.DictReader(open(ws.out("gplay_match.csv"), encoding="utf-8"))]
    assert match == ["g.cookie", "a.one"]   # without a key: regex and position only


def test_getapp_block_page_stops_b2b_pricing_without_output(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, side="b2b-smb")
    (tmp_path / "config" / "capterra_map.yaml").write_text(yaml.safe_dump({"crm": {"slugs": ["crm-software"]}}), encoding="utf-8")
    (tmp_path / "config" / "getapp_categories.yaml").write_text(yaml.safe_dump({"crm": "customer-management-software"}), encoding="utf-8")
    write_csv(ws.out("capterra_products.csv"), [{"slug": "crm-software", "product": "Leads", "reviews": 500, "generic": "0"}])
    calls = []
    monkeypatch.setattr(s5_pricing_b2b.time, "sleep", lambda s: None)
    monkeypatch.setattr(http, "request", lambda *a, **k: calls.append(a[0]) or Resp(BLOCK))
    s5_pricing_b2b.run(ws, argparse.Namespace(agg=False))
    assert len(calls) == 1   # no retries: the first block page stops the stage
    assert not ws.out("pricing_b2b.csv").exists() and not ws.out("pricing_b2b_niche.csv").exists()
    assert not any(ws.cache("getapp").iterdir())


def test_passport_asks_for_a_manual_oligopoly_check_in_b2b_niches_that_are_not_red():
    cats = [{"slug": "website-builder-software", "complete": "1", "top3_share": "0.71"},
            {"slug": "landing-page-software", "complete": "0", "top3_share": ""}]
    lines = s6_passports.oligopoly_lines("b2b-smb", "green", cats)
    assert lines[0].startswith("**Oligopoly check (manual).**")
    assert "Capterra `website-builder-software` top-3 = 71%" in lines[0] and "landing-page" not in lines[0]   # no shares when incomplete
    assert "top-3" not in s6_passports.oligopoly_lines("b2b", "yellow", cats[1:])[0]
    assert s6_passports.oligopoly_lines("b2b", "red", cats) == []
    assert s6_passports.oligopoly_lines("b2c", "green", cats) == [] and s6_passports.oligopoly_lines("prosumer", "green", cats) == []


def with_pricing(page: str, products: list[tuple[str, dict]]) -> str:
    """Add the Next.js page data with one CapterraProduct per (name, pricing) to a category page."""
    data = json.dumps({"items": [{"__typename": "CapterraProduct", "name": n, "slug": n.lower(), "reviewSummary": {"totalReviews": 1},
                                  "pricing": {"__typename": "ProductPricing", **pr}} for n, pr in products]}, separators=(",", ":"))
    push = "self.__next_f.push([1," + json.dumps("5:" + data) + "])"
    return page.replace("<html>", f"<html><script>{push}</script>", 1)


def plan(price, default=False, freq=2, ptype=1, model=1) -> dict:
    return {"__typename": "ProductPricingPlan", "startingPrice": price, "paymentFrequency": freq, "priceType": ptype,
            "pricingModel": model, "isDefault": default}


def test_capterra_pricing_reads_the_default_plan_and_keeps_unknown_apart():
    page = with_pricing(listing(9, [("Leads", 900)]), [
        ("Leads", {"hasFreeTrial": True, "hasFreeVersion": False, "plans": [plan(99), plan(29, default=True, model=2)]}),
        ("Pipes", {"hasFreeTrial": False, "hasFreeVersion": False, "plans": [plan(None, ptype=2), plan(None, default=True, ptype=2)]}),
        ("Deals", {"hasFreeTrial": True, "hasFreeVersion": True}),   # the common page variant: flags only
        ("Deals", {"hasFreeTrial": True, "hasFreeVersion": True, "plans": [plan(12, freq=3)]}),   # shown again with plans
        ("Tiny", {"hasFreeTrial": None})])
    pr = s5_capterra.pricing(page)
    assert pr["Leads"] == {"price": 29, "period": "per month", "model": "Per User", "no_pricing_info": 0, "free_trial": 1, "free_version": 0}
    assert (pr["Pipes"]["price"], pr["Pipes"]["no_pricing_info"]) == ("", 1)   # every plan says "contact the vendor"
    assert (pr["Deals"]["price"], pr["Deals"]["period"]) == (12, "per year")    # the copy with plans wins
    assert (pr["Tiny"]["price"], pr["Tiny"]["no_pricing_info"], pr["Tiny"]["free_trial"]) == ("", "", "")


def test_b2b_prices_come_from_capterra_pages_and_getapp_only_fills_unknown(tmp_path, monkeypatch):
    ws = capterra_ws(tmp_path)
    (tmp_path / "config" / "getapp_categories.yaml").write_text(yaml.safe_dump({"crm": "customer-management-software"}), encoding="utf-8")
    p1 = with_pricing(listing(3, [("Leads", 900), ("Pipes", 500), ("Deals", 300)]), [
        ("Leads", {"hasFreeTrial": True, "hasFreeVersion": False, "plans": [plan(29, default=True)]}),
        ("Pipes", {"hasFreeTrial": False, "hasFreeVersion": False, "plans": [plan(None, default=True, ptype=2)]}),
        ("Deals", {"hasFreeTrial": True, "hasFreeVersion": True})])
    asked = []

    def request(url, **kw):
        asked.append(url)
        return Resp(BLOCK if "getapp.com" in url else p1)
    monkeypatch.setattr(http, "request", request)
    monkeypatch.setattr(s5_capterra.time, "sleep", lambda s: None)
    monkeypatch.setattr(s5_pricing_b2b.time, "sleep", lambda s: None)
    s5_capterra.run(ws, argparse.Namespace())
    s5_pricing_b2b.run(ws, argparse.Namespace(agg=False))
    assert [u for u in asked if "getapp" in u] == ["https://www.getapp.com/customer-management-software/crm/"]   # Deals only, once
    rows = {r["product"]: r for r in csv.DictReader(open(ws.out("pricing_b2b.csv"), encoding="utf-8"))}
    assert [rows[p]["source"] for p in ("Leads", "Pipes", "Deals")] == ["capterra", "capterra", ""]
    assert (rows["Deals"]["price"], rows["Deals"]["free_trial"], rows["Deals"]["free_version"]) == ("", "1", "1")
    agg = next(csv.DictReader(open(ws.out("pricing_b2b_niche.csv"), encoding="utf-8")))
    # Deals is unknown, not unpriced: one public price out of two known, not one out of three
    assert (agg["n"], agg["price_known"], agg["price_public"], agg["price_public_share"]) == ("3", "2", "1", "0.5")
    assert (agg["median_monthly_usd"], agg["under_100_share"], agg["free_trial_share"]) == ("29.0", "1.0", "0.67")


def saved(url: str, page: str) -> str:
    """A page as a browser saves it: the address in a comment before the document."""
    return f"<!-- saved from url=({len(url):04d}){url} -->\n" + page


def test_capterra_pages_saved_in_a_browser_are_imported_and_missing_ones_listed(tmp_path, monkeypatch, capsys):
    ws = capterra_ws(tmp_path)
    (tmp_path / "config" / "capterra_map.yaml").write_text(yaml.safe_dump(
        {"crm": {"slugs": ["crm-software", "sales-software"]}, "budget": {"slugs": ["crm-software"]}}), encoding="utf-8")

    def no_network(*a, **k):
        raise AssertionError("--missing and --import make no requests")
    monkeypatch.setattr(http, "request", no_network)
    s5_capterra.run(ws, argparse.Namespace(missing=True))
    out = capsys.readouterr().out
    assert "2 page(s)" in out   # a category shared by two niches is listed once
    assert "https://www.capterra.com/crm-software/   (" in out and "https://www.capterra.com/sales-software/   (crm)" in out
    folder = tmp_path / "saved"
    folder.mkdir()
    (folder / "Best CRM Software.html").write_text(saved("https://www.capterra.com/crm-software/",
                                                         listing(400, [("Leads", 900), ("Pipes", 500)])), encoding="utf-8")
    (folder / "Best CRM Software (2).html").write_text(saved("https://www.capterra.com/crm-software/?page=2",
                                                             listing(400, [("Deals", 300)])), encoding="utf-8")
    (folder / "check.html").write_text(saved("https://www.capterra.com/sales-software/", BLOCK), encoding="utf-8")
    (folder / "other.html").write_text(saved("https://www.capterra.com/p/123/Leads/", listing(1, [("Leads", 900)])), encoding="utf-8")
    s5_capterra.run(ws, argparse.Namespace(import_dir=str(folder), missing=True))
    out = capsys.readouterr().out
    assert "imported 2 of 4" in out and "skip check.html" in out and "skip other.html" in out
    assert sorted(p.name for p in ws.cache("capterra").iterdir()) == ["crm-software_p1.html", "crm-software_p2.html"]
    # the next page of the category that is now read up to page 2, and still page 1 of the other one
    assert "https://www.capterra.com/crm-software/?page=3   (" in out and "https://www.capterra.com/sales-software/   (crm)" in out
