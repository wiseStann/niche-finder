"""New-entrant survival in the US App Store: fragmentation versus a factory of throwaway wrappers.

Cohort = relevant apps of a niche released 12-24 months before the run date (S5 `appstore_apps.csv`, relevant=1, store=us).
Metrics: share of the cohort updated within 180 / 90 days (are they alive) and share with >= 1k ratings (did they get traction).
Flags (picked up by s6_score, weights unchanged): E:churn - cohort >= 8 and fewer than 50% updated within 180 days;
E:traction - cohort >= 8 and >= 30% reached 1k ratings.

Input: data/out/appstore_apps.csv. Output: data/out/entrant_survival.csv. Free, no network.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
from collections import defaultdict

from nichefinder.workspace import Workspace

SUMMARY = "Survival of new App Store entrants (flags E:churn / E:traction)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def d(s):
    try:
        return dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def run(ws: Workspace, args: argparse.Namespace) -> None:
    ref = ws.today
    src = ws.out("appstore_apps.csv")
    if not src.is_file():
        raise SystemExit(f"{src} not found - run the S5 App Store stage first")
    by = defaultdict(list)
    for r in csv.DictReader(open(src, encoding="utf-8")):
        if r["store"] == "us" and r.get("relevant") in ("1", "True", "true"):
            by[r["niche_id"]].append(r)
    rows = []
    for nid, apps in sorted(by.items()):
        age = lambda a: (ref - d(a["release"])).days if d(a["release"]) else None  # noqa: E731
        coh = [a for a in apps if age(a) is not None and 365 <= age(a) <= 730]
        new12 = sum(1 for a in apps if age(a) is not None and age(a) < 365)
        row = {"niche_id": nid, "apps": len(apps), "new_12m": new12, "cohort_12_24m": len(coh),
               "upd_180d": None, "upd_90d": None, "share_1k": None, "flag": ""}
        if coh:
            upd = lambda days: sum(1 for a in coh if d(a["updated"]) and (ref - d(a["updated"])).days <= days) / len(coh)  # noqa: E731
            row["upd_180d"] = round(upd(180), 2)
            row["upd_90d"] = round(upd(90), 2)
            row["share_1k"] = round(sum(1 for a in coh if float(a["ratings"] or 0) >= 1000) / len(coh), 2)
            if len(coh) >= 8:
                if row["upd_180d"] < 0.5:
                    row["flag"] = "E:churn"
                elif row["share_1k"] >= 0.3:
                    row["flag"] = "E:traction"
        rows.append(row)
    if not rows:
        print("no relevant US App Store apps - nothing to write")
        return
    p = ws.out("entrant_survival.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for r in sorted(rows, key=lambda r: -r["new_12m"])[:25]:
        print(f"{r['niche_id']:36} new12={r['new_12m']:3} coh={r['cohort_12_24m']:3} upd180={r['upd_180d']} 1k={r['share_1k']} {r['flag']}")
    print("->", p)
