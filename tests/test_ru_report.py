"""Offline test of ru_report: the Russian B2B score and report run end to end on minimal inputs (the vendor income block of
the report once read its file through a helper local to run(), so every report failed with a NameError)."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml

from nichefinder.stages import ru_report
from nichefinder.workspace import Workspace


def _write(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _ws(tmp_path: Path, niches: list[dict], traps: dict | None = None) -> Workspace:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["ru"], "as_of": "2026-11-25"}), encoding="utf-8")
    (tmp_path / "niches.yaml").write_text("[]\n", encoding="utf-8")
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "ru_b2b_niches.yaml").write_text(yaml.safe_dump(niches, allow_unicode=True), encoding="utf-8")
    if traps is not None:
        (tmp_path / "config" / "ru_b2b_traps.yaml").write_text(yaml.safe_dump({"ws_traps": traps}, allow_unicode=True), encoding="utf-8")
    return Workspace(tmp_path)


def _brands(nid: str, **counts: int) -> list[dict]:
    return [{"niche_id": nid, "kind": "ws_brands", "phrase": p, "total_count": c, "top5": ""} for p, c in counts.items()]


def _scores(ws: Workspace) -> dict[str, dict]:
    ru_report.run(ws, argparse.Namespace())
    return {r["niche_id"]: r for r in csv.DictReader(open(ws.out("ru_b2b_score.csv"), encoding="utf-8"))}


def test_report_runs_with_vendor_income(tmp_path):
    ws = _ws(tmp_path, [
        {"id": "mono", "name": "Monopoly", "who": "w", "product": "p", "notes": "n"},
        {"id": "pair", "name": "Two players", "who": "w", "product": "p"},
    ])
    _write(ws.out("ru_b2b_wordstat.csv"), [
        {"niche_id": "mono", "kind": "ws_brands", "phrase": "leader", "total_count": 9000, "top5": ""},
        {"niche_id": "mono", "kind": "ws_brands", "phrase": "other", "total_count": 1000, "top5": ""},
        {"niche_id": "pair", "kind": "ws_brands", "phrase": "a", "total_count": 4100, "top5": ""},
        {"niche_id": "pair", "kind": "ws_brands", "phrase": "b", "total_count": 2900, "top5": ""},
        {"niche_id": "pair", "kind": "ws_cat", "phrase": "c", "total_count": 300, "top5": ""},
    ])
    _write(ws.out("ru_vendor_revenue.csv"), [
        {"niche_id": "pair", "owners": 12, "matched": 9, "ambiguous": 1, "unmatched": 2, "diversified": 0, "income_sum": 2.5e9,
         "income_median": 4e7, "vendors_100m": 3, "vendors_1bn": 1, "top_vendor": "Vendor", "top_income": 1.2e9, "top_share": 0.48,
         "growth_matched": 7, "income_growth": 0.12, "year": 2025, "year_prev": 2024},
    ])
    ru_report.run(ws, argparse.Namespace())
    rows = {r["niche_id"]: r for r in csv.DictReader(open(ws.out("ru_b2b_score.csv"), encoding="utf-8"))}
    assert rows["mono"]["verdict"] == "🔴 monopoly"          # 90% of 10,000 brand searches
    assert rows["pair"]["verdict"] != "🔴 monopoly" and "C:brand-leader" not in rows["pair"]["flags"]   # 59%
    report = ws.report("S0-ru-b2b.md").read_text(encoding="utf-8")
    assert "Vendor income" in report and "«Vendor» 48%" in report


def test_spellings_of_one_brand_merge_and_traps_can_be_scoped(tmp_path):
    ws = _ws(tmp_path, [
        {"id": "vet", "name": "Two spellings", "ws_brand_names": {"vmru": "vm"}},
        {"id": "speech", "name": "Trap here"},
        {"id": "tracking", "name": "Own brand here"},
    ], traps={"ct": {"reason": "adjacent category", "niches": ["speech"]}, "muscle": "a muscle, everywhere"})
    _write(ws.out("ru_b2b_wordstat.csv"), _brands("vet", vm=3500, vmru=3500, other=1000)
           + _brands("speech", own=400, ct=5000, muscle=900) + _brands("tracking", ct=5000, b=4000, muscle=900))
    rows = _scores(ws)
    # 7,000 of 8,000 is one brand once the spellings merge; per phrase the leader held 44% and the niche was not a monopoly
    assert (rows["vet"]["ws_top_brand"], float(rows["vet"]["ws_top_share"]), rows["vet"]["verdict"]) == ("vm", 0.875, "🔴 monopoly")
    assert "vm (vm + vmru)=7000" in rows["vet"]["ws_brands_detail"]
    assert float(rows["speech"]["ws_brands_sum"]) == 400 and "ct=5000 (adjacent category)" in rows["speech"]["ws_brands_detail"]
    # the scoped trap counts outside its niche; the global one is left out everywhere
    assert float(rows["tracking"]["ws_brands_sum"]) == 9000 and rows["tracking"]["ws_top_brand"] == "ct"
    assert "muscle=900 (a muscle, everywhere)" in rows["tracking"]["ws_brands_detail"]


def test_controls_are_scored_against_the_cohort_but_stay_out_of_it(tmp_path):
    cohort = [{"id": f"n{i}", "name": f"Niche {i}"} for i in range(4)]
    wsrows = [r for i in range(4) for r in _brands(f"n{i}", a=1000 * (i + 1), b=900 * (i + 1), c=800)]
    ws = _ws(tmp_path / "plain", cohort)
    _write(ws.out("ru_b2b_wordstat.csv"), wsrows)
    before = _scores(ws)
    ws = _ws(tmp_path / "with", cohort + [{"id": "ctrl", "name": "Control", "control": "green"}])
    _write(ws.out("ru_b2b_wordstat.csv"), wsrows + _brands("ctrl", a=900_000, b=800_000, c=700_000))
    after = _scores(ws)
    for nid, r in before.items():          # the control's huge demand moves no percentile and no median of the cohort
        assert (after[nid]["score"], after[nid]["verdict"]) == (r["score"], r["verdict"])
    assert after["ctrl"]["control"] == "green" and after["ctrl"]["verdict"] == "🟢"
    assert list(after)[-1] == "ctrl"        # controls come last
    report = ws.report("S0-ru-b2b.md").read_text(encoding="utf-8")
    assert "Controls: 1 of 1 get the expected colour" in report and "| `ctrl` | green | 🟢 ✓ |" in report


def test_verdict_rules_after_the_control_calibration(tmp_path):
    ws = _ws(tmp_path, [
        {"id": "edge", "name": "70.25% of 142,000"},
        {"id": "two", "name": "Two brands, 58%"},
        {"id": "three", "name": "Three brands, 58%"},
        {"id": "judged", "name": "Platform judgment", "platform": 2},
        {"id": "partial", "name": "Partial platform", "platform": 1},
    ])
    _write(ws.out("ru_b2b_wordstat.csv"), _brands("edge", a=99_861, b=32_468, c=9_830) + _brands("two", a=5_800, b=4_200)
           + _brands("three", a=5_800, b=2_200, c=2_000) + _brands("judged", a=3_000, b=3_000, c=3_000)
           + _brands("partial", a=3_000, b=3_000, c=3_000))
    rows = _scores(ws)
    # platform: 1 is a flag, as in G3: the colour comes from the rule ("judged" has the same data and is red only by judgment)
    assert "P1:platform-partial" in rows["partial"]["flags"] and not rows["partial"]["verdict"].startswith("🔴")
    assert rows["edge"]["verdict"] == "🔴 monopoly"        # compared unrounded: 70.25% is above 70%, rounded it was 0.70
    assert "top brand" not in rows["two"]["why"]        # with two brands the leader holds >= 50% by construction
    assert "C:few-brands" in rows["two"]["flags"] and "C:few-brands" not in rows["three"]["flags"]
    assert rows["three"]["verdict"] == "🟡" and rows["three"]["why"] == "top brand 58% of 3 brands"
    assert rows["judged"]["verdict"] == "🔴 platform"
