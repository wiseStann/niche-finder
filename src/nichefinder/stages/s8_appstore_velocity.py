"""App Store rating velocity: how fast new apps collect ratings, the pull of new entrants.

From appstore_apps.csv (the relevant app set from S5), for every app: ratings per month since release
(ratings / months_since_release). Per niche and store: new_24m = apps released within 24 months;
new_24m_ratings_pm = their combined velocity (ratings/month); new_share = share of the niche's velocity
that comes from new apps; vel_total_pm = combined velocity of all relevant apps; vel_median_pm_top20 =
median velocity of the top 20. It is one point in time; a second snapshot (stage s9_snapshot) gives direct growth.

Only (niche, store) pairs where the App Store is a place to sell and the result set is cleaned are used:
all US pairs, and RU pairs for niches listed in config/appstore_ru_reviewed.yaml (a list of niche ids whose
Russian results were reviewed by hand).

Input: data/out/appstore_apps.csv, data/out/appstore_metrics.csv. Output: data/out/appstore_velocity.csv.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict

from nichefinder.workspace import Workspace

SUMMARY = "App Store rating velocity and share of new entrants"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def reviewed_ru(ws: Workspace) -> set[str]:
    """Niches whose Russian App Store results were cleaned by hand (config/appstore_ru_reviewed.yaml, a list)."""
    return set(ws.load_config("appstore_ru_reviewed.yaml", []) or [])


def months(d, now):
    try:
        y, m, _ = (int(x) for x in d[:10].split("-"))
    except ValueError:
        return None
    return max(1, (now.year - y) * 12 + (now.month - m))


def run(ws: Workspace, args: argparse.Namespace) -> None:
    now = ws.today
    reviewed = reviewed_ru(ws)
    ok = set()   # only (niche, store) pairs where the App Store is a place to sell and the result set is cleaned
    for m in csv.DictReader(open(ws.out("appstore_metrics.csv"), encoding="utf-8")):
        if m.get("na") != "1" and (m["store"] == "us" or m["niche_id"] in reviewed):
            ok.add((m["niche_id"], m["store"]))
    rows = [r for r in csv.DictReader(open(ws.out("appstore_apps.csv"), encoding="utf-8"))
            if r["relevant"] == "1" and (r["niche_id"], r["store"]) in ok]
    by = defaultdict(list)
    for r in rows:
        m = months(r["release"], now)
        if m is None:
            continue
        r["_pm"] = int(r["ratings"] or 0) / m
        r["_new"] = m <= 24
        by[(r["niche_id"], r["store"])].append(r)
    out = []
    for (nid, store), rs in sorted(by.items()):
        rs.sort(key=lambda r: -r["_pm"])
        tot = sum(r["_pm"] for r in rs)
        new = [r for r in rs if r["_new"]]
        new_pm = sum(r["_pm"] for r in new)
        top20 = [r["_pm"] for r in rs[:20]]
        out.append({"niche_id": nid, "store": store, "apps": len(rs), "vel_total_pm": round(tot), "vel_median_pm_top20": round(sorted(top20)[len(top20) // 2]) if top20 else 0,
                    "new_24m": len(new), "new_24m_ratings_pm": round(new_pm), "new_share": round(new_pm / tot, 3) if tot else "",
                    "fastest": rs[0]["name"][:40] if rs else "", "fastest_pm": round(rs[0]["_pm"]) if rs else 0,
                    "fastest_new": new[0]["name"][:40] if new else "", "fastest_new_pm": round(new[0]["_pm"]) if new else 0})
        print(f"{nid:36} {store} vel={out[-1]['vel_total_pm']:>7}/mo new24={len(new):>2} new_pm={out[-1]['new_24m_ratings_pm']:>6} share={out[-1]['new_share']} | {out[-1]['fastest_new'][:30]} {out[-1]['fastest_new_pm']}")
    p = ws.out("appstore_velocity.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("->", p, len(out))
