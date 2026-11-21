"""Competitor site history from the Wayback Machine: how old the niche's leaders are and how many competitors went quiet.

Competitors are the relevant App Store US apps of each shortlisted niche (data/out/appstore_apps.csv, S5), top --top by
ratings; their websites come from the iTunes `sellerUrl` field already in the S5 cache (data/cache/appstore/), so no new
store calls are made. Platform and link-in-bio domains (config list below) are skipped. For each domain the Wayback CDX
API (web.archive.org/cdx, free, no key; one request per domain, captures collapsed to one per month) gives the first
capture (site age), the last capture with HTTP 200 and the number of months with captures in the last 24.

Per niche: domains measured, median age of the top-5 apps' sites (how entrenched the leaders are), share of sites first
seen within 3 years (new entrants on the web), share of sites without a 200 capture in the last 12 months (quiet or dead).
S9 entrant survival measures the App Store cohort; this adds the web side and needs no second snapshot.
Output: data/out/wayback.csv (per niche), wayback_domains.csv (per domain). Cache: data/cache/wayback/, per month.
Caveats: the archive crawls popular sites more often, so "quiet" can mean "rarely crawled" for tiny sites; a developer
site is the company's, not the app's, so a studio with many apps counts with its company age.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import statistics
import time
from urllib.parse import quote, urlparse

from nichefinder import http, niches
from nichefinder.workspace import Workspace

SUMMARY = "Competitor site history from the Wayback Machine: age and liveness"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

CDX = "https://web.archive.org/cdx/search/cdx?url={d}&output=json&fl=timestamp,statuscode&collapse=timestamp:6"
SKIP = ("apple.com", "google.com", "facebook.com", "instagram.com", "linktr.ee", "github.io", "github.com", "notion.site",
        "wixsite.com", "carrd.co", "blogspot.com", "wordpress.com", "medium.com", "twitter.com", "x.com", "tiktok.com",
        "youtube.com", "linkedin.com", "apps.apple.com", "bit.ly", "sites.google.com", "about.me", "t.me", "vk.com")


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--top", type=int, default=10, help="apps per niche by ratings (default 10)")


def seller_urls(ws: Workspace) -> dict[str, str]:
    """trackId -> sellerUrl from the iTunes responses cached by S5."""
    out: dict[str, str] = {}
    for f in glob.glob(str(ws.cache("appstore") / "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in ((d.get("results") or []) if isinstance(d, dict) else []):
            if r.get("sellerUrl") and r.get("trackId"):
                out[str(r["trackId"])] = r["sellerUrl"]
    return out


def domain(url: str) -> str:
    d = urlparse(url if "//" in url else "//" + url).netloc.lower().split(":")[0]
    return d[4:] if d.startswith("www.") else d


def skip(d: str) -> bool:
    return not d or "." not in d or any(d == s or d.endswith("." + s) for s in SKIP)


def history(ws: Workspace, d: str) -> list[tuple[str, str]]:
    """[(yyyymm, status)] per month with captures."""
    try:
        data = http.get_json(CDX.format(d=quote(d)), cache=ws.cache("wayback"), cache_key=f"{d}_{ws.today:%Y-%m}",
                             timeout=90, tries=2, user_agent=http.BOT_UA)
    except (OSError, ValueError, http.HttpError) as e:
        print(f"    {d}: {str(e)[:100]}")
        return []
    rows = data[1:] if data and data[0] and data[0][0] == "timestamp" else data or []
    return [(r[0][:6], r[1]) for r in rows if r and len(r) >= 2]


def domain_stats(h: list[tuple[str, str]], today: dt.date) -> dict:
    if not h:
        return {"first": "", "last_ok": "", "age_years": "", "months_24": 0, "alive": ""}
    ym = lambda s: int(s[:4]) * 12 + int(s[4:6]) - 1  # noqa: E731
    now = today.year * 12 + today.month - 1
    ok = [m for m, s in h if s == "200"]
    first = min(m for m, _ in h)
    last_ok = max(ok) if ok else ""
    return {"first": f"{first[:4]}-{first[4:]}", "last_ok": f"{last_ok[:4]}-{last_ok[4:]}" if last_ok else "",
            "age_years": round((now - ym(first)) / 12, 1), "months_24": sum(1 for m, _ in h if now - ym(m) < 24),
            "alive": int(bool(last_ok) and now - ym(last_ok) < 12)}


def niche_row(nid: str, doms: list[dict]) -> dict:
    meas = [x for x in doms if x["age_years"] != ""]
    top5 = [x["age_years"] for x in meas if x["rank"] <= 5]
    young = sum(1 for x in meas if x["age_years"] < 3)
    quiet = sum(1 for x in meas if x["alive"] == 0)
    return {"niche_id": nid, "domains": len(doms), "measured": len(meas),
            "leaders_age_median": round(statistics.median(top5), 1) if top5 else "",
            "young_share": round(young / len(meas), 2) if meas else "", "quiet_share": round(quiet / len(meas), 2) if meas else "",
            "oldest": max(meas, key=lambda x: x["age_years"])["domain"] if meas else "",
            "youngest": min(meas, key=lambda x: x["age_years"])["domain"] if meas else ""}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    src = ws.out("appstore_apps.csv")
    if not src.is_file():
        print(f"{src} not found - run s5_appstore first; skipping")
        return
    urls = seller_urls(ws)
    ids = set(niches.shortlist_ids(ws))
    apps: dict[str, list[dict]] = {}
    for r in csv.DictReader(open(src, encoding="utf-8")):
        if r["niche_id"] in ids and r.get("store") == "us" and r.get("relevant") in ("1", "True", "true"):
            apps.setdefault(r["niche_id"], []).append(r)
    rows, drows, seen = [], [], {}
    for nid, lst in apps.items():
        lst.sort(key=lambda r: -int(float(r.get("ratings") or 0)))
        doms, rank = [], 0
        for r in lst:
            d = domain(urls.get(str(r["track_id"]), ""))
            rank += 1
            if skip(d) or any(x["domain"] == d for x in doms):
                continue
            if d not in seen:
                live = not http.cache_file(ws.cache("wayback"), f"{d}_{ws.today:%Y-%m}").is_file()
                seen[d] = domain_stats(history(ws, d), ws.today)
                if live:
                    time.sleep(1.0)
            doms.append({"niche_id": nid, "rank": rank, "app": r["name"], "domain": d, **seen[d]})
            if len(doms) >= args.top:
                break
        if doms:
            rows.append(niche_row(nid, doms))
            drows += doms
            x = rows[-1]
            print(f"  {nid:36} {x['measured']:2}/{x['domains']:2} sites, leaders' age {x['leaders_age_median']!s:>5} y, "
                  f"young {x['young_share']!s:>4}, quiet {x['quiet_share']!s:>4}", flush=True)
    if not rows:
        print("no competitor websites found - nothing written")
        return
    with open(ws.out("wayback.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("wayback_domains.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(drows[0].keys()))
        w.writeheader()
        w.writerows(drows)
    print(f"-> wayback.csv {len(rows)}, wayback_domains.csv {len(drows)}")
