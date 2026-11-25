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


def test_report_runs_with_vendor_income(tmp_path):
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["ru"], "as_of": "2026-11-25"}), encoding="utf-8")
    (tmp_path / "niches.yaml").write_text("[]\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ru_b2b_niches.yaml").write_text(yaml.safe_dump([
        {"id": "mono", "name": "Monopoly", "who": "w", "product": "p", "notes": "n"},
        {"id": "pair", "name": "Two players", "who": "w", "product": "p"},
    ]), encoding="utf-8")
    ws = Workspace(tmp_path)
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
