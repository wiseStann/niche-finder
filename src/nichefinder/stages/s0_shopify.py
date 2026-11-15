"""S0: Shopify App Store listings from every category and subcategory (name, rating, reviews, pricing).

Walks /browse, expands subcategories from the top-level category pages, then reads up to 3 pages per category
(?page=N). Pages are cached under data/cache/shopify/ (browse.html, cat_<slug>.html, cat_<slug>_p<N>.html).
Writes data/raw/shopify_apps.csv: category, page, handle, name, rating, reviews, pricing, tagline.
Signal type proven/transactions: e-commerce B2B tools; review count approximates adoption.
Needs curl (the site answers browser-like clients only). Several hundred requests on a cold cache, 1 s apart. No keys.
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import time

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Shopify App Store apps by category"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)

PAGES = 3
MIN_PAGE = 5000   # shorter responses are block pages and are neither cached nor used


def fetch(ws: Workspace, url: str, name: str) -> str:
    for _ in range(3):
        try:
            text = http.get_text(url, cache=ws.cache("shopify"), cache_key=name, ext="", hashed=False, backend="curl",
                                 min_size=MIN_PAGE, headers={"Accept": "text/html"}, timeout=60, tries=1, sleep=1.0)
        except Exception:  # noqa: BLE001
            text = ""
        if len(text) > MIN_PAGE:
            return text
        time.sleep(5)
    return ""


def cards(s: str) -> list[dict]:
    names = re.findall(r'data-app-card-name-value="([^"]+)"', s)
    handles = re.findall(r'data-app-card-handle-value="([^"]+)"', s)
    txt = re.sub(r"<[^>]+>", "|", s)
    txt = html.unescape(re.sub(r"[\s|]*\|[\s|]*", "|", txt))
    out = []
    for name, handle in zip(names, handles):
        name = html.unescape(name)
        i = txt.find("|" + name + "|")
        seg = txt[i:i + 400] if i >= 0 else ""
        m = re.search(r"\|(\d\.\d)\|out of 5 stars\|\(([\d,]+)\)\|[^|]*\|(?:•\|)?([^|]{0,60})\|([^|]{0,160})", seg)
        out.append({"handle": handle, "name": name, "rating": m.group(1) if m else "", "reviews": m.group(2).replace(",", "") if m else "",
                    "pricing": m.group(3) if m else "", "tagline": m.group(4) if m else ""})
    return out


def _category_slugs(s: str) -> set[str]:
    return set(re.findall(r'apps\.shopify\.com/categories/([a-z0-9-]+)', s)) | set(re.findall(r'href="/categories/([a-z0-9-]+)"', s))


def run(ws: Workspace, args: argparse.Namespace) -> None:
    browse = fetch(ws, "https://apps.shopify.com/browse", "browse.html")
    cats = sorted(_category_slugs(browse))
    # expand subcategories from the top-level category pages
    sub = set(cats)
    for c in list(cats):
        sub |= _category_slugs(fetch(ws, f"https://apps.shopify.com/categories/{c}", f"cat_{c}.html"))
    sub = sorted(sub)
    print("categories:", len(sub))
    rows, seen = [], set()
    for c in sub:
        for p in range(1, PAGES + 1):
            s = fetch(ws, f"https://apps.shopify.com/categories/{c}" + (f"?page={p}" if p > 1 else ""), f"cat_{c}_p{p}.html")
            cs = cards(s) if s else []
            new = 0
            for x in cs:
                if (c, x["handle"]) in seen:
                    continue
                seen.add((c, x["handle"]))
                new += 1
                rows.append({"category": c, "page": p, **x})
            if new == 0:
                break
        print(c, sum(1 for r in rows if r["category"] == c))
    if not rows:
        print("no Shopify apps fetched (the site may have blocked the request); nothing written")
        return
    out = ws.raw("shopify_apps.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("->", out, len(rows), "rows,", len({r['handle'] for r in rows}), "unique apps")
