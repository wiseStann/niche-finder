"""App Store supply: players, rating concentration, new apps and free share via the iTunes Search API.

For every shortlisted niche, the category queries (EN -> US store, RU -> RU store for geo `both`/`ru`) are searched
and merged by trackId; each app records in how many queries it appeared (hits) and its best position.
An app is relevant when it ranks in the top TOP_POS of at least one query (Apple orders by relevance) or appears in
3+ queries with a name that shares a token with the queries; config/appstore_relevance.yaml then adds manual
`exclude` / `include` lists of trackIds per niche and store.
Inputs: niches.yaml, queries/*.yaml, config/shortlist.yaml, config/appstore_relevance.yaml.
Outputs: data/out/appstore_apps.csv (all apps), data/out/appstore_review.md (top 25 per niche for an eyeball check).
Calls the free iTunes Search API (no key); responses are cached in data/cache/appstore/.
"""
from __future__ import annotations

import argparse
import csv
import re
import time
import urllib.parse

from nichefinder import http, niches
from nichefinder.workspace import Workspace

SUMMARY = "App Store players per niche (iTunes Search API, relevance by position + manual exclusions)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

MAX_Q = 6
TOP_POS = 15
STOP = {"app", "apps", "for", "the", "and", "with", "free", "best", "online", "ai", "tool", "tools", "software", "iphone",
        "приложение", "приложения", "для", "и", "с", "бесплатно", "ии", "программа", "сервис"}


def search(ws: Workspace, term: str, country: str) -> dict:
    u = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "entity": "software", "country": country, "limit": 200})
    for attempt in range(4):
        try:
            return http.get_json(u, cache=ws.cache("appstore"), cache_key=f"{country}|{term}", sleep=0.6,
                                 user_agent="Mozilla/5.0", tries=1)
        except Exception as e:  # noqa: BLE001
            print("  retry", term, e)
            time.sleep(5 * (attempt + 1))
    return {"results": []}


def tokens(q: str) -> set[str]:
    return {t for t in re.findall(r"[a-zа-яё0-9]+", q.lower()) if t not in STOP and len(t) > 2}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    all_niches = {x["id"]: x for x in niches.load_niches(ws)}
    ids = niches.shortlist_ids(ws)
    queries = niches.load_queries(ws)
    rel = ws.load_config("appstore_relevance.yaml", {}) or {}

    rows, review = [], ["# S5 App Store: top 25 apps per niche (relevance check)\n",
                        "hits - number of category queries the app appeared in; rel - whether it is in the relevant set "
                        "(edit `config/appstore_relevance.yaml`: `exclude`/`include` by trackId).\n"]
    for nid in ids:
        n = all_niches[nid]
        stores = [("us", "en")]
        if n.get("geo", "global") in ("both", "ru"):
            stores.append(("ru", "ru"))
        for country, lang in stores:
            cats = [e["q"] for e in queries[nid].get(lang, []) if e["i"] == "category"][:MAX_Q]
            if not cats:
                continue
            apps, qtok = {}, set()
            for q in cats:
                qtok |= tokens(q)
                for pos, a in enumerate(search(ws, q, country).get("results", []), 1):
                    tid = a["trackId"]
                    if tid not in apps:
                        apps[tid] = {"a": a, "hits": 0, "qs": [], "best_pos": pos}
                    apps[tid]["hits"] += 1
                    apps[tid]["qs"].append(q)
                    apps[tid]["best_pos"] = min(apps[tid]["best_pos"], pos)
            ov = (rel.get(nid) or {}).get(country) or {}
            excl, incl = set(ov.get("exclude") or []), set(ov.get("include") or [])
            for tid, rec in apps.items():
                a = rec["a"]
                name_tok = tokens(a.get("trackName", ""))
                # relevant: in the top TOP_POS of at least one query (Apple ranks by relevance),
                # or seen in 3+ queries with a name that overlaps the query tokens
                auto = rec["best_pos"] <= TOP_POS or (rec["hits"] >= 3 and bool(name_tok & qtok))
                relevant = (auto and tid not in excl) or tid in incl
                rows.append({
                    "niche_id": nid, "store": country, "track_id": tid, "name": a.get("trackName", ""),
                    "seller": a.get("sellerName", ""), "ratings": a.get("userRatingCount", 0),
                    "rating": a.get("averageUserRating", 0), "price": a.get("price", 0),
                    "release": (a.get("releaseDate") or "")[:10], "updated": (a.get("currentVersionReleaseDate") or "")[:10],
                    "genre": a.get("primaryGenreName", ""), "hits": rec["hits"], "best_pos": rec["best_pos"], "auto": int(auto), "relevant": int(relevant),
                    "queries": " | ".join(rec["qs"]),
                })
            top = sorted([r for r in rows if r["niche_id"] == nid and r["store"] == country and r["relevant"]], key=lambda r: -r["ratings"])[:25]
            review.append(f"\n## {nid} - {country} ({len(apps)} apps, queries: {', '.join(cats)})\n")
            review.append("| trackId | App | Developer | Ratings | Stars | $ | Released | hits | pos. | rel |")
            review.append("|---|---|---|---|---|---|---|---|---|---|")
            for r in top:
                review.append(f"| {r['track_id']} | {r['name'][:50]} | {r['seller'][:28]} | {r['ratings']:,} | {r['rating']:.1f} | {r['price']} | {r['release']} | {r['hits']} | {r['best_pos']} | {'✓' if r['relevant'] else ''} |")
            print(f"{nid:36} {country} apps={len(apps):3} relevant={sum(1 for r in rows if r['niche_id']==nid and r['store']==country and r['relevant'])}")

    if not rows:
        print("no apps found - nothing written")
        return
    out = ws.out("appstore_apps.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    ws.out("appstore_review.md").write_text("\n".join(review), encoding="utf-8")
    print("->", out, len(rows), "rows")
