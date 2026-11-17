"""Hacker News per shortlisted niche: Show HN launches and Ask HN questions (Algolia HN Search API).

Search terms are the niche's Latin-script phrases in config/coverage_keywords.yaml (HN is English). Each term is
searched as an exact phrase in titles (no typo tolerance) among Show HN and Ask HN posts of the last 36 months, one
request per term with up to 1,000 hits. A hit is kept only when its title matches the niche's regex
(niches.text_matchers: deal_keywords, else the coverage phrases), which removes homonyms; hits are deduplicated across
terms by item id. General news stories and post bodies are left out on purpose: their titles and texts mention a
niche's words in passing ("lifting the veil", "LaTeX salon"), while a Show HN title names a product and an Ask HN title
names a question.

Outputs: data/out/hn_niche.csv - Show HN and Ask HN posts in the last 12 months and the 12 before, posts over 36
months, points and comments of the last 12 months, hn_trend, capped (a term exceeded 1,000 hits: counts are a lower
bound), top_show, top_ask; data/out/hn_matches.csv - every kept post (niche_id, kind, date, points, comments, title,
url, hn_url) for review.

hn_trend, fixed before the first run, over Show HN + Ask HN posts: NA when posts_12m + posts_prev12m < 10; UP when
posts_12m / posts_prev12m >= 1.25; DOWN when <= 0.8; FLAT otherwise. The audience is developers: B2C verticals
(gardeners, churches, tattoo studios) are barely represented, so a low count means NA, not "no demand".
No keys; Algolia allows 10,000 requests an hour; 0.3 s between live requests; one request per search term.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import urllib.parse

from nichefinder import http, niches
from nichefinder.workspace import Workspace

SUMMARY = "Hacker News per niche: Show HN launches and Ask HN questions with a trend (Algolia API)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

API = "https://hn.algolia.com/api/v1/search"
CAP = 1000
LATIN = re.compile(r"^[\x20-\x7e]+$")


def hn_trend(last: int, prev: int) -> str:
    if last + prev < 10:
        return "NA"
    if prev == 0 or last / prev >= 1.25:
        return "UP"
    return "DOWN" if last / prev <= 0.8 else "FLAT"


def kind(tags: list[str]) -> str:
    return "show" if "show_hn" in tags else "ask"


def search(ws: Workspace, term: str, since_ts: int, stamp: str) -> dict:
    params = {"query": f'"{term}"', "tags": "(show_hn,ask_hn)", "hitsPerPage": CAP, "numericFilters": f"created_at_i>{since_ts}",
              "typoTolerance": "false", "restrictSearchableAttributes": "title",
              "attributesToRetrieve": "title,url,points,num_comments,created_at_i,_tags", "attributesToHighlight": "none"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    return http.get_json(url, cache=ws.cache("hn"), cache_key=f"{stamp}|{url}", user_agent=http.BOT_UA, timeout=60, sleep=0.3)


def run(ws: Workspace, args: argparse.Namespace) -> None:
    ids = niches.shortlist_ids(ws)
    match = niches.text_matchers(ws, ids)
    cov = ws.load_config("coverage_keywords.yaml", {}) or {}
    now = dt.datetime.combine(ws.today, dt.time.max, tzinfo=dt.timezone.utc)
    t36, t24, t12 = (int((now - dt.timedelta(days=d)).timestamp()) for d in (1095, 730, 365))
    stamp = f"{ws.today:%Y-%m}"   # posts keep arriving: cache per month of the run
    rows, kept = [], []
    for nid in ids:
        terms = [str(t) for t in cov.get(nid, []) if LATIN.match(str(t)) and len(str(t)) >= 3]
        if not terms or nid not in match:
            print(f"{nid:36} no Latin coverage phrases - skipped")
            continue
        items: dict[str, dict] = {}
        capped = False
        for term in terms:
            try:
                a = search(ws, term, t36, stamp)
            except (http.HttpError, OSError, ValueError) as e:
                print(f"  ! {nid} '{term}': {e}")
                continue
            capped = capped or a.get("nbHits", 0) > CAP
            for h in a.get("hits", []):
                if h["objectID"] not in items and match[nid](h.get("title") or ""):
                    items[h["objectID"]] = h
        hits = list(items.values())
        last = [h for h in hits if h["created_at_i"] > t12]
        prev = [h for h in hits if t24 < h["created_at_i"] <= t12]

        def count(seq, k):
            return sum(1 for h in seq if kind(h.get("_tags") or []) == k)

        def top(k):
            best = max((h for h in last if kind(h.get("_tags") or []) == k), key=lambda h: h.get("points") or 0, default=None)
            return f"{best['title'][:90]} ({best.get('points') or 0} points)" if best else ""

        row = {"niche_id": nid, "terms": len(terms),
               "show_12m": count(last, "show"), "show_prev12m": count(prev, "show"),
               "ask_12m": count(last, "ask"), "ask_prev12m": count(prev, "ask"),
               "posts_12m": len(last), "posts_prev12m": len(prev), "posts_36m": len(hits),
               "points_12m": sum(h.get("points") or 0 for h in last), "comments_12m": sum(h.get("num_comments") or 0 for h in last),
               "hn_trend": hn_trend(len(last), len(prev)), "capped": int(capped), "top_show": top("show"), "top_ask": top("ask")}
        rows.append(row)
        for h in sorted(hits, key=lambda h: -h["created_at_i"]):
            kept.append({"niche_id": nid, "kind": kind(h.get("_tags") or []), "date": dt.datetime.fromtimestamp(h["created_at_i"], dt.timezone.utc).date().isoformat(),
                         "points": h.get("points") or 0, "comments": h.get("num_comments") or 0, "title": (h.get("title") or "")[:120],
                         "url": h.get("url") or "", "hn_url": f"https://news.ycombinator.com/item?id={h['objectID']}"})
        print(f"{nid:36} posts 12m={row['posts_12m']:3} prev={row['posts_prev12m']:3} -> {row['hn_trend']:4} show={row['show_12m']:3} ask={row['ask_12m']:3}"
              + (" (capped)" if capped else ""))
    if not rows:
        print("no shortlisted niche has Latin coverage phrases - nothing written")
        return
    with open(ws.out("hn_niche.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("hn_matches.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "kind", "date", "points", "comments", "title", "url", "hn_url"])
        w.writeheader()
        w.writerows(kept)
    print(f"-> data/out/hn_niche.csv ({len(rows)} niches), data/out/hn_matches.csv ({len(kept)} posts)")
