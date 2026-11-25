"""B2B pricing (switching cost): prices of the top products per niche, from Capterra category pages, then GetApp.

For every B2B niche: the top-N products by Capterra reviews (horizontal ones excluded). s5_capterra already read their
pricing from the category pages (capterra_products.csv): free trial / free version always, the entry price, period and
model when the page lists plans. A product whose price is still unknown goes to GetApp, which shows the same Gartner data
on product cards: its GetApp slug (found in the category listing) -> the card. GetApp answers scripts with an anti-bot
page (2026-11-21), so the first block page ends the GetApp lookups and the Capterra data is written alone.
Inputs: data/out/capterra_products.csv, config/capterra_map.yaml, config/getapp_categories.yaml (GetApp child -> parent).
Outputs: data/out/pricing_b2b.csv (per product, `source` capterra / getapp / empty) and data/out/pricing_b2b_niche.csv
(per niche: share of products with a public price among those whose pricing is known, median/min/max monthly price,
share under $100, free trial/version shares). A product with no price and no "no pricing info" mark is unknown and stays
out of the public-price share (counting it as unpriced gave false 0 % shares). HTML is cached in data/cache/getapp/.
Needs curl. No key.
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import time
from collections import defaultdict

from nichefinder import http
from nichefinder.stages.s5_capterra import blocked   # GetApp sits behind the same anti-bot check as Capterra
from nichefinder.workspace import Workspace

SUMMARY = "B2B pricing of top Capterra products from Capterra page data, then GetApp cards"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)

TOP_N = 8
# Capterra slug -> GetApp child category, where it differs from "slug minus -software"
OVERRIDE = {
    "billing-and-invoicing-software": "billing-invoicing",
    "rental-property-management-software": "property-management",
    "legal-case-management-software": "legal-case-management",
    "multi-channel-ecommerce-software": "multi-channel-ecommerce",
    "seo-software": "seo",
}


class Blocked(Exception):
    """GetApp answered with an anti-bot page: the whole site is closed to scripts, so the stage stops."""


def fetch(ws: Workspace, url: str, name: str) -> str:
    path = ws.cache("getapp") / name
    if path.exists() and path.stat().st_size > 5000:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not blocked(text):
            return text
        path.unlink()   # a block page cached by an earlier version is not data
    for attempt in range(3):
        try:
            text = http.request(url, backend="curl", timeout=60, headers={"Accept": "text/html"},
                                tries=1, raise_for_status=False).text
        except OSError:
            text = ""
        if blocked(text):
            raise Blocked(url)
        if len(text) > 5000 and "Page Not Found" not in text[:3000]:
            path.write_text(text, encoding="utf-8")
            time.sleep(1.2)
            return text
        time.sleep(6 * (attempt + 1))
    return ""


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def listing_products(ws: Workspace, parent: str, child: str) -> dict:
    out = {}
    for page in (1, 2, 3):
        url = f"https://www.getapp.com/{parent}/{child}/" + (f"?page={page}" if page > 1 else "")
        s = fetch(ws, url, f"cat_{child}_p{page}.html")
        if not s:
            break
        found = re.findall(r'href="/[a-z0-9-]+/a/([a-z0-9-]+)/"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,80}?)\s*<', s)
        new = 0
        for slug, name in found:
            if slug not in out and name.strip() and not name.lower().startswith(("read more", "learn more", "compare")):
                out[slug] = name.strip(); new += 1
        if new == 0:
            break
    return out


def product_pricing(ws: Workspace, slug: str):
    s = fetch(ws, f"https://www.getapp.com/all-software/a/{slug}/", f"prod_{slug}.html")
    if not s:
        return None
    txt = re.sub(r"<[^>]+>", "|", s)
    txt = html.unescape(re.sub(r"[\s|]*\|[\s|]*", "|", txt))
    price, period, model = None, "", ""
    m = re.search(r"Starting price\|(?:See details\|)?([\d.,]+)\|([^|]{0,30})\|?/?\|?(per [a-z]+|Per [a-z]+|one-time|One-time)?", txt)
    if m:
        price = m.group(1).replace(",", "")
        model = m.group(2).strip()
        period = (m.group(3) or "").lower()
    if price is None:
        m = re.search(r"Starting from\|([\d.,]+)\|(Per [a-z]+|per [a-z]+|One-time|Free)", txt)
        if m:
            price, period = m.group(1).replace(",", ""), m.group(2).lower()
    no_info = "No pricing info" in txt

    def flag(label):
        i = s.find(f">{label}</div>")
        if i < 0:
            i = s.find(f">{label}<")
        if i < 0:
            return ""
        seg = s[i:i + 400]
        if "fas-check" in seg or "far-check" in seg or "icon-fas-check" in seg:
            return "1"
        if "fas-times" in seg:
            return "0"
        return ""
    return {"price": price, "period": period, "model": model, "no_pricing_info": int(no_info),
            "free_trial": flag("Free trial"), "free_version": flag("Free version")}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agg", action="store_true", help="only rebuild pricing_b2b_niche.csv from pricing_b2b.csv")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    if getattr(args, "agg", False):
        aggregate(ws)
        return
    cmap = ws.load_config("capterra_map.yaml", {})
    gcats = ws.load_config("getapp_categories.yaml", {}) or {}
    src = ws.out("capterra_products.csv")
    if not src.is_file():
        print(f"{src} not found - run s5_capterra first; skipping")
        return
    prods = list(csv.DictReader(open(src, encoding="utf-8")))
    by_slug = defaultdict(list)
    for r in prods:
        if r["generic"] == "0":
            by_slug[r["slug"]].append(r)
    rows = price_products(ws, cmap, gcats, by_slug)
    if not any(r[k] not in ("", None) for r in rows for k in ("price", "no_pricing_info", "free_trial", "free_version")):
        print("no pricing found for any product - nothing written (s5_merge treats the niches as unpriced: neutral switching inputs)")
        return
    src_n = defaultdict(int)
    for r in rows:
        src_n[r["source"] or "unknown"] += 1
    print("pricing source per product:", dict(src_n))
    out = ws.out("pricing_b2b.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("->", out, len(rows))
    aggregate(ws)


PRICE_COLS = ("price", "period", "model", "no_pricing_info", "free_trial", "free_version")


def known_price(r: dict) -> bool:
    """The product's pricing is known: a public price, or a mark that the vendor publishes none."""
    return str(r.get("price", "")) not in ("", "None") or str(r.get("no_pricing_info", "")) == "1"


