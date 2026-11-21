"""Russian reviews of the leading products of each shortlisted niche: App Store, Google Play and Startpack (no keys).

Which products: per niche (geo `both` or `ru`) and store, at most `fetch.apps_per_store` (config/ru_reviews.yaml):
- App Store RU: the relevant apps with the most ratings (at least `fetch.min_ratings`) from data/out/appstore_apps.csv
  (s5_appstore; store ru, relevant=1, after the manual edits in config/appstore_relevance.yaml);
- Google Play RU: the same from data/out/gplay_apps.csv (s8_gplay_details; country ru, the relevant set of s8_gplay_filter);
- the product check: the relevance of S5 and S8 is loose (a top search position, a substring such as "cookie" in
  CookieRun), and the most-rated candidates are often giants where the task is a side feature (Instagram for
  transcription, the Wildberries shopper app for seller analytics). So an LLM gets the niche (who, task, product) and the
  `fetch.fit_candidates` most-rated candidates per store (name, developer, store genre) and answers per app whether it
  is a product these users would choose or compare for the task. Only those are kept; `apps` in config/ru_reviews.yaml
  overrides it per niche (`keep` / `drop` lists of app ids). Every decision with its reason: data/out/ru_reviews_fit.csv;
- Startpack (startpack.ru, business software - the voice of B2B buyers that app stores do not have): the products listed
  for the niche in config/startpack_map.yaml (`apps`, in that order), then the products of its `categories` with the most
  reviews (at least `fetch.startpack_min_reviews`), minus `exclude`. Niches without an entry are not looked up.
How: App Store - the public customer-reviews RSS feed (itunes.apple.com/ru/rss/customerreviews/page=N/id=ID/
sortby=mostrecent/json), 50 newest reviews a page, `fetch.appstore_pages` pages at most (Apple serves 10).
Google Play - google-play-scraper through the Node helper gplay_reviews.mjs, the `fetch.gplay_reviews` newest reviews
in Russian; without Node this part is skipped with a note. Startpack - review pages sorted by date (sources/startpack.py),
`fetch.startpack_pages` pages of 50. Reviews without text are dropped, and so are reviews older than `fetch.window_months`
before the run date (`fetch.startpack_window_months` for Startpack: B2B products collect reviews more slowly).

Reviews keep coming, so the run month is part of every cache key: a re-run in the same month is free and offline, and
the next month fetches fresh reviews. Cache: data/cache/ru_reviews/ (App Store pages), data/cache/gplay_reviews/ (Node),
data/cache/startpack/ (HTML).
Output: data/out/ru_reviews_docs.jsonl (one line per review and niche: niche_id, store, app_id, app, id, date, rating,
title, text, version, thumbs), data/out/ru_reviews_apps.csv (per niche and app: store ratings, reviews fetched and
kept, the oldest kept review, status) and data/out/ru_reviews_fit.csv (the product check). A run with --niches replaces
only those niches in these files. The product check needs LLM_API_KEY (cached in data/cache/llm/, one call per niche).
Usage: nf run s10_ru_reviews_fetch -- [--niches a,b]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from collections import Counter, defaultdict

from nichefinder import appfit, http, niches, tools
from nichefinder.sources import startpack
from nichefinder.stages.s10_reddit_fetch import months_back
from nichefinder.workspace import Workspace

SUMMARY = "Russian reviews of each niche's leading products: App Store, Google Play, Startpack"
KEYS: tuple[str, ...] = ("LLM_API_KEY",)   # the product check of app store candidates
NEEDS: tuple[str, ...] = ()   # Node is optional: without it the Google Play part is skipped

CONFIG = "ru_reviews.yaml"
STARTPACK_MAP = "startpack_map.yaml"
DEFAULTS = {
    "fetch": {"window_months": 12, "apps_per_store": 8, "min_ratings": 20, "fit_candidates": 30, "appstore_pages": 10,
              "gplay_reviews": 500, "startpack_window_months": 36, "startpack_pages": 4, "startpack_min_reviews": 5},
    "sample": {"max_reviews": 240, "min_chars": 40},
    "verdict": {"min_app_reviews": 80, "min_apps": 2, "min_cohort": 6, "low_rating": 3, "min_low_reviews": 30, "gap_pct": 0.67,
                "gap_floor": 0.15, "paywall_pct": 0.67, "paywall_floor": 0.15, "quality_pct": 0.67, "quality_floor": 0.30,
                "content_praise": 0.50, "top_app_warn": 0.60},
}
RSS = "https://itunes.apple.com/ru/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
STORE_NAME = {"appstore": "App Store", "gplay": "Google Play", "startpack": "Startpack"}
DOCS, APPS, FIT, GPLAY_PLAN = "ru_reviews_docs.jsonl", "ru_reviews_apps.csv", "ru_reviews_fit.csv", "ru_reviews_gplay_plan.json"
APP_COLS = ["niche_id", "store", "app_id", "app", "developer", "ratings", "rating", "fetched", "kept", "oldest", "status"]
FIT_COLS = ["niche_id", "store", "app_id", "app", "developer", "genre", "ratings", "fit", "by", "why"]


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


def app_fit(ws: Workspace, niche: dict, cands: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    """The LLM product check of one niche's candidates (appfit.check): (store, app_id) -> (fit, why); fit is "yes",
    "no", or "" when the model gave no answer for the app."""
    return dict(zip(((c["store"], c["app_id"]) for c in cands), appfit.check(ws, niche, cands)))


def pick_apps(ws: Workspace, ids: list[str], st: dict) -> tuple[list[dict], list[dict]]:
    """The leading apps per niche and store that pass the product check: of the fit_candidates most-rated relevant apps
    with at least min_ratings ratings, the apps_per_store most-rated that fit. Returns (apps, product check rows)."""
    want, cand = set(ids), []
    p = ws.out("appstore_apps.csv")
    if p.is_file():
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            if r["store"] == "ru" and r["relevant"] == "1" and r["niche_id"] in want:
                cand.append({"niche_id": r["niche_id"], "store": "appstore", "app_id": r["track_id"], "app": r["name"],
                             "developer": r["seller"], "genre": r.get("genre", ""), "ratings": int(num(r["ratings"])),
                             "rating": num(r["rating"])})
    p = ws.out("gplay_apps.csv")
    if p.is_file():
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            if r["country"] == "ru" and r["niche_id"] in want:
                cand.append({"niche_id": r["niche_id"], "store": "gplay", "app_id": r["appId"], "app": r["title"],
                             "developer": r["developer"], "genre": r.get("genre", ""), "ratings": int(num(r["ratings"])),
                             "rating": num(r["score"])})
    by = defaultdict(dict)
    for c in cand:
        if c["ratings"] >= st["min_ratings"]:
            by[(c["niche_id"], c["store"])].setdefault(c["app_id"], c)
    meta = {n["id"]: n for n in niches.load_niches(ws)}
    manual = (ws.load_config(CONFIG, {}) or {}).get("apps") or {}
    out, fit_rows, unanswered = [], [], []
    for nid in ids:
        pools = {s: sorted(by[(nid, s)].values(), key=lambda c: -c["ratings"])[: int(st["fit_candidates"])]
                 for s in ("appstore", "gplay") if (nid, s) in by}
        cands = [c for pool in pools.values() for c in pool]
        if not cands:
            continue
        m = manual.get(nid) or {}
        keep, drop = {str(x) for x in m.get("keep") or []}, {str(x) for x in m.get("drop") or []}
        checked = app_fit(ws, meta.get(nid, {"id": nid}), cands)
        if all(fit == "" for fit, _ in checked.values()):
            unanswered.append(nid)
        for c in cands:
            fit, why = checked[(c["store"], c["app_id"])]
            by_whom = "llm"
            if c["app_id"] in keep or c["app_id"] in drop:
                fit, by_whom, why = ("yes" if c["app_id"] in keep else "no"), "config", "config/ru_reviews.yaml apps"
            c["fit"] = fit
            fit_rows.append({k: c.get(k, "") for k in FIT_COLS if k not in ("by", "why")} | {"by": by_whom, "why": why})
        for pool in pools.values():
            out += [c for c in pool if c["fit"] == "yes"][: int(st["apps_per_store"])]
    if fit_rows:
        print(f"product check: {sum(r['fit'] == 'yes' for r in fit_rows)} of {len(fit_rows)} app store candidates fit their niche "
              f"(reasons in {FIT})")
    if unanswered:
        print(f"!! the product check got no answer for {', '.join(unanswered)}: no app store reviews for them; run the stage again")
    return out, fit_rows


def startpack_apps(ws: Workspace, ids: list[str], st: dict, month: str) -> list[dict]:
    """Startpack products per niche from config/startpack_map.yaml: the listed `apps` first, then the products of its
    `categories` with the most reviews, minus `exclude`; at most apps_per_store. Ratings are filled in after the fetch."""
    smap = ws.load_config(STARTPACK_MAP, {}) or {}
    out = []
    for nid in ids:
        m = smap.get(nid) or {}
        if not isinstance(m, dict) or not (m.get("apps") or m.get("categories")):
            continue
        exclude = set(m.get("exclude") or [])
        known: dict[str, dict] = {}
        for cat in m.get("categories") or []:
            for a in startpack.category(ws, cat, month):
                known.setdefault(a["code"], a)
        listed = list(dict.fromkeys(str(c) for c in m.get("apps") or []))
        auto = [a["code"] for a in sorted(known.values(), key=lambda a: -a["reviews"])
                if a["reviews"] >= int(st["startpack_min_reviews"]) and a["code"] not in listed]
        for code in [c for c in listed + auto if c not in exclude][: int(st["apps_per_store"])]:
            a = known.get(code) or {}
            out.append({"niche_id": nid, "store": "startpack", "app_id": code, "app": a.get("name") or code, "developer": "",
                        "ratings": a.get("reviews", 0), "rating": a.get("stars", 0.0)})
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


def merge_write(ws: Workspace, ids: list[str], docs: list[dict], apps: list[dict], partial: bool,
                fit_rows: list[dict] | None = None) -> None:
    """Write the outputs; a partial run keeps the rows of the niches it did not touch."""
    redo = set(ids)
    dp = ws.out(DOCS)
    old_docs = [json.loads(x) for x in open(dp, encoding="utf-8")] if partial and dp.is_file() else []
    with open(dp, "w", encoding="utf-8") as fh:
        for r in [x for x in old_docs if x["niche_id"] not in redo] + docs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for name, cols, rows in ((APPS, APP_COLS, apps), (FIT, FIT_COLS, fit_rows or [])):
        p = ws.out(name)
        old = list(csv.DictReader(open(p, encoding="utf-8"))) if partial and p.is_file() else []
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows([x for x in old if x["niche_id"] not in redo] + rows)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: shortlisted niches with geo both/ru)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    st = settings(ws, "fetch")
    has_map = bool(ws.load_config(STARTPACK_MAP, {}))
    if not ws.out("appstore_apps.csv").is_file() and not ws.out("gplay_apps.csv").is_file() and not has_map:
        print("no appstore_apps.csv, gplay_apps.csv or config/startpack_map.yaml - run s5_appstore and the s8_gplay_* stages first")
        return
    ids = target_niches(ws, args.niches)
    month = f"{ws.today:%Y-%m}"
    store_apps, fit_rows = pick_apps(ws, ids, st)
    apps = store_apps + startpack_apps(ws, ids, st, month)
    if not apps:
        print(f"no Russian apps with >= {st['min_ratings']} ratings and no Startpack products for {len(ids)} niches with geo both/ru")
        return
    end = ws.today.isoformat()
    start = {"appstore": months_back(ws.today, int(st["window_months"])).isoformat()}
    start["gplay"] = start["appstore"]
    start["startpack"] = months_back(ws.today, int(st["startpack_window_months"])).isoformat()
    print(f"{len(apps)} products in {len({a['niche_id'] for a in apps})} niches; reviews from {start['appstore']} "
          f"(Startpack from {start['startpack']}) to {end}")
    fetched: dict[tuple[str, str], tuple[list[dict], str]] = {}
    for a in apps:
        key = (a["store"], a["app_id"])
        if key in fetched:
            continue
        if a["store"] == "appstore":
            fetched[key] = appstore_reviews(ws, a["app_id"], st["appstore_pages"], month)
        elif a["store"] == "startpack":
            items, status, meta = startpack.reviews(ws, a["app_id"], month, st["startpack_pages"], since=start["startpack"])
            fetched[key] = ([{**x, "text": startpack.review_text(x), "version": "", "thumbs": 0} for x in items], status)
            # The review page knows the name and the review count. Its aggregate rating is not the mean of the reviews
            # (NotiSend: 1.0 over 151 mostly positive reviews on 2026-11-20), so the mean of the fetched reviews is used.
            mean = round(sum(x["rating"] for x in items) / len(items), 2) if items else 0.0
            for b in apps:
                if b["store"] == "startpack" and b["app_id"] == a["app_id"]:
                    b.update(app=meta.get("name") or b["app"], ratings=meta.get("reviews") or b["ratings"], rating=mean)
    for app_id, res in gplay_reviews(ws, [a for a in apps if a["store"] == "gplay"], st["gplay_reviews"], month).items():
        fetched[("gplay", app_id)] = res
    docs, app_rows = [], []
    per_niche = defaultdict(Counter)
    for a in apps:
        items, status = fetched.get((a["store"], a["app_id"]), ([], "not fetched"))
        kept = [x for x in items if x["text"] and start[a["store"]] <= x["date"] <= end]
        for x in kept:
            docs.append({"niche_id": a["niche_id"], "store": a["store"], "app_id": a["app_id"], "app": a["app"],
                         **{k: x[k] for k in ("id", "date", "rating", "title", "text", "version", "thumbs")}})
        app_rows.append({**{k: a[k] for k in ("niche_id", "store", "app_id", "app", "developer", "ratings", "rating")},
                         "fetched": len(items), "kept": len(kept), "oldest": min((x["date"] for x in kept), default=""), "status": status})
        per_niche[a["niche_id"]][a["store"]] += len(kept)
    for nid in ids:
        if nid in per_niche:
            c = per_niche[nid]
            print(f"  {nid:36} App Store {c['appstore']:5}  Google Play {c['gplay']:5}  Startpack {c['startpack']:5}")
    merge_write(ws, ids, docs, app_rows, partial=bool(args.niches), fit_rows=fit_rows)
    bad = [r for r in app_rows if r["status"] != "ok"]
    print(f"-> {DOCS} ({len(docs)} reviews), {APPS} ({len(app_rows)} apps" + (f", {len(bad)} not fetched in full" if bad else "") + ")")
