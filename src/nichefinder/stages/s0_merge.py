"""S0: merge all raw source files into one universe table, data/out/universe.csv.

Reads data/raw/*.csv written by the S0 fetch stages (a missing file is skipped with a note) and maps every entity to
one schema: entity, source, source_type, geo, side, category, one_liner, signal, url, niche_id.

Sources and their source_type: YC, Product Hunt, BetaList and Product Radar (geo ru) = rising; TinySeed, App Store
top-grossing, Google Play top-grossing, WordPress plugins (>= 5000 active installs), Shopify apps and successful
Kickstarter projects with >= 200 backers (paid in advance) = proven; Empire Flippers software and digital listings
(verified P&L, for sale and sold) = transactions; Google Play top-free = usage.
Google Play lists are cut at rank 150.

Optional user-provided imports (no fetcher exists; put the CSV in data/raw/ and it is merged when present):
  smartranking_rows.csv  regional app/company revenue ranking, source_type=ru. Columns: title, vertical, segment,
                         market_text, rev_cur_mln, rev_prev_mln, growth_pct, url.
  g2_categories.csv      B2B software category taxonomy (a category becomes an entity), source_type=proven.
                         Columns: title, parent, url.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter

from nichefinder.workspace import Workspace

SUMMARY = "Merge raw sources into data/out/universe.csv"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

FIELDS = ["entity", "source", "source_type", "geo", "side", "category", "one_liner", "signal", "url", "niche_id"]


def run(ws: Workspace, args: argparse.Namespace) -> None:
    def read(name: str) -> list[dict]:
        path = ws.raw(name)
        if not path.is_file():
            print("  (missing)", name)
            return []
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    rows: list[dict] = []

    # YC: rising
    for r in read("yc_companies.csv"):
        if r["excluded"] == "1":
            continue
        side = "b2c" if r["industry"] == "Consumer" else "b2b"
        rows.append({
            "entity": r["name"], "source": f"yc:{r['batch']}", "source_type": "rising", "geo": "global", "side": side,
            "category": f"{r['industry']} / {r['subindustry']}".replace("B2B / B2B -> ", "B2B / "),
            "one_liner": r["one_liner"], "signal": f"team={r['team_size']}; tags={r['tags']}", "url": r["website"], "niche_id": "",
        })

    # Product Hunt: rising
    for r in read("ph_top.csv"):
        rows.append({
            "entity": r["name"], "source": f"ph:{r['period']}", "source_type": "rising", "geo": "global", "side": "",
            "category": r["topics"], "one_liner": r["tagline"], "signal": "", "url": f"https://www.producthunt.com/posts/{r['slug']}", "niche_id": "",
        })

    # TinySeed: proven small-team B2B
    for r in read("tinyseed_portfolio.csv"):
        rows.append({
            "entity": r["name"], "source": "tinyseed", "source_type": "proven", "geo": "global", "side": "b2b",
            "category": "", "one_liner": r["excerpt"], "signal": "", "url": r["website"], "niche_id": "",
        })

    # Empire Flippers: transactions with a verified P&L; software and digital listings only (s0_empireflippers `kind`)
    for r in read("ef_listings.csv"):
        if r["kind"] not in ("software", "digital"):
            continue
        rows.append({
            "entity": r["public_title"][:80], "source": f"ef:{r['kind']}", "source_type": "transactions", "geo": "global",
            "side": {"B2B": "b2b", "B2C": "b2c"}.get(r["customer_type"], ""),
            "category": f"{r['monetizations']} / {r['niches']}"[:80], "one_liner": r["summary"][:160],
            "signal": f"profit_mo=${r['monthly_net_profit']}; price=${r['listing_price']}; {r['listing_status']} {r['first_listed_at'][:7]}",
            "url": r["url"], "niche_id": "",
        })

    # App Store: proven B2C (US + RU)
    for r in read("appstore_top.csv"):
        rows.append({
            "entity": r["name"], "source": f"appstore:{r['country']}:{r['genre']}", "source_type": "proven", "geo": "global" if r["country"] == "us" else "ru",
            "side": "b2c", "category": r["genre"], "one_liner": r["summary"][:160], "signal": f"rank={r['rank']}; dev={r['developer']}",
            "url": f"https://apps.apple.com/{r['country']}/app/id{r['app_id']}", "niche_id": "",
        })

    # Optional import: regional revenue ranking
    for r in read("smartranking_rows.csv"):
        rows.append({
            "entity": r["title"], "source": f"smartranking:{r['vertical']}", "source_type": "ru", "geo": "ru", "side": "",
            "category": r["segment"], "one_liner": r["market_text"],
            "signal": f"rev={r['rev_cur_mln']}mln; prev={r['rev_prev_mln']}; growth={r['growth_pct']}", "url": r["url"], "niche_id": "",
        })

    # Optional import: B2B software category taxonomy (a category is an entity)
    for r in read("g2_categories.csv"):
        rows.append({
            "entity": r["title"], "source": "g2:category", "source_type": "proven", "geo": "global", "side": "b2b",
            "category": r["parent"].replace("&amp;", "&"), "one_liner": "", "signal": "", "url": r["url"], "niche_id": "",
        })

    # Google Play top charts, WordPress plugins, Shopify App Store
    for r in read("gplay_top.csv"):
        if int(r["rank"]) > 150:   # the tail of a 200-item list carries little information
            continue
        rows.append({
            "entity": r["title"], "source": f"gplay:{r['country']}:{r['collection'].lower()}:{r['category']}", "source_type": "proven" if r["collection"] == "TOP_GROSSING" else "usage",
            "geo": "global" if r["country"] == "us" else "ru", "side": "b2c", "category": r["category"], "one_liner": (r["summary"] or "")[:160],
            "signal": f"rank={r['rank']}; dev={r['developer']}; score={r['score']}", "url": f"https://play.google.com/store/apps/details?id={r['appId']}", "niche_id": "",
        })
    for r in read("wordpress_plugins.csv"):
        if int(r["active_installs"] or 0) < 5000:
            continue
        rows.append({
            "entity": r["name"], "source": "wordpress:popular", "source_type": "proven", "geo": "global", "side": "b2b",
            "category": r["tags"][:80], "one_liner": r["short_description"][:160], "signal": f"installs={r['active_installs']}; ratings={r['num_ratings']}",
            "url": f"https://wordpress.org/plugins/{r['slug']}/", "niche_id": "",
        })
    seen_sh: set[str] = set()
    for r in read("shopify_apps.csv"):
        if r["handle"] in seen_sh:
            continue
        seen_sh.add(r["handle"])
        rows.append({
            "entity": r["name"], "source": f"shopify:{r['category']}", "source_type": "proven", "geo": "global", "side": "b2b",
            "category": r["category"], "one_liner": r["tagline"][:160], "signal": f"reviews={r['reviews']}; rating={r['rating']}; pricing={r['pricing']}",
            "url": f"https://apps.shopify.com/{r['handle']}", "niche_id": "",
        })

    # BetaList: rising (pre-launch)
    for r in read("betalist.csv"):
        rows.append({
            "entity": r["name"], "source": "betalist", "source_type": "rising", "geo": "global", "side": "",
            "category": "", "one_liner": r["tagline"][:160], "signal": f"date={r['date']}", "url": r["url"], "niche_id": "",
        })
    # Product Radar: rising, Russian-language launches
    for r in read("productradar.csv"):
        rows.append({
            "entity": r["name"], "source": "productradar", "source_type": "rising", "geo": "ru", "side": "",
            "category": r["categories"][:80], "one_liner": r["description"][:160],
            "signal": f"month={r['month']}; votes={r['votes']}; comments={r['comments']}" + (f"; asks={r['asks']}" if r["asks"] else ""),
            "url": r["url"], "niche_id": "",
        })
    # Kickstarter: proven (paid in advance), successful projects with >= 200 backers
    for r in read("kickstarter_projects.csv"):
        if r["state"] != "successful" or int(r["backers"] or 0) < 200:
            continue
        rows.append({
            "entity": r["name"], "source": f"kickstarter:{r['category']}", "source_type": "proven", "geo": "global", "side": "b2c",
            "category": f"{r['category']} / {r['subcategory']}", "one_liner": r["blurb"][:160],
            "signal": f"pledged=${int(float(r['pledged_usd'] or 0)):,}; backers={r['backers']}", "url": r["url"], "niche_id": "",
        })

    if not rows:
        raise SystemExit("no raw source files found in data/raw/: run the S0 fetch stages first (`nf run s0`)")
    out = ws.out("universe.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    c = Counter(r["source"].split(":")[0] for r in rows)
    print(f"universe: {len(rows)} rows -> {out}")
    for k, v in c.most_common():
        print(f"  {v:5d}  {k}")
