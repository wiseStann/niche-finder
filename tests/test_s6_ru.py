"""Offline tests for the gates of s6_ru (2026-11-24 calibration): brand queries summed per brand name, the top-1 gate with
two brands, the second-platform rule through Google Play RU, and the global platform judgment as the fallback of G3."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml

from nichefinder.stages import s6_ru
from nichefinder.workspace import Workspace

# niche -> (side, brands {query: (brand name, volume)})
NICHES = {
    "dup": ("b2c", {"gamma app": ("Gamma", 600), "gamma ai": ("Gamma", 500), "rival": ("Rival", 400)}),
    "duo": ("b2b-smb", {"leader": ("Leader", 9000), "other": ("Other", 1000)}),
    "duo-small": ("b2b-smb", {"leader": ("Leader", 900), "other": ("Other", 100)}),
    "duo-even": ("b2b-smb", {"leader": ("Leader", 6000), "other": ("Other", 4000)}),
    "android": ("b2c", {"big": ("Big", 8000), "b": ("B", 1000), "c": ("C", 1000)}),
    "android-b2b": ("b2b-smb", {"big": ("Big", 8000), "b": ("B", 1000), "c": ("C", 1000)}),
    "plat-global": ("b2c", {"x": ("X", 300), "y": ("Y", 300), "z": ("Z", 300)}),
    "plat-ru": ("b2c", {"x": ("X", 300), "y": ("Y", 300), "z": ("Z", 300)}),
}


def make_ws(tmp_path: Path) -> Workspace:
    (tmp_path / "nf.yaml").write_text(yaml.safe_dump({"markets": ["us", "ru"], "as_of": "2026-11-24"}), encoding="utf-8")
    (tmp_path / "niches.yaml").write_text(yaml.safe_dump([
        {"id": nid, "name": nid, "who": "w", "task": "t", "product": "p", "side": side, "tier": "A", "geo": "both"}
        for nid, (side, _) in NICHES.items()]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    queries, ws_rows = {}, []
    for nid, (_, brands) in NICHES.items():
        q = [{"q": f"{nid} program", "i": "category", "anchor": True}]
        ws_rows.append({"keyword": f"{nid} program", "niche_id": nid, "intent": "category", "anchor": 1, "total_count": 2000, "nested_json": "[]"})
        for kw, (b, vol) in brands.items():
            q.append({"q": kw, "i": "brand", "b": b})
            ws_rows.append({"keyword": kw, "niche_id": nid, "intent": "brand", "anchor": 0, "total_count": vol, "nested_json": "[]"})
        queries[nid] = {"ru": q}
    (tmp_path / "queries" / "q.yaml").write_text(yaml.safe_dump(queries, allow_unicode=True), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "overrides.yaml").write_text(yaml.safe_dump(
        {"plat-global": {"platform_risk": 2}, "plat-ru": {"platform_risk": 2}}), encoding="utf-8")
    (tmp_path / "config" / "overrides_ru.yaml").write_text(yaml.safe_dump({"plat-ru": {"platform": 0}}), encoding="utf-8")
    ws = Workspace(tmp_path)
    out = ws.out("wordstat_ru.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ws_rows[0]))
        w.writeheader()
        w.writerows(ws_rows)
    with open(ws.out("offsearch.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["niche_id", "gp_ru_top1_share", "gp_ru_players_100k"])
        w.writeheader()
        w.writerows([{"niche_id": n, "gp_ru_top1_share": 0.3, "gp_ru_players_100k": 10} for n in ("android", "android-b2b")])
    return ws


def test_calibrated_gates(tmp_path):
    ws = make_ws(tmp_path)
    s6_ru.run(ws, argparse.Namespace())
    r = {x["niche_id"]: x for x in csv.DictReader(open(ws.out("score_ru.csv"), encoding="utf-8"))}
    # two spellings of one brand are one brand: 1,100 of 1,500 searches, 2 brands
    assert (r["dup"]["ya_top1_brand"], r["dup"]["ya_n_brands"], r["dup"]["ya_top1_share"]) == ("Gamma", "2", "0.733")
    assert r["dup"]["gates"] == ""                                   # 2 brands, but under 5,000 searches
    assert r["duo"]["gates"] == "G2:top1" and r["duo"]["conc_src"] == "brands-2"   # 90% of 10,000
    assert r["duo-small"]["gates"] == "" and r["duo-even"]["gates"] == ""          # too little volume; 60% is no monopoly
    # second platform: a fragmented Google Play RU overrules the top-1 gate for B2C only
    assert (r["android"]["gates"], r["android"]["flags"]) == ("", "PASS:android")
    assert (r["android-b2b"]["gates"], r["android-b2b"]["flags"]) == ("G2:top1", "")
    # G3: the global platform judgment counts unless the Russian file says otherwise
    assert (r["plat-global"]["gates"], r["plat-global"]["platform_src"]) == ("G3:platform", "global")
    assert (r["plat-ru"]["gates"], r["plat-ru"]["platform_src"]) == ("", "ru")
    assert r["duo"]["verdict"] == "red" and r["android"]["verdict"] in ("green", "yellow")
    report = ws.report("S6-ru.md").read_text(encoding="utf-8")
    assert "PASS:android" in report
