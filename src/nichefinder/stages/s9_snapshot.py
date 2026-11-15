"""Supply snapshots over time: direct growth of App Store ratings and Google Play installs/ratings.

S8 estimates rating velocity indirectly (ratings / months since release). A second snapshot taken a while later
(30 days or more) gives the real growth per app and per niche: who is growing, whether new players take share,
whether the niche as a whole is expanding.

Subcommands (`nf run s9_snapshot -- <command> [--date D] [--base B]`):
  freeze    freeze the current appstore_apps.csv / gplay_apps.csv of the shortlist into data/snapshots/<date>/
            (date = the run date unless --date is given)
  refresh   fresh App Store ratings for the apps of the base snapshot (iTunes lookup, 150 ids per call, no key)
            -> data/snapshots/<date>/appstore.csv; --base defaults to the earliest snapshot
  diff      growth per app and niche between two snapshots (--base, default the earliest; --date, default the latest)
            -> data/out/snapshot_diff_<date>.csv, data/out/snapshot_diff_apps_<date>.csv, reports/S9-snapshot-<date>.md

Google Play is refreshed by the separate stage s9_gplay_refresh. Cost: $0.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import time
from collections import defaultdict

from nichefinder import http, niches
from nichefinder.stages.s8_appstore_velocity import reviewed_ru
from nichefinder.stages.s8_gplay_metrics import excluder
from nichefinder.workspace import Workspace

SUMMARY = "Freeze, refresh and diff supply snapshots (App Store, Google Play)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

AS_FIELDS = ["niche_id", "store", "track_id", "name", "seller", "ratings", "release"]
GP_FIELDS = ["niche_id", "country", "appId", "title", "developer", "maxInstalls", "ratings", "released"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("command", choices=["freeze", "refresh", "diff"], help="what to do")
    parser.add_argument("--date", default="", help="snapshot date YYYY-MM-DD (freeze/refresh: default the run date; diff: default the latest snapshot)")
    parser.add_argument("--base", default="", help="base snapshot date (refresh/diff: default the earliest snapshot)")


def f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def snapshot_dates(ws: Workspace) -> list[str]:
    return sorted(p.name for p in ws.snapshots().iterdir() if p.is_dir())


def freeze(ws: Workspace, date: str) -> None:
    d = ws.snapshots(date)
    d.mkdir(parents=True, exist_ok=True)
    ids = set(niches.shortlist_ids(ws))
    rel = ws.load_config("appstore_relevance.yaml", {}) or {}
    reviewed = reviewed_ru(ws)   # the RU result set is cleaned by hand only for these niches
    rows = []
    for r in csv.DictReader(open(ws.out("appstore_apps.csv"), encoding="utf-8")):
        na = (rel.get(r["niche_id"], {}).get(r["store"], {}) or {}).get("na")
        if r["niche_id"] in ids and r["relevant"] == "1" and not na and (r["store"] == "us" or r["niche_id"] in reviewed):
            rows.append({k: r[k] for k in AS_FIELDS})
    with open(d / "appstore.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=AS_FIELDS)
        w.writeheader()
        w.writerows(rows)
    excluded = excluder(ws)
    g = [{k: r[k] for k in GP_FIELDS} for r in csv.DictReader(open(ws.out("gplay_apps.csv"), encoding="utf-8-sig"))
         if r["niche_id"] in ids and not excluded(r)]
    with open(d / "gplay.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=GP_FIELDS)
        w.writeheader()
        w.writerows(g)
    print(f"-> {d}: appstore {len(rows)} apps, gplay {len(g)}")


def refresh(ws: Workspace, base_date: str, date: str) -> None:
    """Fresh App Store ratings for the base snapshot's apps via iTunes lookup (150 ids per call, no key)."""
    base_date = base_date or snapshot_dates(ws)[0]
    base = list(csv.DictReader(open(ws.snapshots(base_date) / "appstore.csv", encoding="utf-8")))
    d = ws.snapshots(date)
    d.mkdir(parents=True, exist_ok=True)
    cache = ws.cache(f"appstore_lookup_{date}")
    by_store = defaultdict(set)
    for r in base:
        by_store[r["store"]].add(r["track_id"])
    fresh = {}
    for store, ids in by_store.items():
        ids = sorted(ids)
        for i in range(0, len(ids), 150):
            batch = ids[i:i + 150]
            key = cache / f"{store}_{i}.json"
            if key.exists():
                data = json.loads(key.read_text(encoding="utf-8"))
            else:
                u = f"https://itunes.apple.com/lookup?id={','.join(batch)}&country={store}"
                try:
                    data = http.request(u, user_agent="Mozilla/5.0", timeout=60, tries=4, backoff=(5, 10, 15, 20)).json()
                except (OSError, http.HttpError, ValueError) as e:
                    print("  failed", store, i, e)
                    continue
                key.write_text(json.dumps(data), encoding="utf-8")
                time.sleep(1.0)
            for a in data.get("results", []):
                fresh[(store, str(a.get("trackId")))] = {"ratings": a.get("userRatingCount", 0), "name": a.get("trackName", "")}
            print(f"  {store} {min(i + 150, len(ids))}/{len(ids)}")
    rows = []
    for r in base:
        x = fresh.get((r["store"], r["track_id"]))
        rows.append({**r, "ratings": x["ratings"] if x else "", "name": x["name"] if x else r["name"]})
    with open(d / "appstore.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=AS_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"-> {d}/appstore.csv: {sum(1 for r in rows if r['ratings'] != '')}/{len(rows)} updated (empty ones are no longer on sale)")


def months_between(d0, d1):
    a, b = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)
    return max(1e-9, (b - a).days / 30.44)


