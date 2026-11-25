"""Capterra supply (B2B): product count per category and review concentration (top1/top3/HHI).

A Capterra category page lists 25 cards on page 1 (the first two are sponsored) and 50 per `?page=N` after that. After
the sponsored cards the products come by review count, highest first, so page 1 holds the leaders and the tail follows.
Paging stops once a page brings no new cards, ends in products without reviews, or every product has been seen
(`numberOfItems` in the schema.org ItemList is the total number of products in the category), or at MAX_PAGES.
A category is complete only when paging stopped for one of these reasons. When Cloudflare blocks a page, the category is
incomplete: the pages fetched so far overstate the top-1 and top-3 shares and undercount the players, and how many pages
get through changes from run to run (rehearsal of 2026-11-24: page 1 only for 9 of 13 categories, and the verdict of three
niches moved with it). An incomplete category keeps its product count and the names of its leaders, but its shares,
player counts and review totals stay empty. Instead it carries bounds that more pages cannot move the wrong way: the
top-1 share read so far is an upper bound (the leader is on page 1, the denominator only grows), the players read so far
a lower bound, and the reviews of the last ordered card (`tail_reviews`) an upper bound for every product not read.
Once that tail is under 100 reviews, no unread product can be a player, so the player count is exact and is filled in
(changed 2026-11-25; the count of products with 10+ reviews likewise once the tail is under 10). s5_merge settles the S5 gate from them when it can and treats the category as no data otherwise. Pages that came through
stay in the cache, so a later run fetches only the missing ones.
Cloudflare lets a browser through when it stops curl, so pages can also come from a browser: `--missing` lists the pages
the cache lacks (no requests), and `--import <folder>` checks pages saved there (Ctrl+S) and puts them into the cache under
the address the browser recorded (its "saved from url" comment, else the canonical link). The next run reads them;
`--offline` makes that run read the cache only, without the retries a blocked page costs (about 30 s per category).
Pricing: the page data (Next.js `self.__next_f` strings) holds a pricing object per product. Every page variant has the
free trial / free version flags; some categories (employee scheduling, rental property management in 2026-11) also list
the plans. Then the default plan, the one Capterra shows as "Paid plans start at", gives the entry price, its period
(paymentFrequency 2 = per month, 3 = per year) and model (pricingModel 1 flat rate, 2 per user, 3 per feature,
4 usage based, 5 other); plans that are all "contact the vendor" (priceType 2) mean no public price. Without plans the
price is unknown, not missing, and s5_pricing_b2b looks for it on GetApp.
Horizontal products (config/capterra_generic.yaml) are excluded from the niche concentration and reported separately,
except in a niche that names the product in its own brand queries (`i: brand`): Deputy is a horizontal substitute for a
gym but a player in shift scheduling, Wix a player among website builders.
Inputs: config/capterra_map.yaml (niche -> category slugs), config/capterra_generic.yaml, queries/*.yaml (brands).
Outputs: data/out/capterra_products.csv (with the pricing columns), data/out/capterra_categories_stats.csv. HTML is cached in data/cache/capterra/.
Needs curl (Capterra answers browser-like clients only). No key.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nichefinder import http, niches
from nichefinder.workspace import Workspace

SUMMARY = "Capterra category sizes and review concentration (HTML via curl)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)

MAX_PAGES = 14
# An anti-bot interstitial is about 44 KB, above any size floor, so it is recognised by its markers (2026-11-21: 45 of
# 51 category pages came back as "Security Check" and were cached as if they were data).
BLOCK_MARKERS = ("<title>Security Check</title>", "<title>Just a moment", "cf-browser-verification", "challenge-platform")


def blocked(text: str) -> bool:
    head = text[:5000]
    return any(m in head for m in BLOCK_MARKERS) and '"numberOfItems"' not in text


def page_url(slug: str, page: int) -> str:
    return f"https://www.capterra.com/{slug}/" + (f"?page={page}" if page > 1 else "")


def fetch(ws: Workspace, slug: str, page: int, offline: bool = False) -> str:
    path = ws.cache("capterra") / f"{slug}_p{page}.html"
    if path.exists() and path.stat().st_size > 10000:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not blocked(text):
            return text
        path.unlink()   # a block page cached by an earlier version
    if offline:
        return ""
    url = page_url(slug, page)
    for attempt in range(3):
        try:
            text = http.request(url, backend="curl", timeout=60, headers={"Accept": "text/html"},
                                tries=1, raise_for_status=False).text
        except OSError:
            text = ""
        if len(text) > 10000 and not blocked(text):
            path.write_text(text, encoding="utf-8")
            time.sleep(1.0)
            return text
        time.sleep(5 * (attempt + 1))
    return ""


def parse(s: str):
    n_items = re.findall(r'"numberOfItems":(\d+)', s)
    txt = re.sub(r"<[^>]+>", "|", s)
    txt = html.unescape(re.sub(r"[\s|]*\|[\s|]*", "|", txt))
    cards = re.findall(r"\|([^|]{2,60})\|(\d\.\d)\|\(\|([\d,]+)\|\)", txt)
    seen, out = set(), []
    for name, rating, cnt in cards:
        if name not in seen:
            seen.add(name)
            out.append((name.strip(), float(rating), int(cnt.replace(",", ""))))
    return (int(n_items[0]) if n_items else None), out


P1_LISTING = 25   # cards of the category listing on page 1; a block of related products may follow them


def crawl(ws: Workspace, slug: str, offline: bool = False) -> tuple[int | None, list[tuple[str, float, int]], int, str, int | None]:
    """All pages of a category: (numberOfItems, products, pages fetched, why paging stopped, tail).

    The reason is "end" (no new cards, the listing reached products without reviews, or every product was seen) or "cap"
    (MAX_PAGES, a fixed cut that is the same in every run) for a complete category, and "blocked pN" or "no cards" for an
    incomplete one. `tail` is the review count of the last card of the review-ordered listing on the last page read: no
    product on a later page has more.
    """
    total, products, seen, tail = None, [], set(), None
    for page in range(1, MAX_PAGES + 1):
        s = fetch(ws, slug, page, offline)
        if not s:
            return total, products, page - 1, f"blocked p{page}", tail
        n, cards = parse(s)
        total = total or n
        if page == 1 and not cards:
            return total, products, 1, "no cards", tail   # a page that is not a category listing (a redesign, a redirect)
        listing = cards[:P1_LISTING] if page == 1 else cards
        tail = listing[-1][2] if listing else tail
        new = [c for c in cards if c[0] not in seen]
        seen.update(c[0] for c in new)
        products += new
        if not new or all(c[2] == 0 for c in new) or tail == 0:   # the pages after this one hold no reviews
            return total, products, page, "end", tail
        if total and len(products) >= total:
            return total, products, page, "end", tail
    return total, products, MAX_PAGES, "cap", tail


def complete(stop: str) -> bool:
    return stop in ("end", "cap")


PERIOD = {2: "per month", 3: "per year"}
MODEL = {1: "Flat Rate", 2: "Per User", 3: "Per Feature", 4: "Usage Based", 5: "Other"}
PRICE_COLS = ("price", "period", "model", "no_pricing_info", "free_trial", "free_version")


def payload(s: str) -> str:
    """The data of a Next.js page: the JavaScript strings of `self.__next_f.push([1, "..."])`, decoded and joined."""
    out = []
    for chunk in re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', s):
        try:
            out.append(json.loads('"' + chunk + '"'))
        except ValueError:
            pass
    return "".join(out)


def plan_price(pr: dict) -> dict:
    """Entry price of one product's pricing object; empty price and no_pricing_info when the page lists no plans."""
    out = {"price": "", "period": "", "model": "", "no_pricing_info": "",
           "free_trial": "" if pr.get("hasFreeTrial") is None else int(bool(pr["hasFreeTrial"])),
           "free_version": "" if pr.get("hasFreeVersion") is None else int(bool(pr["hasFreeVersion"]))}
    plans = [p for p in pr.get("plans") or [] if isinstance(p, dict)]
    if not plans:
        return out
    priced = [p for p in plans if p.get("priceType") == 1 and isinstance(p.get("startingPrice"), (int, float))]
    pick = next((p for p in priced if p.get("isDefault")), None) or min(priced, key=lambda p: p["startingPrice"], default=None)
    if pick is None:   # every plan says "contact the vendor"
        out["no_pricing_info"] = 1
        return out
    out.update(price=pick["startingPrice"], period=PERIOD.get(pick.get("paymentFrequency"), ""),
               model=MODEL.get(pick.get("pricingModel"), ""), no_pricing_info=0)
    return out


