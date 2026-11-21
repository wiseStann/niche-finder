"""Offline tests for s0_regulation: prefilter, selection, batching, regulation.gov.ru parsing and a full run with fakes."""
from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

import yaml

from nichefinder import http, llm
from nichefinder.stages import s0_regulation as reg
from nichefinder.workspace import Workspace

CONFIG = Path(reg.__file__).resolve().parents[1] / "examples" / "default" / "config" / "regulation.yaml"


def make_ws(tmp_path: Path, markets=("us", "ru")) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": list(markets), "as_of": "2026-11-21"}), encoding="utf-8")
    (tmp_path / "config").mkdir()
    shutil.copy(CONFIG, tmp_path / "config" / "regulation.yaml")
    return Workspace(tmp_path)


def cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def fr_doc(num, title, abstract="", significant=False, date="2026-06-01", typ="Rule"):
    return {"document_number": num, "title": title, "abstract": abstract, "action": "Final rule.", "dates": "Effective July 1, 2026.",
            "agencies": [{"name": "Labor Department"}, {"raw_name": "Wage and Hour Division"}], "effective_on": "2026-07-01",
            "html_url": f"https://www.federalregister.gov/d/{num}", "significant": significant, "publication_date": date, "type": typ}


NPALIST = """<projects offset="0" limit="500" sort="desc" total="3">
  <project id="300">
    <title>Об утверждении формы отчета о маркировке товаров</title>
    <projectId>01/02/06-26/00000300</projectId>
    <publishDate>2026-06-10T10:00:00Z</publishDate>
    <kind id="2">Проект ведомственного акта</kind>
    <department id="1">Минпромторг России</department>
    <procedure id="2">Оценка регулирующего воздействия</procedure>
    <regulatoryImpact id="1">Высокая</regulatoryImpact>
    <circlePersons>индивидуальные предприниматели и организации, продающие товары</circlePersons>
    <planDate>2027-03-01T12:00:00Z</planDate>
  </project>
  <project id="200">
    <title>Об утверждении образцов форменной одежды работников</title>
    <publishDate>2026-03-01T10:00:00Z</publishDate>
    <procedure id="1">Раскрытие информации о подготовке проектов нормативных правовых актов</procedure>
    <regulatoryImpact id="0">Не определена</regulatoryImpact>
  </project>
  <project id="100">
    <title>Об утверждении порядка ведения реестра</title>
    <publishDate>2025-10-01T10:00:00Z</publishDate>
  </project>
</projects>"""

PRINT = {"title": "x", "blocks": [
    {"title": "Паспорт проекта", "values": [
        {"description": "Ключевые слова", "type": "Text", "values": ["маркировка", "отчет"]},
        {"description": "Сотрудник, ответственный за разработку проекта", "type": "Text", "values": ["Иванов Иван"]}]},
    {"title": "Текст", "values": [
        {"description": "Обязательные требования (КНД)", "type": "Text", "values": ["Да"]},
        {"description": "Круг лиц, на которых будет распространено действие ", "type": "Text", "values": [["продавцы"]]},
        {"description": "Электронный адрес для отправки своих предложений", "type": "EmailLink", "values": ["a@b.ru"]},
        {"description": "Планируемый срок вступления проекта в силу", "type": "DateTime", "values": ["2027-03-01T12:00:00"]}]}]}


def test_us_priority_excludes_routine_and_counts_terms():
    c = cfg()["us"]
    assert reg.us_priority(fr_doc("1", "Airworthiness Directives; Boeing Airplanes", "inspection reporting"), c) == 0
    assert reg.us_priority(fr_doc("2", "Amendment of Class E Airspace", ""), c) == 0
    assert reg.us_priority(fr_doc("3", "Parking Rates", "Sets the rate."), c) == 0
    p = reg.us_priority(fr_doc("4", "Employer Recordkeeping", "Employers must keep records; small entities affected."), c)
    assert p >= 3 and reg.us_priority(fr_doc("4", "Employer Recordkeeping", "Employers must keep records; small entities affected.",
                                             significant=True), c) == p + 2


