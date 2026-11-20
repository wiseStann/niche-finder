"""S0: Empire Flippers marketplace listings (public JSON API, no key): online businesses with a verified P&L.

Reads https://api.empireflippers.com/api/v1/listings/list?limit=100&page=N until the last page (about 29 pages for ~2,900
listings, for sale and sold). Empire Flippers checks the seller's P&L before listing, so profit and price are verified,
unlike self-reported marketplaces. Most listings are Amazon FBA, content and e-commerce; SaaS is a minority.
The niche is not a field: it is only in public_title ("... in the Kitchenware Niche"), the summary and the marketplace's
own `niches` tags, so s5_deals matches the text with config/deal_keywords.yaml.

Each listing gets a `kind` from its monetizations: software (SaaS, Application), digital (digital and info products,
newsletters, YouTube, subscriptions) or other (Amazon, e-commerce, content sites). Software and digital listings enter
the universe; s5_deals counts software listings only. The other kinds stay out because an Amazon seller's summary
matches seller-tool niches although the business is a customer of those niches, not a player in them
(2,871 listings on 2026-11-20: 79 software, 216 digital, 2,576 other).

Pages are trimmed to the fields below and cached under data/cache/empireflippers/ with the run month in the key: the list
shifts as listings come and go, so a re-run in the same month is free and the next month fetches fresh data.
Writes data/raw/ef_listings.csv: listing_number, public_title, summary, listing_status, monetizations, niches,
customer_type, country, monthly_net_profit, monthly_gross_revenue, listing_price, listing_multiple, multiple_type,
first_made_money_at, first_listed_at, days_on_marketplace, updated_at, mrr, churn_percent, kind, url.
Duplicates by listing_number are dropped. 1.5 s between live requests.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Empire Flippers listings with a verified P&L (profit, price, status)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

API = "https://api.empireflippers.com/api/v1/listings/list"
LIMIT = 100
MAX_PAGES = 100
# output column -> field of the API listing
FIELDS = {
    "listing_number": "listing_number", "public_title": "public_title", "summary": "summary",
    "listing_status": "listing_status", "monetizations": "monetizations", "niches": "niches",
    "customer_type": "customer_type", "country": "country",
    "monthly_net_profit": "average_monthly_net_profit", "monthly_gross_revenue": "average_monthly_gross_revenue",
    "listing_price": "listing_price", "listing_multiple": "listing_multiple", "multiple_type": "listing_multiple_type",
    "first_made_money_at": "first_made_money_at", "first_listed_at": "first_listed_at",
    "days_on_marketplace": "days_on_marketplace", "updated_at": "updated_at", "mrr": "mrr", "churn_percent": "churn_percent",
}
SOFTWARE = {"SaaS", "Application"}
DIGITAL = {"Digital Product", "Info Product", "Newsletter", "YouTube", "Subscription"}


def kind(monetizations: str) -> str:
    """software | digital | other, from the 'a|b' monetization tags."""
    tags = set(monetizations.split("|"))
    return "software" if tags & SOFTWARE else "digital" if tags & DIGITAL else "other"


def trim(listing: dict) -> dict:
    """The fields we keep, with the tag lists flattened to 'a|b'."""
    row = {}
    for col, key in FIELDS.items():
        v = listing.get(key)
        if key == "monetizations":
            v = "|".join(m.get("monetization", "") for m in v or [] if isinstance(m, dict))
        elif key == "niches":
            v = "|".join(m.get("niche", "") for m in v or [] if isinstance(m, dict))
        row[col] = "" if v is None else v
    row["kind"] = kind(row["monetizations"])
    row["url"] = f"https://empireflippers.com/listing/{row['listing_number']}/" if row["listing_number"] else ""
    return row


def fetch_page(ws: Workspace, page: int) -> dict:
    """{'pages': int, 'count': int, 'listings': [trimmed rows]} for one page; cached per run month."""
    path = http.cache_file(ws.cache("empireflippers"), f"ef_{ws.today:%Y-%m}_l{LIMIT}_p{page}", ".json", hashed=False)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    url = f"{API}?limit={LIMIT}&page={page}"
    data = http.request(url, user_agent=http.BOT_UA, timeout=120).json()
    if data.get("errors"):
        raise RuntimeError(f"Empire Flippers API error on page {page}: {json.dumps(data['errors'])[:300]}")
    d = data.get("data") or {}
    count = int(d.get("count") or 0)
    out = {"pages": int(d.get("pages") or math.ceil(count / LIMIT)), "count": count,
           "listings": [trim(x) for x in d.get("listings") or []]}
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    time.sleep(1.5)
    return out


def run(ws: Workspace, args: argparse.Namespace) -> None:
    rows: list[dict] = []
    page, pages = 1, 1
    while page <= min(pages, MAX_PAGES):
        d = fetch_page(ws, page)
        pages = d["pages"]
        rows += d["listings"]
        print(f"page {page}/{pages}: {len(d['listings'])} listings", flush=True)
        if not d["listings"]:
            break
        page += 1
    seen: set = set()
    uniq = []
    for r in rows:
        if r["listing_number"] in seen:
            continue
        seen.add(r["listing_number"])
        r["kind"] = kind(r["monetizations"])      # derived at run time, so a rule change needs no new fetch
        uniq.append(r)
    if not uniq:
        print("no Empire Flippers listings fetched; nothing written (an existing ef_listings.csv is kept).")
        return
    out = ws.raw("ef_listings.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[*FIELDS, "kind", "url"])
        w.writeheader()
        w.writerows(uniq)
    print(f"unique: {len(uniq)} -> {out}")