def pricing(s: str) -> dict[str, dict]:
    """Pricing of the products on a category page by product name (plan_price columns). A product shown twice keeps the
    copy that lists plans."""
    data, dec, out = payload(s), json.JSONDecoder(), {}
    for m in re.finditer(r'"pricing":\{"__typename":"ProductPricing"', data):
        k, obj = m.start(), None
        for _ in range(5000):   # walk back to the product object that holds this pricing object
            k = data.rfind("{", 0, k)
            if k < 0:
                break
            try:
                o, end = dec.raw_decode(data, k)
            except ValueError:
                continue
            if isinstance(o, dict) and isinstance(o.get("pricing"), dict) and end > m.start():
                obj = o
                break
        if not obj or not isinstance(obj.get("name"), str):
            continue
        name = html.unescape(obj["name"]).strip()
        row = plan_price(obj["pricing"])
        known = row["price"] != "" or row["no_pricing_info"] != ""
        if name not in out or (known and out[name]["price"] == "" and out[name]["no_pricing_info"] == ""):
            out[name] = row
    return out


def cached_pricing(ws: Workspace, slug: str, pages: int) -> dict[str, dict]:
    """Pricing from the pages of a category that are in the cache (the pages crawl read)."""
    out: dict[str, dict] = {}
    for page in range(1, pages + 1):
        s = fetch(ws, slug, page, offline=True)
        for name, row in (pricing(s) if s else {}).items():
            out.setdefault(name, row)
    return out


