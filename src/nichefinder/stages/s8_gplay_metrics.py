"""Google Play aggregates per niche and country from gplay_apps.csv.

installs_sum is the sum of maxInstalls over the relevant apps (Google Play reports installs worldwide, without a
country split; "country" is the storefront the app was found in); players_100k / players_1m count apps with
at least 100k / 1M installs; top1_share is the leader's share of installs; new_24m counts apps released within
24 months; ratings_sum sums ratings; paid_share is the share of apps with in-app purchases or a price.
Manual exclusions (platforms, marketplaces, games, neighbouring categories) live in config/gplay_exclude.yaml:
appId -> [niche ids], an empty list meaning every niche.

Input: data/out/gplay_apps.csv. Output: data/out/gplay_metrics.csv.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict

from nichefinder.workspace import Workspace

SUMMARY = "Google Play installs, players and concentration per niche"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
# Russian month abbreviations: Google Play prints release dates in the storefront language.
RU_MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}


def months_since(released, now):
    m = re.match(r"([A-Za-z]{3}) (\d{1,2}), (\d{4})", released or "")
    if not m:
        m2 = re.match(r"(\d{1,2}) ([а-яА-Я]+)\.? (\d{4})", released or "")
        if not m2:
            return None
        mon = RU_MONTHS.get(m2.group(2)[:3].lower())
        y = int(m2.group(3))
        if not mon:
            return None
        return max(1, (now.year - y) * 12 + (now.month - mon))
    mon, y = MONTHS[m.group(1)], int(m.group(3))
    return max(1, (now.year - y) * 12 + (now.month - mon))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def excluder(ws: Workspace):
    """Predicate for rows of gplay_apps.csv / snapshots that config/gplay_exclude.yaml removes.
    A key is an appId or its prefix (appIds can be truncated to 42 characters in reviews)."""
    excl = ws.load_config("gplay_exclude.yaml", {}) or {}

    def excluded(r):
        for k, niches in excl.items():
            if r["appId"] == k or (len(k) >= 40 and r["appId"].startswith(k)):
                return not niches or r["niche_id"] in niches
        return False
    return excluded


def run(ws: Workspace, args: argparse.Namespace) -> None:
    now = ws.today
    excluded = excluder(ws)
    rows = [r for r in csv.DictReader(open(ws.out("gplay_apps.csv"), encoding="utf-8-sig")) if not excluded(r)]
    by = defaultdict(list)
    for r in rows:
        by[(r["niche_id"], r["country"])].append(r)
    out = []
    for (nid, country), rs in sorted(by.items()):
        rs.sort(key=lambda r: -num(r["maxInstalls"]))
        inst = [num(r["maxInstalls"]) for r in rs]
        tot = sum(inst) or 1
        new = [r for r in rs if (months_since(r["released"], now) or 999) <= 24]
        paid = [r for r in rs if r["offersIAP"] == "true" or r["free"] == "false"]
        out.append({"niche_id": nid, "country": country, "apps": len(rs), "installs_sum": int(sum(inst)),
                    "players_100k": sum(1 for x in inst if x >= 100_000), "players_1m": sum(1 for x in inst if x >= 1_000_000),
                    "top1": rs[0]["title"][:40] if rs else "", "top1_share": round(inst[0] / tot, 3) if rs else "", "top3_share": round(sum(inst[:3]) / tot, 3) if rs else "",
                    "top_dev_share": round(max(sum(num(r["maxInstalls"]) for r in rs if r["developer"] == d) for d in {r["developer"] for r in rs}) / tot, 3) if rs else "",
                    "ratings_sum": int(sum(num(r["ratings"]) for r in rs)), "new_24m": len(new), "new_24m_installs": int(sum(num(r["maxInstalls"]) for r in new)),
                    "paid_share": round(len(paid) / len(rs), 2) if rs else ""})
        o = out[-1]
        print(f"{nid:36} {country} apps={o['apps']:>2} installs={o['installs_sum']:>12,} >=100k={o['players_100k']:>2} >=1M={o['players_1m']:>2} top1={o['top1_share']} new24={o['new_24m']} | {o['top1'][:30]}")
    p = ws.out("gplay_metrics.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("->", p, len(out))