def test_ru_parsing_priority_and_passport():
    rows = reg.parse_npalist(NPALIST)
    assert [r["id"] for r in rows] == ["300", "200", "100"]
    c = cfg()["ru"]
    orv, uniform, plain = rows
    assert reg.ru_priority(uniform, c) == 0                         # internal act of the state apparatus
    p = reg.ru_priority(orv, c)
    assert p >= 4 + 2 + 1                                           # high ORV impact + terms + business addressees
    assert reg.ru_priority(plain, c) == 2                           # two terms (a register, a keeping procedure), no ORV
    row = reg.ru_row(orv, c["orv_procedure"])
    assert row["flag"] == "Высокая" and row["effective"] == "2027-03-01" and row["url"].endswith("/projects/300")
    assert "Affected: индивидуальные" in row["_text"]
    pp = reg.parse_passport(PRINT)
    assert pp == {"Keywords": "маркировка; отчет", "Sets mandatory requirements": "Да", "Affected": "продавцы",
                  "Planned entry into force": "2027-03-01"}   # no names, e-mails or phones


def test_select_splits_budget_and_batches_by_month():
    def rows(m, n):
        return [{"market": m, "priority": i % 3 + 1, "published": f"2026-0{1 + i % 2}-1{i % 9}", "doc_id": f"{m}{i}"} for i in range(n)]
    out = reg.select({"us": rows("us", 10), "ru": rows("ru", 2)}, 8)
    assert len(out["ru"]) == 2 and len(out["us"]) == 6               # ru leaves its unused share to us
    assert [r["priority"] for r in out["us"]] == sorted((r["priority"] for r in out["us"]), reverse=True)
    chunks = reg.batches(out["us"] + out["ru"], 2)
    assert all(len({(r["market"], r["published"][:7]) for r in c}) == 1 and len(c) <= 2 for c in chunks)
    assert sum(len(c) for c in chunks) == 8


