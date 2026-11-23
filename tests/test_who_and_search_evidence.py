"""Offline tests for the register counts (ru_msp_counts, s8_who_counts, ru_vendor_revenue), the paid-search evidence
stages (s3_switch_intent, s5_serp) and the Wayback stage."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import zipfile
from pathlib import Path

import yaml

from nichefinder import http
from nichefinder.sources import dataforseo as dfs
from nichefinder.stages import ru_msp_counts, ru_vendor_revenue, s3_switch_intent, s5_serp, s8_who_counts, s9_wayback
from nichefinder.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": "2026-11-21"}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "queries").mkdir()
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": "salons", "who": "w", "task": "t", "product": "p", "geo": "both", "side": "b2b-smb", "tier": "A"},
        {"id": "gyms", "who": "w", "task": "t", "product": "p", "geo": "global", "side": "b2c", "tier": "A"},
    ]), encoding="utf-8")
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump({
        "salons": {"en": [{"q": "salon software", "i": "category", "anchor": True}, {"q": "salon booking app", "i": "category"},
                          {"q": "vagaro", "i": "brand", "b": "Vagaro"}],
                   "ru": [{"q": "программа для салона", "i": "category", "anchor": True}, {"q": "yclients", "i": "brand", "b": "YCLIENTS"}]},
        "gyms": {"en": [{"q": "gym software", "i": "category", "anchor": True}, {"q": "zen planner", "i": "brand", "b": "Zen Planner"}]},
    }, allow_unicode=True), encoding="utf-8")
    (tmp_path / "config" / "shortlist.yaml").write_text(yaml.safe_dump({"tier_a": [{"id": "salons"}, {"id": "gyms"}]}), encoding="utf-8")
    return Workspace(tmp_path)


# ---- ru_msp_counts -----------------------------------------------------------

def _doc(kind, cat, new, code):
    return (f'<Документ ИдДок="x" ДатаСост="10.11.2026" ВидСубМСП="{kind}" КатСубМСП="{cat}" ПризНовМСП="{new}">'
            f'<СвОКВЭД><СвОКВЭДОсн КодОКВЭД="{code}" НаимОКВЭД="name {code}" ВерсОКВЭД="2014"/></СвОКВЭД></Документ>')


def _msp_zip(path: Path, docs: list[str]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.xml", '<?xml version="1.0"?><Файл>' + "".join(docs[:2]) + "</Файл>")
        z.writestr("b.xml", '<?xml version="1.0"?><Файл>' + "".join(docs[2:]) + "</Файл>")


def test_msp_pick_and_prefix_match():
    dumps = {dt.date(2026, 11, 10): "a", dt.date(2026, 10, 10): "b", dt.date(2025, 11, 10): "c", dt.date(2025, 10, 10): "d"}
    assert ru_msp_counts.pick(dumps, dt.date(2026, 11, 21), True) == (dt.date(2026, 11, 10), dt.date(2025, 11, 10))
    assert ru_msp_counts.pick(dumps, dt.date(2026, 11, 1), True) == (dt.date(2026, 10, 10), dt.date(2025, 10, 10))
    assert ru_msp_counts.matches("96.02.1", "96.02") and ru_msp_counts.matches("96.02", "96.02")
    assert ru_msp_counts.matches("43.21", "43.2") and ru_msp_counts.matches("43.22.1", "43.2")   # subgroups carry no dot
    assert not ru_msp_counts.matches("96.0", "96.02") and not ru_msp_counts.matches("11.1", "01.1")


def test_msp_counts_end_to_end(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (tmp_path / "config" / "who_counts.yaml").write_text(yaml.safe_dump({"salons": {"okved": ["96.02"]}, "gyms": {"naics": ["713940"]}}))
    now = ws.cache("rmsp") / "data-10112026-structure-12052026.zip"
    old = ws.cache("rmsp") / "data-10112025-structure-10062025.zip"
    _msp_zip(now, [_doc(2, 1, 1, "96.02"), _doc(2, 1, 2, "96.02.1"), _doc(1, 2, 2, "96.02"), _doc(1, 1, 2, "62.01")])
    _msp_zip(old, [_doc(2, 1, 2, "96.02"), _doc(1, 2, 2, "96.02"), _doc(1, 1, 2, "62.01")])
    monkeypatch.setattr(ru_msp_counts, "list_dumps", lambda ws: {dt.date(2026, 11, 10): now.name, dt.date(2025, 11, 10): old.name})
    monkeypatch.setattr(http, "download", lambda url, path, **kw: path)    # the zips are already in the cache folder
    ru_msp_counts.run(ws, argparse.Namespace(no_compare=False, keep_dumps=False, date=None))
    codes = {r["code"]: r for r in csv.DictReader(open(ws.out("ru_msp_okved.csv"), encoding="utf-8"))}
    assert codes["96.02"]["total"] == "2" and codes["96.02"]["ip"] == "1" and codes["96.02"]["new"] == "1"
    (row,) = list(csv.DictReader(open(ws.out("ru_msp_niches.csv"), encoding="utf-8")))
    assert row["niche_id"] == "salons" and row["msp"] == "3" and row["msp_prev"] == "2" and float(row["msp_yoy"]) == 0.5
    assert not now.exists() and ws.out("ru_msp/okved_2026-11-10.csv").is_file()   # zip deleted, aggregate kept as the cache
    monkeypatch.setattr(http, "download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download on re-run")))
    ru_msp_counts.run(ws, argparse.Namespace(no_compare=False, keep_dumps=False, date=None))


# ---- s8_who_counts -----------------------------------------------------------

def _census_zip(path: Path, name: str, text: str) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, text)


def test_who_counts_us_and_ru(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (tmp_path / "config" / "who_counts.yaml").write_text(yaml.safe_dump({
        "salons": {"naics": ["812112"], "okved": ["96.02"], "note": "n"}, "gyms": {"naics": ["713940", "999999"]}}))
    head = '"uscode","naics","lfo","emp","est","n<5","n5_9","n10_19","n20_49"\n'
    c23 = head + '"98","812112","-",1,100,60,20,10,5\n"98","812112","C",1,40,1,1,1,1\n"98","713940","-",1,50,10,10,10,10\n'
    c22 = head + '"98","812112","-",1,80,1,1,1,1\n"98","713940","-",1,50,1,1,1,1\n'
    ne = '"ST","NAICS","LFO","RCPTOT_SIZE","ESTAB_F","ESTAB"\n"00","812112","-","001",,900\n"00","71394","-","001",,77\n'
    d = ws.cache("census")
    _census_zip(d / "cbp23us.zip", "cbp23us.txt", c23)
    _census_zip(d / "cbp22us.zip", "cbp22us.txt", c22)
    _census_zip(d / "nonemp24us.zip", "nonemp24us.txt", ne)
    monkeypatch.setattr(s8_who_counts, "find_cbp", lambda ws: [(2023, "x/cbp23us.zip"), (2022, "x/cbp22us.zip")])
    monkeypatch.setattr(s8_who_counts, "find_nonemp", lambda ws: (2024, "x/nonemp24us.zip"))
    monkeypatch.setattr(http, "download", lambda url, path, **kw: path)
    with open(ws.out("ru_msp_niches.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("niche_id,okved,msp,msp_prev,msp_yoy,ip_share\nsalons,96.02,5000,4000,0.25,0.8\n")
    s8_who_counts.run(ws, argparse.Namespace())
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("who_counts.csv"), encoding="utf-8"))}
    s = rows["salons"]
    assert s["us_est"] == "100" and float(s["us_est_yoy"]) == 0.25 and s["us_lt20"] == "90" and s["us_nonemp"] == "900"
    assert s["ru_msp"] == "5000" and s["us_year"] == "2023"
    g = rows["gyms"]
    assert g["us_est"] == "50" and g["missing"] == "999999" and g["us_nonemp"] == "77"   # 713940 -> 71394 by the NAICS rule


# ---- ru_vendor_revenue -------------------------------------------------------

def test_vendor_name_normalisation():
    assert ru_vendor_revenue.norm('ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ &quot;РОМАШКА&quot;') == "ромашка"
    assert ru_vendor_revenue.norm('ООО «Ромашка»') == "ромашка"
    assert ru_vendor_revenue.norm('АО "Ёлка Софт"') == "елка софт"
    assert ru_vendor_revenue.norm("Акционерное общество Аорта") == "аорта"     # "ao" inside a word is kept


def test_vendor_revenue_summary(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)

    def rel(docs):
        body = "".join(f'<Документ ИдДок="x" ДатаДок="25.10.2026" ДатаСост="31.12.{y}"><СведНП НаимОрг="{n.replace('"', '&quot;')}" ИННЮЛ="{i}"/>'
                       f'<СведДохРасх СумДоход="{inc}" СумРасход="1.00"/></Документ>' for n, i, inc, y in docs)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.xml", '<?xml version="1.0"?><Файл>' + body + "</Файл>")
        return buf.getvalue()

    d = ws.cache("revexp")
    (d / "data-20261025-structure-20180110.zip").write_bytes(rel([
        ('ООО "Ромашка"', "1", "300000000.00", 2025), ('ООО "Дубль"', "2", "5.00", 2025), ('ООО "Дубль"', "3", "6.00", 2025),
        ('АО "Гигант"', "4", "90000000000.00", 2025)]))
    (d / "data-20251025-structure-20180110.zip").write_bytes(rel([('ООО "Ромашка"', "1", "200000000.00", 2024)]))
    monkeypatch.setattr(ru_vendor_revenue, "list_releases", lambda ws: {
        dt.date(2026, 10, 25): "data-20261025-structure-20180110.zip", dt.date(2025, 10, 25): "data-20251025-structure-20180110.zip"})
    monkeypatch.setattr(http, "download", lambda url, path, **kw: path)
    with open(ws.out("ru_b2b_reestr_items.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["niche_id", "id", "date", "name", "owner", "classes", "keyword", "ai"])
        for o in ('Общество с ограниченной ответственностью "Ромашка"', 'ООО "Дубль"', 'АО "Гигант"', "ИП Иванов"):
            w.writerow(["crm", "1", "", "p", o, "", "", 0])
    ru_vendor_revenue.run(ws, argparse.Namespace(max_income=20e9))
    (r,) = list(csv.DictReader(open(ws.out("ru_vendor_revenue.csv"), encoding="utf-8")))
    assert (r["owners"], r["matched"], r["ambiguous"], r["unmatched"], r["diversified"]) == ("4", "1", "1", "1", "1")
    assert r["income_sum"] == "300000000" and float(r["income_growth"]) == 0.5 and r["year"] == "2025"


# ---- s3_switch_intent --------------------------------------------------------

def test_switch_intent_phrases_and_summary(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    ph = s3_switch_intent.phrases(ws, "en")
    assert {"vagaro alternative", "cancel vagaro", "zen planner alternatives"} <= {p["phrase"] for p in ph}
    assert {p["phrase"] for p in s3_switch_intent.phrases(ws, "ru")} >= {"аналог yclients", "отменить подписку yclients"}

    def fake_sv(ws_, keywords, location_code=None, language_code=None, date_from=None, use_cache=True):
        out = {}
        for k in keywords:
            v = 100 if "alternative" in k else 10
            months = [{"year": 2025 + (i // 12), "month": i % 12 + 1, "search_volume": v} for i in range(24)]
            out[k] = {"keyword": k, "search_volume": v, "monthly_searches": months}
        return out, 0.0

    monkeypatch.setattr(dfs, "search_volume", fake_sv)
    monkeypatch.setattr(dfs, "search_volume_cached", lambda *a, **k: True)
    with open(ws.out("dfs_us.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("keyword,search_volume\nvagaro,1000\nzen planner,400\n")
    s3_switch_intent.run(ws, argparse.Namespace(pools=["us"], dry=False))
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("switch_intent.csv"), encoding="utf-8"))}
    assert rows["salons"]["alt_volume"] == "310" and float(rows["salons"]["alt_ratio"]) == 0.31   # 3 x 100 + "apps like" 10
    assert rows["salons"]["churn_volume"] == "20"
    assert rows["salons"]["top_alt_brand"] == "Vagaro" and rows["salons"]["alt_ratio_pct"] == "1.0"   # B2B cohort of one


def test_switch_intent_stops_when_balance_is_low(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    monkeypatch.setattr(dfs, "search_volume_cached", lambda *a, **k: False)
    monkeypatch.setattr(dfs, "balance", lambda: 0.01)
    monkeypatch.setattr(dfs, "search_volume", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not pay")))
    try:
        s3_switch_intent.run(ws, argparse.Namespace(pools=["us"], dry=False))
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "balance" in str(e)


# ---- s5_serp -----------------------------------------------------------------

def test_serp_ownership(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (tmp_path / "config" / "serp_domains.yaml").write_text(yaml.safe_dump({"directory": ["capterra.com"], "ugc": ["reddit.com"]}))

    def fake_serp(ws_, q, **kw):
        org = [{"type": "organic", "rank_group": i + 1, "domain": d, "url": f"https://{d}/", "title": d}
               for i, d in enumerate(["www.vagaro.com", "capterra.com", "blog.capterra.com", "reddit.com", "example.com"])]
        return org + [{"type": "ai_overview"}], 0.0

    monkeypatch.setattr(dfs, "serp", fake_serp)
    monkeypatch.setattr(dfs, "serp_cached", lambda *a, **k: True)
    monkeypatch.setattr(dfs, "keyword_difficulty_cached", lambda *a, **k: True)
    monkeypatch.setattr(dfs, "keyword_difficulty", lambda ws_, kws, **k: ({q: 40 for q in kws}, 0.0))
    s5_serp.run(ws, argparse.Namespace(per_niche=2, dry=False, niches=["salons"]))
    (r,) = list(csv.DictReader(open(ws.out("serp_ownership.csv"), encoding="utf-8")))
    assert r["queries"] == "2" and r["organic"] == "10"
    assert float(r["directory_share"]) == 0.4 and float(r["brand_share"]) == 0.2 and float(r["ugc_share"]) == 0.2
    assert float(r["ai_overview_share"]) == 1.0 and "R:ai-overview" in r["flags"] and float(r["kd_mean"]) == 40


# ---- s9_wayback --------------------------------------------------------------

def test_wayback_domain_stats_and_skip():
    today = dt.date(2026, 11, 21)
    st = s9_wayback.domain_stats([("201501", "200"), ("202601", "200"), ("202610", "404")], today)
    assert st["first"] == "2015-01" and st["alive"] == 1 and st["age_years"] == 11.8 and st["months_24"] == 2
    assert s9_wayback.domain_stats([("201801", "200")], today)["alive"] == 0
    assert s9_wayback.skip("apps.apple.com") and s9_wayback.skip("foo.github.io") and not s9_wayback.skip("vagaro.com")
    assert s9_wayback.domain("https://www.Vagaro.com/pro") == "vagaro.com"


def test_wayback_end_to_end(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (ws.cache("appstore") / "x.json").write_text(json.dumps({"results": [
        {"trackId": 1, "sellerUrl": "https://www.vagaro.com"}, {"trackId": 2, "sellerUrl": "https://linktr.ee/x"}]}))
    with open(ws.out("appstore_apps.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("niche_id,store,track_id,name,ratings,relevant\nsalons,us,1,Vagaro,900,1\nsalons,us,2,Other,10,1\n")
    monkeypatch.setattr(s9_wayback, "history", lambda ws_, d: [("201001", "200"), ("202609", "200")])
    s9_wayback.run(ws, argparse.Namespace(top=10))
    (r,) = list(csv.DictReader(open(ws.out("wayback.csv"), encoding="utf-8")))
    assert r["domains"] == "1" and r["leaders_age_median"] == "16.8" and r["quiet_share"] == "0.0"


# ---- http.download resume ----------------------------------------------------

def test_download_resumes_with_range(tmp_path, monkeypatch):
    calls = []

    class Resp:
        def __init__(self, status, data, fail_after=None):
            self.status, self.data, self.fail_after, self.pos = status, data, fail_after, 0
            self.headers = {"Content-Length": str(len(data) if fail_after is None else 6)}

        def read(self, n):
            if self.fail_after is not None and self.pos >= self.fail_after:
                raise OSError("connection reset")
            out = self.data[self.pos:self.pos + 2]
            self.pos += len(out)
            return out

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout, proxy=None):
        calls.append(req.headers.get("Range"))
        return Resp(200, b"abc", fail_after=2) if len(calls) == 1 else Resp(206, b"cdef")   # 2 bytes, then the rest

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    dst = tmp_path / "big.zip"
    http.download("https://example.com/big.zip", dst, progress=False)
    assert calls == [None, "bytes=2-"]
    assert dst.read_bytes() == b"abcdef"


# ---- passport blocks (nichefinder.evidence) ------------------------------------

def test_evidence_blocks_render(tmp_path):
    from nichefinder.evidence import Evidence
    ws = make_ws(tmp_path)
    o = ws.out

    def put(name, rows):
        with open(o(name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    put("who_counts.csv", [{"niche_id": "salons", "naics": "812112", "us_est": "100000", "us_est_prev": "98000", "us_est_yoy": "0.02",
                            "us_lt20": "97000", "us_lt20_share": "0.97", "us_nonemp": "900000", "missing": "", "okved": "96.02",
                            "ru_msp": "250000", "ru_msp_yoy": "0.05", "ru_ip_share": "0.8", "note": "floor", "us_year": "2023",
                            "us_prev_year": "2022", "nonemp_year": "2024"}])
    put("switch_intent.csv", [{"niche_id": "salons", "pool": "us", "side": "b2b-smb", "brand_volume": "1000", "alt_volume": "300",
                               "churn_volume": "20", "alt_ratio": "0.3", "churn_ratio": "0.02", "alt_ratio_pct": "0.9", "alt_yoy": "0.1",
                               "top_alt_brand": "Vagaro", "top_alt_share": "0.7"}])
    put("serp_ownership.csv", [{"niche_id": "salons", "queries": "3", "organic": "30", "distinct_domains": "20", "directory_share": "0.4",
                                "store_share": "0", "ugc_share": "0.1", "media_share": "0.2", "brand_share": "0.2", "other_share": "0.1",
                                "top3_brand_avg": "1.0", "ai_overview_share": "0.67", "local_pack_share": "0", "paid_items": "0",
                                "kd_mean": "35", "flags": "R:serp-listicles R:ai-overview", "top_domains": "capterra.com (3)"}])
    put("wayback.csv", [{"niche_id": "salons", "domains": "10", "measured": "9", "leaders_age_median": "12", "young_share": "0.1",
                         "quiet_share": "0.2", "oldest": "a.com", "youngest": "b.com"}])
    ev = Evidence(ws)
    who = "\n".join(ev.who_lines("salons", {"payers_low": "1000", "payers_high": "50000"}))
    assert "100,000 establishments" in who and "1.0% of US establishments" in who and "250,000 businesses" in who
    assert "Vagaro" in "\n".join(ev.switch_lines("salons"))
    assert "R:serp-listicles" in "\n".join(ev.serp_lines("salons"))
    assert "12 years old" in "\n".join(ev.supply_lines("salons"))
    tags = ev.tags("salons")
    assert "R:ai-overview" in tags and "W:switch-high" in tags and "who:100,000" in tags
    assert ev.who_lines("gyms") == [] and ev.yt_lines("salons") == [] and ev.freelance_line("salons") == []


def test_dataforseo_account_refusal_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(dfs, "_raw_request", lambda *a, **k: {"status_code": 40104, "status_message": "Please verify your account", "tasks": None})
    try:
        dfs._request("POST", "/serp/google/organic/live/advanced", [{}])
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "40104" in str(e) and "verify" in str(e)


def test_serp_stops_at_the_first_account_error(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    calls = []

    def refused(ws_, q, **kw):
        calls.append(q)
        raise dfs.AccountError("DataForSEO serp 40201: paused")

    monkeypatch.setattr(dfs, "serp", refused)
    monkeypatch.setattr(dfs, "serp_cached", lambda *a, **k: True)
    monkeypatch.setattr(dfs, "keyword_difficulty_cached", lambda *a, **k: True)
    monkeypatch.setattr(dfs, "keyword_difficulty", lambda ws_, kws, **k: ({}, 0.0))
    try:
        s5_serp.run(ws, argparse.Namespace(per_niche=2, dry=False, niches=["salons", "gyms"]))
        raise AssertionError("expected SystemExit")
    except SystemExit as e:
        assert "40201" in str(e)
    assert len(calls) == 1
    assert isinstance(dfs._fail(40104, "verify"), dfs.AccountError) and not isinstance(dfs._fail(40501, "bad"), dfs.AccountError)
