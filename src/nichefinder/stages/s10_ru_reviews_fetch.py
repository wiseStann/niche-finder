"""Russian App Store and Google Play reviews of the leading apps of each shortlisted niche (no keys).

Which apps: per niche (geo `both` or `ru`) and store, the relevant apps with the most ratings, at most
`fetch.apps_per_store`, each with at least `fetch.min_ratings` ratings (config/ru_reviews.yaml):
- App Store RU: data/out/appstore_apps.csv from s5_appstore (store ru, relevant=1, after the manual edits in
  config/appstore_relevance.yaml);
- Google Play RU: data/out/gplay_apps.csv from s8_gplay_details (country ru, the relevant set of s8_gplay_filter).
How: App Store - the public customer-reviews RSS feed (itunes.apple.com/ru/rss/customerreviews/page=N/id=ID/
sortby=mostrecent/json), 50 newest reviews a page, `fetch.appstore_pages` pages at most (Apple serves 10).
Google Play - google-play-scraper through the Node helper gplay_reviews.mjs, the `fetch.gplay_reviews` newest reviews
in Russian. Without Node the Google Play part is skipped with a note. Reviews older than `fetch.window_months` before the
run date and reviews without text are dropped.

Reviews keep coming, so the run month is part of every cache key: a re-run in the same month is free and offline, and
the next month fetches fresh reviews. Cache: data/cache/ru_reviews/ (App Store pages), data/cache/gplay_reviews/ (Node).
Output: data/out/ru_reviews_docs.jsonl (one line per review and niche: niche_id, store, app_id, app, id, date, rating,
title, text, version, thumbs) and data/out/ru_reviews_apps.csv (per niche and app: store ratings, reviews fetched and
kept, the oldest kept review, status). A run with --niches replaces only those niches in both files.
Usage: nf run s10_ru_reviews_fetch -- [--niches a,b]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from collections import defaultdict

from nichefinder import http, niches, tools
from nichefinder.stages.s10_reddit_fetch import months_back
from nichefinder.workspace import Workspace

SUMMARY = "Russian App Store and Google Play reviews of each niche's leading apps"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()   # Node is optional: without it only the App Store part runs

CONFIG = "ru_reviews.yaml"
DEFAULTS = {
    "fetch": {"window_months": 12, "apps_per_store": 8, "min_ratings": 20, "appstore_pages": 10, "gplay_reviews": 500},
    "sample": {"max_reviews": 240, "min_chars": 40},
    "verdict": {"min_app_reviews": 80, "min_apps": 2, "min_cohort": 6, "gap_pct": 0.67, "gap_floor": 0.15,
                "quality_pct": 0.67, "quality_floor": 0.30, "content_praise": 0.50},
}
RSS = "https://itunes.apple.com/ru/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
STORE_NAME = {"appstore": "App Store", "gplay": "Google Play"}
DOCS, APPS, GPLAY_PLAN = "ru_reviews_docs.jsonl", "ru_reviews_apps.csv", "ru_reviews_gplay_plan.json"
APP_COLS = ["niche_id", "store", "app_id", "app", "developer", "ratings", "rating", "fetched", "kept", "oldest", "status"]


def settings(ws: Workspace, section: str) -> dict:
    """One block of config/ru_reviews.yaml over the defaults; the file is optional."""
    cfg = ws.load_config(CONFIG, {}) or {}
    return {**DEFAULTS[section], **(cfg.get(section) or {})}


def config_status(ws: Workspace) -> str:
    return str((ws.load_config(CONFIG, {}) or {}).get("status") or "draft")


def num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def target_niches(ws: Workspace, only: str = "") -> list[str]:
    """Shortlisted niches whose geo includes Russia, optionally restricted to a comma-separated list."""
    geo = {n["id"]: n.get("geo", "global") for n in niches.load_niches(ws)}
    ids = [i for i in niches.shortlist_ids(ws) if geo.get(i) in ("both", "ru")]
    if only:
        wanted = {x.strip() for x in only.split(",") if x.strip()}
        ids = [i for i in ids if i in wanted]
    return ids


def pick_apps(ws: Workspace, ids: list[str], st: dict) -> list[dict]:
    """The leading relevant apps per niche and store: at most apps_per_store, each with at least min_ratings ratings."""
    want, cand = set(ids), []
    p = ws.out("appstore_apps.csv")
    if p.is_file():
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            if r["store"] == "ru" and r["relevant"] == "1" and r["niche_id"] in want:
                cand.append({"niche_id": r["niche_id"], "store": "appstore", "app_id": r["track_id"], "app": r["name"],
                             "developer": r["seller"], "ratings": int(num(r["ratings"])), "rating": num(r["rating"])})
    p = ws.out("gplay_apps.csv")
    if p.is_file():
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            if r["country"] == "ru" and r["niche_id"] in want:
                cand.append({"niche_id": r["niche_id"], "store": "gplay", "app_id": r["appId"], "app": r["title"],
                             "developer": r["developer"], "ratings": int(num(r["ratings"])), "rating": num(r["score"])})
    by = defaultdict(dict)
    for c in cand:
        if c["ratings"] >= st["min_ratings"]:
            by[(c["niche_id"], c["store"])].setdefault(c["app_id"], c)
    order = {nid: i for i, nid in enumerate(ids)}
    out = []
    for key in sorted(by, key=lambda k: (order[k[0]], k[1])):
        out += sorted(by[key].values(), key=lambda c: -c["ratings"])[: int(st["apps_per_store"])]
    return out


def parse_rss(d: dict) -> list[dict]:
    """Reviews of one App Store RSS page. `entry` is a list, a single dict, or missing (no reviews)."""
    e = (d.get("feed") or {}).get("entry") or []
    if isinstance(e, dict):
        e = [e]

    def lab(x, k):
        v = x.get(k)
        return str(v.get("label") or "") if isinstance(v, dict) else ""

    out = []
    for x in e:
        if "im:rating" not in x:   # old feeds put the app itself first
            continue
        out.append({"id": lab(x, "id"), "date": lab(x, "updated")[:10], "rating": int(num(lab(x, "im:rating"))),
                    "title": lab(x, "title").strip(), "text": lab(x, "content").strip(), "version": lab(x, "im:version"),
                    "thumbs": int(num(lab(x, "im:voteSum")))})
    return out


def appstore_reviews(ws: Workspace, app_id: str, pages: int, month: str) -> tuple[list[dict], str]:
    """Newest reviews of one app in the Russian App Store; status 'ok' or the reason the fetch stopped early."""
    out = []
    for page in range(1, int(pages) + 1):
        try:
            d = http.get_json(RSS.format(page=page, app_id=app_id), cache=ws.cache("ru_reviews"),
                              cache_key=f"{month}|appstore|{app_id}|{page}", sleep=0.5, tries=3)
        except http.HttpError as e:
            if e.status == 400:   # past the last page Apple serves
                break
            return out, f"HTTP {e.status} on page {page}"
        except (OSError, ValueError) as e:
            return out, f"failed on page {page}: {str(e)[:60]}"
        items = parse_rss(d)
        out += items
        if len(items) < 50:
            break
    return out, "ok"


def gplay_reviews(ws: Workspace, apps: list[dict], num_reviews: int, month: str) -> dict[str, tuple[list[dict], str]]:
    """appId -> (reviews, status). Runs the Node helper for apps not cached this month; skips without Node."""
    ids = sorted({a["app_id"] for a in apps})
    if not ids:
        return {}
    cache = ws.cache("gplay_reviews")
    path = lambda a: cache / f"ru_{a}_{month}.json"  # noqa: E731
    missing = [a for a in ids if not path(a).is_file()]
    note = ""
    if missing:
        problem = tools.check("node", ws)
        if problem:
            note = "no node"
            print(f"  Google Play skipped for {len(missing)} apps: {problem}")
        else:
            ws.out(GPLAY_PLAN).write_text(json.dumps([{"appId": a, "num": int(num_reviews)} for a in missing], indent=1), encoding="utf-8")
            os.environ["NF_CACHE_DIR"] = str(ws.cache_root)
            try:
                tools.run_node(ws, "gplay_reviews.mjs", month)
            except subprocess.CalledProcessError as e:
                print(f"  gplay_reviews.mjs failed ({e.returncode}); using what is cached")
    out = {}
    for a in ids:
        p = path(a)
        if not p.is_file():
            out[a] = ([], note or "fetch failed")
            continue
        raw = json.loads(p.read_text(encoding="utf-8")).get("reviews") or []
        out[a] = ([{"id": str(x.get("id") or ""), "date": str(x.get("date") or "")[:10], "rating": int(num(x.get("score"))),
                    "title": (x.get("title") or "").strip(), "text": (x.get("text") or "").strip(),
                    "version": x.get("version") or "", "thumbs": int(num(x.get("thumbsUp")))} for x in raw], "ok")
    return out


def merge_write(ws: Workspace, ids: list[str], docs: list[dict], apps: list[dict], partial: bool) -> None:
    """Write both outputs; a partial run keeps the rows of the niches it did not touch."""
    redo = set(ids)
    dp, ap = ws.out(DOCS), ws.out(APPS)
    old_docs = [json.loads(x) for x in open(dp, encoding="utf-8")] if partial and dp.is_file() else []
    old_apps = list(csv.DictReader(open(ap, encoding="utf-8"))) if partial and ap.is_file() else []
    with open(dp, "w", encoding="utf-8") as fh:
        for r in [x for x in old_docs if x["niche_id"] not in redo] + docs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(ap, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=APP_COLS)
        w.writeheader()
        w.writerows([x for x in old_apps if x["niche_id"] not in redo] + apps)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: shortlisted niches with geo both/ru)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    st = settings(ws, "fetch")
    if not ws.out("appstore_apps.csv").is_file() and not ws.out("gplay_apps.csv").is_file():
        print("neither appstore_apps.csv nor gplay_apps.csv found - run s5_appstore and the s8_gplay_* stages first")
        return
    ids = target_niches(ws, args.niches)
    apps = pick_apps(ws, ids, st)
    if not apps:
        print(f"no Russian apps with >= {st['min_ratings']} ratings for {len(ids)} niches with geo both/ru - nothing to fetch")
        return
    month = f"{ws.today:%Y-%m}"
    start = months_back(ws.today, int(st["window_months"])).isoformat()
    end = ws.today.isoformat()
    print(f"{len(apps)} apps in {len({a['niche_id'] for a in apps})} niches; reviews from {start} to {end}")
    fetched: dict[tuple[str, str], tuple[list[dict], str]] = {}
    for a in apps:
        if a["store"] == "appstore" and ("appstore", a["app_id"]) not in fetched:
            fetched[("appstore", a["app_id"])] = appstore_reviews(ws, a["app_id"], st["appstore_pages"], month)
    for app_id, res in gplay_reviews(ws, [a for a in apps if a["store"] == "gplay"], st["gplay_reviews"], month).items():
        fetched[("gplay", app_id)] = res
    docs, app_rows = [], []
    per_niche = defaultdict(lambda: [0, 0])
    for a in apps:
        items, status = fetched.get((a["store"], a["app_id"]), ([], "not fetched"))
        kept = [x for x in items if x["text"] and start <= x["date"] <= end]
        for x in kept:
            docs.append({"niche_id": a["niche_id"], "store": a["store"], "app_id": a["app_id"], "app": a["app"], **x})
        app_rows.append({**{k: a[k] for k in ("niche_id", "store", "app_id", "app", "developer", "ratings", "rating")},
                         "fetched": len(items), "kept": len(kept), "oldest": min((x["date"] for x in kept), default=""), "status": status})
        per_niche[a["niche_id"]][0 if a["store"] == "appstore" else 1] += len(kept)
    for nid in ids:
        if nid in per_niche:
            n_as, n_gp = per_niche[nid]
            print(f"  {nid:36} App Store {n_as:5}  Google Play {n_gp:5}")
    merge_write(ws, ids, docs, app_rows, partial=bool(args.niches))
    bad = [r for r in app_rows if r["status"] != "ok"]
    print(f"-> {DOCS} ({len(docs)} reviews), {APPS} ({len(app_rows)} apps" + (f", {len(bad)} not fetched in full" if bad else "") + ")")