def price_products(ws: Workspace, cmap: dict, gcats: dict, by_slug: dict) -> list[dict]:
    rows, getapp_open, listings = [], True, {}
    for nid, cfg in cmap.items():
        for cslug in cfg["slugs"]:
            child = OVERRIDE.get(cslug, cslug.replace("-software", ""))
            parent = gcats.get(child)
            top = sorted(by_slug[cslug], key=lambda r: -int(r["reviews"]))[:TOP_N]
            for r in top:
                cap = {k: r.get(k, "") or "" for k in PRICE_COLS}
                pr, gslug, matched, source = dict(cap), "", "", "capterra" if known_price(cap) else ""
                if not source and getapp_open and parent:
                    try:
                        if cslug not in listings:
                            listings[cslug] = listing_products(ws, parent, child)
                        listing = listings[cslug]
                        lookup = {norm(n): s for s, n in listing.items()}
                        gslug = lookup.get(norm(r["product"]))
                        if not gslug:
                            cand = [s for s, n in listing.items() if norm(r["product"]) in norm(n) or norm(n) in norm(r["product"])]
                            gslug = cand[0] if cand else re.sub(r"[^a-z0-9]+", "-", r["product"].lower()).strip("-")
                        matched = int(gslug in listing)
                        ga = product_pricing(ws, gslug) or {}
                        # the card's own flags win; Capterra's fill what the card does not show
                        pr = {k: (ga.get(k) if ga.get(k) not in ("", None) else cap[k]) for k in PRICE_COLS}
                        source = "getapp" if known_price(ga) else ""
                    except Blocked as e:
                        # 2026-11-21: GetApp, like Capterra, answers scripts with a Cloudflare "Security Check" page.
                        # Retrying every URL cost ~40 s each, so the first block page ends the GetApp lookups.
                        getapp_open = False
                        print(f"GetApp answered {e} with an anti-bot page - no more GetApp lookups in this run; "
                              "prices come from Capterra pages only")
                elif not source and getapp_open and not parent:
                    print(f"  !! no GetApp category for {cslug} ({child}) - add it to config/getapp_categories.yaml")
                rows.append({"niche_id": nid, "capterra_slug": cslug, "product": r["product"], "reviews": r["reviews"],
                             "source": source, "getapp_slug": gslug, "matched": matched, **{k: pr.get(k, "") for k in PRICE_COLS}})
                print(f"{nid:34} {r['product'][:28]:28} rev={r['reviews']:>5} [{source or 'unknown':8}] price={pr.get('price')} "
                      f"{pr.get('period', '')} {str(pr.get('model', ''))[:12]} trial={pr.get('free_trial')} free={pr.get('free_version')}")
    return rows


def aggregate(ws: Workspace) -> None:
    """pricing_b2b.csv -> pricing_b2b_niche.csv: share of products with a public price, median/min/max monthly price,
    share under $100, free trial / free version shares."""
    rows = list(csv.DictReader(open(ws.out("pricing_b2b.csv"), encoding="utf-8")))
    by = defaultdict(list)
    for r in rows:
        by[r["niche_id"]].append(r)
    agg = []
    for nid, rs in by.items():
        seen, uniq = set(), []
        for r in rs:
            if r["product"] not in seen:
                seen.add(r["product"]); uniq.append(r)
        monthly = sorted(float(r["price"]) for r in uniq if r["price"] not in ("", "None") and "month" in (r["period"] or ""))
        pub = [r for r in uniq if r["price"] not in ("", "None")]
        known = [r for r in uniq if known_price(r)]
        trial = [r for r in uniq if r["free_trial"] in ("0", "1")]
        free = [r for r in uniq if r["free_version"] in ("0", "1")]
        agg.append({"niche_id": nid, "n": len(uniq), "price_known": len(known), "price_public": len(pub),
                    "price_public_share": round(len(pub) / len(known), 2) if known else "",
                    "median_monthly_usd": monthly[len(monthly) // 2] if monthly else "", "min_monthly_usd": monthly[0] if monthly else "", "max_monthly_usd": monthly[-1] if monthly else "",
                    "under_100_share": round(sum(1 for x in monthly if x < 100) / len(monthly), 2) if monthly else "",
                    "free_trial_share": round(sum(1 for r in trial if r["free_trial"] == "1") / len(trial), 2) if trial else "",
                    "free_version_share": round(sum(1 for r in free if r["free_version"] == "1") / len(free), 2) if free else "",
                    "sample": "; ".join(f"{r['product'][:20]} ${r['price']}{'/' + r['period'].replace('per ', '') if r['period'] else ''}" for r in pub[:5])})
    out = ws.out("pricing_b2b_niche.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(agg[0].keys())); w.writeheader(); w.writerows(agg)
    print("->", out, len(agg))