def diff(ws: Workspace, d0: str, d1: str) -> None:
    dates = snapshot_dates(ws)
    d0, d1 = d0 or dates[0], d1 or dates[-1]
    if d0 == d1:
        raise SystemExit("two snapshots are needed: `freeze` now and `refresh` later")
    months = months_between(d0, d1)
    names = niches.niche_names(ws)
    apps_out, niche = [], defaultdict(lambda: defaultdict(float))
    for src, key, val in (("appstore", ("store", "track_id"), "ratings"), ("gplay", ("country", "appId"), "ratings")):
        p0, p1 = ws.snapshots(d0) / f"{src}.csv", ws.snapshots(d1) / f"{src}.csv"
        if not (p0.exists() and p1.exists()):
            print("no", src, "in one of the snapshots - skipped")
            continue
        a0 = {(r["niche_id"], r[key[0]], r[key[1]]): r for r in csv.DictReader(open(p0, encoding="utf-8"))}
        a1 = {(r["niche_id"], r[key[0]], r[key[1]]): r for r in csv.DictReader(open(p1, encoding="utf-8"))}
        for k, r0 in a0.items():
            r1 = a1.get(k)
            if not r1 or r1[val] == "":
                continue
            gained = f(r1[val]) - f(r0[val])
            inst = (f(r1.get("maxInstalls")) - f(r0.get("maxInstalls"))) if src == "gplay" else None
            rel = r0.get("release") or r0.get("released") or ""
            new24 = False
            try:
                y = int(rel[:4]) if rel[:4].isdigit() else int(rel.strip()[-4:])
                new24 = (dt.date.fromisoformat(d1).year - y) * 12 <= 24
            except ValueError:
                pass
            apps_out.append({"niche_id": k[0], "src": src, "geo": k[1], "id": k[2], "name": (r1.get("name") or r1.get("title") or "")[:60],
                             "v0": int(f(r0[val])), "v1": int(f(r1[val])), "gained": int(gained), "gained_pm": round(gained / months, 1),
                             "installs_gained": int(inst) if inst is not None else "", "new24": int(new24)})
            n = niche[(k[0], src, k[1])]
            n["gained"] += gained
            n["v0"] += f(r0[val])
            n["apps"] += 1
            if new24:
                n["gained_new"] += gained
            n["leader_gained"] = max(n["leader_gained"], gained)
            if src == "gplay" and inst is not None:
                n["installs_gained"] += inst
    if not apps_out:
        raise SystemExit(f"no apps present in both snapshots {d0} and {d1}")
    apps_out.sort(key=lambda r: -r["gained"])
    with open(ws.out(f"snapshot_diff_apps_{d1}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(apps_out[0].keys()))
        w.writeheader()
        w.writerows(apps_out)
    rows = []
    for (nid, src, geo), n in sorted(niche.items(), key=lambda kv: -kv[1]["gained"]):
        rows.append({"niche_id": nid, "src": src, "geo": geo, "apps": int(n["apps"]), "base": int(n["v0"]), "gained": int(n["gained"]),
                     "gained_pm": round(n["gained"] / months, 1), "growth_pct": round(100 * n["gained"] / n["v0"], 2) if n["v0"] else "",
                     "new24_share": round(n["gained_new"] / n["gained"], 3) if n["gained"] > 0 else "", "leader_share": round(n["leader_gained"] / n["gained"], 3) if n["gained"] > 0 else "",
                     "installs_gained": int(n["installs_gained"]) if src == "gplay" else ""})
    with open(ws.out(f"snapshot_diff_{d1}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    L = [f"# S9: supply snapshot {d0} -> {d1} ({months:.1f} months)", "",
         "Direct growth of ratings (App Store US/RU) and ratings/installs (Google Play US/RU) over the relevant apps of the shortlist. "
         "\"New\" means apps at most 24 months old at the date of the second snapshot; \"leader\" is the share of the fastest-growing app in the niche's growth.", "",
         "| Niche | Source | Geo | Apps | Base | Gained | Per month | Growth, % | New share | Leader share | Installs + |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {names.get(r['niche_id'], r['niche_id'])} `{r['niche_id']}` | {r['src']} | {r['geo']} | {r['apps']} | {r['base']:,} | {r['gained']:,} | {r['gained_pm']:,} | {r['growth_pct']} | {r['new24_share']} | {r['leader_share']} | {r['installs_gained']} |")
    L += ["", "## Top 30 apps by growth", "", "| Niche | Source | Geo | App | Before | After | Gained | Per month | New |", "|---|---|---|---|---|---|---|---|---|"]
    for r in apps_out[:30]:
        L.append(f"| {r['niche_id']} | {r['src']} | {r['geo']} | {r['name']} | {r['v0']:,} | {r['v1']:,} | {r['gained']:,} | {r['gained_pm']:,} | {'yes' if r['new24'] else ''} |")
    ws.report(f"S9-snapshot-{d1}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"-> snapshot_diff_{d1}.csv ({len(rows)} rows), snapshot_diff_apps_{d1}.csv ({len(apps_out)}), reports/S9-snapshot-{d1}.md")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    if args.command == "freeze":
        freeze(ws, args.date or ws.today.isoformat())
    elif args.command == "refresh":
        refresh(ws, args.base, args.date or ws.today.isoformat())
    else:
        diff(ws, args.base, args.date)