def test_run_end_to_end(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    (tmp_path / "niches.yaml").write_text("[]\n", encoding="utf-8")
    fr_pages = {
        1: {"results": [fr_doc("2026-1", "Employer Recordkeeping for Tip Pools", "Employers must keep records of tips.", True),
                        fr_doc("2026-2", "Safety Zone; Fireworks", "safety")],
            "next_page_url": "https://www.federalregister.gov/api/v1/documents?page=2"},
        2: {"results": [fr_doc("2026-3", "Removal of Reporting Requirements", "Removes reporting requirements for employers.")],
            "next_page_url": None}}

    def fake_json(url, **kw):
        if "federalregister" in url:
            if "conditions%5Btype%5D%5B%5D=PRORULE" in url:
                return {"results": [], "next_page_url": None}
            return fr_pages[2 if "page=2" in url else 1]
        if "PublicProjects/Print/" in url:
            return PRINT
        raise AssertionError(url)

    monkeypatch.setattr(http, "get_json", fake_json)
    monkeypatch.setattr(http, "get_text", lambda url, **kw: NPALIST)
    asked = []

    def fake_llm(ws_, messages, **kw):
        user = messages[1]["content"]
        asked.append(user)
        items = []
        for i, block in enumerate(user.split("\n\n")):
            yes = "Tip Pools" in block or "маркировке" in block
            items.append({"i": i, "creates_task": "yes" if yes else "no", "recurring": "yes" if yes else "no",
                          "who": "US employers with tipped staff" if "Tip" in block else "Russian sellers",
                          "task": "keep tip records", "deadline": "2026-07-01", "idea_who": "restaurants",
                          "idea_task": "track tip pools", "idea_product": "SaaS", "confidence": "high", "why": "names the duty"})
        return {"r": items}, False, {"prompt_tokens": 100, "completion_tokens": 50}

    monkeypatch.setattr(llm, "chat_json", fake_llm)
    reg.run(ws, argparse.Namespace(max_docs=None, markets="", workers=1, dry=False))
    rows = list(csv.DictReader(open(ws.out("regulation_candidates.csv"), encoding="utf-8")))
    by = {r["doc_id"]: r for r in rows}
    # the safety zone is dropped by the prefilter, the uniform order too, the 2025-10 draft is outside the window
    assert set(by) == {"2026-1", "2026-3", "01/02/06-26/00000300"}
    assert by["2026-1"]["creates_task"] == "yes" and by["2026-1"]["flag"] == "significant"
    assert by["2026-3"]["creates_task"] == "no" and by["2026-3"]["idea_product"] == ""
    ru = by["01/02/06-26/00000300"]
    assert ru["creates_task"] == "yes" and "mandatory requirements" in ru["flag"]
    assert any("Keywords: маркировка" in a for a in asked)          # the passport reached the LLM
    assert not any("a@b.ru" in a or "Иванов" in a for a in asked)   # contact details never did
    report = ws.report("S0-regulation.md").read_text(encoding="utf-8")
    assert "Tip Pools" in report and "regulation.gov.ru" in report and "restaurants x track tip pools x SaaS" in report
    assert (tmp_path / "niches.yaml").read_text(encoding="utf-8") == "[]\n"


def us_only(monkeypatch, n):
    docs = [fr_doc(f"2026-{i}", f"Employer Recordkeeping {i}", "Employers must keep records.", date=f"2026-{1 + i % 12:02d}-01")
            for i in range(n)]
    monkeypatch.setattr(http, "get_json", lambda url, **kw: {"results": [] if "PRORULE" in url else docs, "next_page_url": None})


def test_llm_down_stops_after_one_probe_call(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, markets=("us",))
    us_only(monkeypatch, 30)
    calls = []

    def broke(ws_, messages, **kw):                     # what llm.chat_json returns after an HTTP 402 on every try
        calls.append(kw.get("tries"))
        return None, False, None

    monkeypatch.setattr(llm, "chat_json", broke)
    reg.run(ws, argparse.Namespace(max_docs=30, markets="", workers=3, dry=False))
    assert calls == [2]                                 # the probe only, with few retries
    pre = list(csv.DictReader(open(ws.out("regulation_prefilter.csv"), encoding="utf-8")))
    assert len(pre) == 30 and all(r["selected"] == "1" for r in pre)
    assert not ws.out("regulation_candidates.csv").exists() and not ws.report("S0-regulation.md").exists()


def test_llm_failing_midway_writes_an_incomplete_report(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, markets=("us",))
    us_only(monkeypatch, 60)                            # 12 months x 5 documents, batch 10 -> 12 calls
    state = {"n": 0}

    def flaky(ws_, messages, **kw):
        state["n"] += 1
        if state["n"] > 3:
            return None, False, None
        n = messages[1]["content"].count("\nTitle: ")
        return {"r": [{"i": i, "creates_task": "yes", "confidence": "high"} for i in range(n)]}, False, None

    monkeypatch.setattr(llm, "chat_json", flaky)
    reg.run(ws, argparse.Namespace(max_docs=60, markets="", workers=1, dry=False))
    assert state["n"] == 4                              # three answers, then one failure stops a single worker
    rows = list(csv.DictReader(open(ws.out("regulation_candidates.csv"), encoding="utf-8")))
    assert len(rows) == 60 and sum(r["creates_task"] == "yes" for r in rows) == 15
    assert sum(r["why"].startswith("not classified") for r in rows) == 45
    assert "INCOMPLETE: 45 selected documents" in ws.report("S0-regulation.md").read_text(encoding="utf-8")


def test_dry_run_makes_no_llm_calls(tmp_path, monkeypatch):
    ws = make_ws(tmp_path, markets=("us",))
    monkeypatch.setattr(http, "get_json", lambda url, **kw: {"results": [fr_doc("1", "Employer Recordkeeping", "Employers must keep records.")],
                                                              "next_page_url": None})

    def boom(*a, **kw):
        raise AssertionError("LLM called in a dry run")

    monkeypatch.setattr(llm, "chat_json", boom)
    reg.run(ws, argparse.Namespace(max_docs=5, markets="", workers=1, dry=True))
    assert not ws.out("regulation_candidates.csv").exists()