def missing_pages(ws: Workspace, cmap: dict) -> list[tuple[str, str, str]]:
    """(niche, slug, URL) of the next page each incomplete category needs, from the cache alone (no requests). Only the
    shortlisted niches when there is a shortlist: only they are scored."""
    out, done = [], set()
    shortlist = set(niches.shortlist_ids(ws))
    for nid, cfg in cmap.items():
        if shortlist and nid not in shortlist:
            continue
        for slug in cfg["slugs"]:
            if slug in done:
                continue
            done.add(slug)
            _, _, pages, stop, _ = crawl(ws, slug, offline=True)
            if not complete(stop):
                out.append((nid, slug, page_url(slug, pages + 1 if stop.startswith("blocked") else 1)))
    return out


def saved_address(s: str) -> str:
    """The address a browser saved a page from: its "saved from url" comment, else the canonical link."""
    m = re.search(r"<!-- saved from url=\(\d+\)(\S+?) -->", s[:3000])
    if m:
        return m.group(1)
    m = re.search(r'<link[^>]*rel="canonical"[^>]*href="([^"]+)"', s) or re.search(r'<link[^>]*href="([^"]+)"[^>]*rel="canonical"', s)
    return html.unescape(m.group(1)) if m else ""


def import_pages(ws: Workspace, folder: Path) -> int:
    """Put category pages saved in a browser into the cache. Returns the number imported."""
    files = sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in (".html", ".htm"))
    n = 0
    for p in files:
        s = p.read_text(encoding="utf-8", errors="ignore")
        url = urlparse(saved_address(s))
        parts = [x for x in url.path.split("/") if x]
        if not url.netloc.endswith("capterra.com") or len(parts) != 1:
            print(f"  skip {p.name}: not a Capterra category page ({url.geturl() or 'no address in the file'})")
            continue
        if blocked(s) or not parse(s)[1]:
            print(f"  skip {p.name}: no product cards (a block page or an unfinished load); open the page again and save it")
            continue
        page = int((parse_qs(url.query).get("page") or ["1"])[0])
        (ws.cache("capterra") / f"{parts[0]}_p{page}.html").write_text(s, encoding="utf-8")
        n += 1
        print(f"  {p.name} -> {parts[0]} page {page}")
    print(f"imported {n} of {len(files)} file(s) into {ws.cache('capterra')}")
    return n


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--missing", action="store_true",
                        help="list the pages the cache lacks (next page of every incomplete category) and stop; no requests")
    parser.add_argument("--import", dest="import_dir", metavar="FOLDER",
                        help="first put the category pages saved in a browser in FOLDER into the cache")
    parser.add_argument("--offline", action="store_true",
                        help="read the cache only: pages it lacks are not requested (the categories stay incomplete)")


