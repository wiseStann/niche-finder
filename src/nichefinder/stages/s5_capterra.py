"""Capterra supply (B2B): product count per category and review concentration (top1/top3/HHI).

A Capterra category page lists 25 cards on page 1 (the first two are sponsored) and 50 per `?page=N` after that; paging
stops once a page brings no new cards or only products without reviews. `numberOfItems` in the schema.org ItemList is
the total number of products in the category. Horizontal products (config/capterra_generic.yaml) are excluded from the
niche concentration and reported separately.
Inputs: config/capterra_map.yaml (niche -> category slugs), config/capterra_generic.yaml.
Outputs: data/out/capterra_products.csv, data/out/capterra_categories_stats.csv. HTML is cached in data/cache/capterra/.
Needs curl (Capterra answers browser-like clients only). No key.
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import time

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Capterra category sizes and review concentration (HTML via curl)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)

MAX_PAGES = 14


def fetch(ws: Workspace, slug: str, page: int) -> str:
    path = ws.cache("capterra") / f"{slug}_p{page}.html"
    if path.exists() and path.stat().st_size > 10000:
        return path.read_text(encoding="utf-8", errors="ignore")
    url = f"https://www.capterra.com/{slug}/" + (f"?page={page}" if page > 1 else "")
    for attempt in range(3):
        try:
            text = http.request(url, backend="curl", timeout=60, headers={"Accept": "text/html"},
                                tries=1, raise_for_status=False).text
        except OSError:
            text = ""
        if len(text) > 10000:
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


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cmap = ws.load_config("capterra_map.yaml", {})
    generic = set((ws.load_config("capterra_generic.yaml", {}) or {}).get("generic") or [])
    if not cmap:
        print("config/capterra_map.yaml is empty or missing - nothing to do")
        return
    prod_rows, cat_rows = [], []
    for nid, cfg in cmap.items():
        for slug in cfg["slugs"]:
            total, products, seen = None, [], set()
            for page in range(1, MAX_PAGES + 1):
                s = fetch(ws, slug, page)
                if not s:
                    print("  !! empty", slug, page)
                    break
                n, cards = parse(s)
                total = total or n
                new = [c for c in cards if c[0] not in seen]
                for c in new:
                    seen.add(c[0])
                products += new
                if not new or all(c[2] == 0 for c in new):
                    break
            products.sort(key=lambda c: -c[2])
            niche_only = [c for c in products if c[0] not in generic]
            gen_in = [c[0] for c in products if c[0] in generic and c[2] >= 100]

            def conc(ps):
                tot = sum(c[2] for c in ps)
                sh = [c[2] / tot for c in ps] if tot else []
                return tot, (ps[0][0] if ps else ""), (round(sh[0], 3) if sh else ""), (round(sum(sh[:3]), 3) if sh else ""), (round(sum(x * x for x in sh), 3) if sh else "")
            tot_rev, top1, top1_share, top3_share, hhi = conc(products)
            n_tot, n_top1, n_top1_share, n_top3_share, n_hhi = conc(niche_only)
            stats = {
                "niche_id": nid, "slug": slug, "products_total": total, "products_seen": len(products),
                "products_10plus": sum(1 for c in niche_only if c[2] >= 10),
                "products_100plus": sum(1 for c in niche_only if c[2] >= 100),
                "reviews_total": tot_rev, "top1_all": top1, "top1_share_all": top1_share, "top3_share_all": top3_share,
                "reviews_niche": n_tot, "top1": n_top1, "top1_share": n_top1_share, "top3_share": n_top3_share, "hhi": n_hhi,
                "generic_present": "; ".join(gen_in[:6]),
                "note": cfg.get("note", ""),
            }
            cat_rows.append(stats)
            for k, (name, rating, cnt) in enumerate(products, 1):
                prod_rows.append({"niche_id": nid, "slug": slug, "rank": k, "product": name, "rating": rating, "reviews": cnt, "generic": int(name in generic)})
            print(f"{nid:34} {slug:44} total={total} seen={len(products)} >=10={stats['products_10plus']} >=100={stats['products_100plus']} top1={stats['top1']} {stats['top1_share']} top3={stats['top3_share']} generic={stats['generic_present'][:40]}")
    if not cat_rows:
        return
    with open(ws.out("capterra_products.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(prod_rows[0].keys()) if prod_rows else
                           ["niche_id", "slug", "rank", "product", "rating", "reviews", "generic"])
        w.writeheader(); w.writerows(prod_rows)
    with open(ws.out("capterra_categories_stats.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cat_rows[0].keys())); w.writeheader(); w.writerows(cat_rows)
    print("-> data/out/capterra_products.csv, capterra_categories_stats.csv")
