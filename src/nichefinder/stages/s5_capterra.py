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
s5_merge settles the S5 gate from them when it can and treats the category as no data otherwise. Pages that came through
stay in the cache, so a later run fetches only the missing ones.
Horizontal products (config/capterra_generic.yaml) are excluded from the niche concentration and reported separately,
except in a niche that names the product in its own brand queries (`i: brand`): Deputy is a horizontal substitute for a
gym but a player in shift scheduling, Wix a player among website builders.
Inputs: config/capterra_map.yaml (niche -> category slugs), config/capterra_generic.yaml, queries/*.yaml (brands).
Outputs: data/out/capterra_products.csv, data/out/capterra_categories_stats.csv. HTML is cached in data/cache/capterra/.
Needs curl (Capterra answers browser-like clients only). No key.
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import time

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


def fetch(ws: Workspace, slug: str, page: int) -> str:
    path = ws.cache("capterra") / f"{slug}_p{page}.html"
    if path.exists() and path.stat().st_size > 10000:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not blocked(text):
            return text
        path.unlink()   # a block page cached by an earlier version
    url = f"https://www.capterra.com/{slug}/" + (f"?page={page}" if page > 1 else "")
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


def crawl(ws: Workspace, slug: str) -> tuple[int | None, list[tuple[str, float, int]], int, str, int | None]:
    """All pages of a category: (numberOfItems, products, pages fetched, why paging stopped, tail).

    The reason is "end" (no new cards, the listing reached products without reviews, or every product was seen) or "cap"
    (MAX_PAGES, a fixed cut that is the same in every run) for a complete category, and "blocked pN" or "no cards" for an
    incomplete one. `tail` is the review count of the last card of the review-ordered listing on the last page read: no
    product on a later page has more.
    """
    total, products, seen, tail = None, [], set(), None
    for page in range(1, MAX_PAGES + 1):
        s = fetch(ws, slug, page)
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
    leaders' names (page 1 holds them), but no shares, player counts or review totals; its bounds are the
    `top1_share_max`, `products_100plus_min` and `tail_reviews` columns."""
    products = sorted(products, key=lambda c: -c[2])
    horizontal = {c[0] for c in products if c[0] in generic and not is_own(c[0], brands)}
    niche_only = [c for c in products if c[0] not in horizontal]
    tot_rev, top1, top1_share, top3_share, _ = conc(products)
    n_tot, n_top1, n_top1_share, n_top3_share, n_hhi = conc(niche_only)
    full = complete(stop)
    stats = {
        "niche_id": nid, "slug": slug, "products_total": total, "products_seen": len(products),
        "complete": int(full), "pages": pages, "stop": stop,
        "products_10plus": sum(1 for c in niche_only if c[2] >= 10) if full else "",
        "products_100plus": sum(1 for c in niche_only if c[2] >= 100) if full else "",
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


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cmap = ws.load_config("capterra_map.yaml", {})
    generic = set((ws.load_config("capterra_generic.yaml", {}) or {}).get("generic") or [])
    if not cmap:
        print("config/capterra_map.yaml is empty or missing - nothing to do")
        return
    brands = own_brands(ws)
    prod_rows, cat_rows, crawled = [], [], {}
    for nid, cfg in cmap.items():
        for slug in cfg["slugs"]:
            if slug not in crawled:   # a category shared by two niches is fetched once
                crawled[slug] = crawl(ws, slug)
            total, products, pages, stop, tail = crawled[slug]
            stats, rows = category_stats(nid, slug, cfg, total, products, pages, stop, tail, generic, brands.get(nid, set()))
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
              "Then run s5_merge and s6 again.")
    with open(ws.out("capterra_products.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(prod_rows[0].keys()) if prod_rows else
                           ["niche_id", "slug", "rank", "product", "rating", "reviews", "generic"])
        w.writeheader(); w.writerows(prod_rows)
    with open(ws.out("capterra_categories_stats.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cat_rows[0].keys())); w.writeheader(); w.writerows(cat_rows)
    print("-> data/out/capterra_products.csv, capterra_categories_stats.csv")