def own_brands(ws: Workspace) -> dict[str, set[str]]:
    """Lower-cased brand names (`b` of the `i: brand` queries, any language) per niche."""
    out: dict[str, set[str]] = {}
    for nid, langs in niches.load_queries(ws).items():
        for qs in (langs or {}).values():
            for q in qs or []:
                if q.get("i") == "brand" and q.get("b"):
                    out.setdefault(nid, set()).add(str(q["b"]).strip().lower())
    return out


def is_own(product: str, brands: set[str]) -> bool:
    """The product is one of the niche's brands: the same name, or the brand followed by more words ("Wix Studio")."""
    p = product.strip().lower()
    return any(p == b or re.match(re.escape(b) + r"\W", p) for b in brands)


def conc(ps: list[tuple[str, float, int]]):
    """(reviews, top-1 name, top-1 share, top-3 share, HHI) of products sorted by reviews, highest first."""
    tot = sum(c[2] for c in ps)
    sh = [c[2] / tot for c in ps] if tot else []
    return (tot, (ps[0][0] if ps else ""), (round(sh[0], 3) if sh else ""), (round(sum(sh[:3]), 3) if sh else ""),
            (round(sum(x * x for x in sh), 3) if sh else ""))


def category_stats(nid: str, slug: str, cfg: dict, total, products, pages: int, stop: str, tail: int | None,
                   generic: set[str], brands: set[str]) -> tuple[dict, list[dict]]:
    """The stats row of one category and its product rows. An incomplete category keeps counts of what was seen and the
    leaders' names (page 1 holds them), but no shares or review totals, and a player count only when it is exact (every
    unread product has fewer reviews than the threshold); its bounds are the `top1_share_max`, `products_100plus_min`
    and `tail_reviews` columns."""
    products = sorted(products, key=lambda c: -c[2])
    horizontal = {c[0] for c in products if c[0] in generic and not is_own(c[0], brands)}
    niche_only = [c for c in products if c[0] not in horizontal]
    tot_rev, top1, top1_share, top3_share, _ = conc(products)
    n_tot, n_top1, n_top1_share, n_top3_share, n_hhi = conc(niche_only)
    full = complete(stop)
    exact_10 = full or (pages > 0 and tail is not None and tail < 10)     # no unread product reaches the threshold
    exact_100 = full or (pages > 0 and tail is not None and tail < 100)
    stats = {
        "niche_id": nid, "slug": slug, "products_total": total, "products_seen": len(products),
        "complete": int(full), "pages": pages, "stop": stop,
        "products_10plus": sum(1 for c in niche_only if c[2] >= 10) if exact_10 else "",
        "products_100plus": sum(1 for c in niche_only if c[2] >= 100) if exact_100 else "",
        "reviews_total": tot_rev if full else "", "top1_all": top1,
        "top1_share_all": top1_share if full else "", "top3_share_all": top3_share if full else "",
        "reviews_niche": n_tot if full else "", "top1": n_top1,
        "top1_share": n_top1_share if full else "", "top3_share": n_top3_share if full else "", "hhi": n_hhi if full else "",
        "generic_present": "; ".join([c[0] for c in products if c[0] in horizontal and c[2] >= 100][:6]),
        "generic_kept": "; ".join(c[0] for c in products if c[0] in generic and c[0] not in horizontal),
        "top1_share_max": n_top1_share if pages else "",
        "products_100plus_min": sum(1 for c in niche_only if c[2] >= 100) if pages else "",
        "tail_reviews": tail if pages and tail is not None else "",
        "note": cfg.get("note", ""),
    }
    rows = [{"niche_id": nid, "slug": slug, "rank": k, "product": name, "rating": rating, "reviews": cnt,
             "generic": int(name in horizontal)} for k, (name, rating, cnt) in enumerate(products, 1)]
    return stats, rows


def price_columns(prices: dict[str, dict], name: str) -> dict:
    row = prices.get(name) or next((v for k, v in prices.items() if k.lower() == name.lower()), None) or {}
    return {k: row.get(k, "") for k in PRICE_COLS}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cmap = ws.load_config("capterra_map.yaml", {})
    generic = set((ws.load_config("capterra_generic.yaml", {}) or {}).get("generic") or [])
    if not cmap:
        print("config/capterra_map.yaml is empty or missing - nothing to do")
        return
    if getattr(args, "import_dir", None):
        import_pages(ws, Path(args.import_dir))
    if getattr(args, "missing", False):
        need = missing_pages(ws, cmap)
        side = {n["id"]: n.get("side", "") for n in niches.load_niches(ws, scoped=False)}
        b2b = [x for x in need if side.get(x[0], "").startswith("b2b")]
        other = [x for x in need if x not in b2b]
        print(f"{len(need)} page(s) to open in a browser and save (Ctrl+S) into one folder, then "
              "`nf run s5_capterra -- --import <folder>`; repeat until nothing is listed.")
        for title, group in ((f"B2B niches, Capterra is their supply source ({len(b2b)}):", b2b),
                             (f"Other niches, used only when the App Store has no data ({len(other)}):", other)):
            if group:
                print(title)
                for nid, slug, url in group:
                    print(f"  {url}   ({nid})")
        return
    brands = own_brands(ws)
    prod_rows, cat_rows, crawled, prices = [], [], {}, {}
    for nid, cfg in cmap.items():
        for slug in cfg["slugs"]:
            if slug not in crawled:   # a category shared by two niches is fetched once
                crawled[slug] = crawl(ws, slug, offline=getattr(args, "offline", False))
                prices[slug] = cached_pricing(ws, slug, crawled[slug][2])
            total, products, pages, stop, tail = crawled[slug]
            stats, rows = category_stats(nid, slug, cfg, total, products, pages, stop, tail, generic, brands.get(nid, set()))
            for r in rows:
                r.update(price_columns(prices[slug], r["product"]))
            cat_rows.append(stats)
            prod_rows += rows
            state = "" if stats["complete"] else f" INCOMPLETE ({stop})"
            print(f"{nid:34} {slug:44} total={total} seen={len(products)} pages={pages}{state} >=100={stats['products_100plus']} "
                  f"top1={stats['top1']} {stats['top1_share']} top3={stats['top3_share']} generic={stats['generic_present'][:40]}"
                  + (f" own={stats['generic_kept']}" if stats["generic_kept"] else ""), flush=True)
    if not cat_rows:
        return
    partial = [r for r in cat_rows if not r["complete"]]
    if partial:
        print(f"\n{len(partial)} of {len(cat_rows)} categories are incomplete (anti-bot pages); s5_merge reads only their bounds:")
        for r in partial:
            print(f"  {r['niche_id']:34} {r['slug']:44} {r['stop']}, {r['products_seen']} of {r['products_total'] or '?'} products seen"
                  + (f"; top-1 <= {r['top1_share_max']}, >= {r['products_100plus_min']} players, unread <= {r['tail_reviews']} reviews each"
                     if r["top1_share_max"] != "" else ""))
        print("Re-run `nf run s5_capterra` later: fetched pages stay in the cache and only the missing ones are requested. "
              "Or save them in a browser: `nf run s5_capterra -- --missing` lists them, `-- --import <folder>` reads them. "
              "Then run s5_pricing_b2b, s5_merge and s6 again.")
    with open(ws.out("capterra_products.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(prod_rows[0].keys()) if prod_rows else
                           ["niche_id", "slug", "rank", "product", "rating", "reviews", "generic", *PRICE_COLS])
        w.writeheader(); w.writerows(prod_rows)
    with open(ws.out("capterra_categories_stats.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cat_rows[0].keys())); w.writeheader(); w.writerows(cat_rows)
    print("-> data/out/capterra_products.csv, capterra_categories_stats.csv")
