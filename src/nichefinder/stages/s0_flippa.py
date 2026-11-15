"""S0: Flippa listings of SaaS businesses for sale (JSON embedded in the search pages, or the listing cards when the page has no JSON).

Fetches up to 15 search pages (https://flippa.com/search?filter[property_type]=saas), cached under
data/cache/flippa/, and writes data/raw/flippa_saas.csv: title, summary, basic_name, revenue_average,
profit_average, price, original_price, annual_organic_traffic, app_rating, listing_url.
Small SaaS products with real revenue that are actually changing hands (source_type=transactions).
Stops at the first page without listings. No keys; 1.5 s between live requests.
"""
from __future__ import annotations

import argparse
import csv
import html
import re

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Flippa SaaS listings for sale (revenue, price)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

PAGES = 15
FIELDS = ["title", "summary", "basic_name", "revenue_average", "profit_average", "price", "original_price",
          "annual_organic_traffic", "app_rating", "listing_url"]


def fetch(ws: Workspace, page: int) -> str:
    url = f"https://flippa.com/search?filter%5Bproperty_type%5D=saas&page%5Bnumber%5D={page}"
    return http.get_text(url, cache=ws.cache("flippa"), cache_key=f"flippa_saas_p{page}", ext=".html", hashed=False,
                         timeout=60, min_size=1000, sleep=1.5)


def grab(block: str, key: str) -> str:
    m = re.search(r'"%s":("(?:[^"\\]|\\.)*"|[-0-9.]+|null|true|false)' % re.escape(key), block)
    if not m:
        return ""
    v = m.group(1)
    if v.startswith('"'):
        return v[1:-1].encode("utf-8").decode("unicode_escape", errors="ignore").encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    return "" if v == "null" else v


def _money(text: str) -> str:
    """'USD $160K' -> '160000', 'USD $2,520,000' -> '2520000'; empty when there is no amount."""
    m = re.search(r"([\d,.]+)\s*([KkMm]?)", text or "")
    if not m or not re.search(r"\d", m.group(1)):
        return ""
    try:
        v = float(m.group(1).replace(",", "")) * {"": 1, "k": 1e3, "m": 1e6}[m.group(2).lower()]
    except ValueError:
        return ""
    return str(int(round(v)))


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_cards(h: str) -> list[dict]:
    """Fallback for the current page layout: listing cards (<li id="listing-N">) instead of embedded JSON."""
    rows = []
    for block in re.split(r'<li id="listing-\d+"', h)[1:]:
        link = re.search(r'<h4[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not link:
            continue
        url = link.group(1)
        summ = re.search(r"</h4>.*?<p[^>]*>(.*?)</p>", block, re.S)

        def stat(label: str) -> str:
            m = re.search(r"<p[^>]*>\s*%s\s*</p>\s*<p[^>]*>(.*?)</p>" % re.escape(label), block, re.S)
            return _plain(m.group(1)) if m else ""
        prices = re.search(r"Asking price\s*</p>(.*?)(?:</div>|<hr|<form)", block, re.S)
        amounts = [_money(_plain(x)) for x in re.findall(r"<(?:span|p)[^>]*>(.*?)</(?:span|p)>", prices.group(1), re.S)] if prices else []
        amounts = [a for a in amounts if a]
        slug = re.sub(r"^https?://[^/]+/\d+-?", "", url).split("?")[0]
        rows.append({
            "title": slug.replace("-", " "),
            "summary": _plain(summ.group(1)) if summ else "",
            "basic_name": _plain(link.group(2)),
            "revenue_average": _money(stat("Monthly Revenue")),
            "profit_average": _money(stat("Monthly Profit")),
            "price": amounts[0] if amounts else "",
            "original_price": amounts[1] if len(amounts) > 1 else "",
            "annual_organic_traffic": "",
            "app_rating": "",
            "listing_url": url,
        })
    return rows


def run(ws: Workspace, args: argparse.Namespace) -> None:
    rows = []
    for p in range(1, PAGES + 1):
        try:
            h = fetch(ws, p)
        except Exception as e:  # noqa: BLE001
            print(f"  ! page {p}: {e}")
            break
        # every listing starts with {"id": and carries "revenue_average"
        blocks = re.split(r'\{"id":', h)
        n = 0
        for b in blocks[1:]:
            if '"revenue_average"' not in b or '"summary"' not in b:
                continue
            b = b[:6000]
            rows.append({
                "title": grab(b, "title"),
                "summary": grab(b, "summary"),
                "basic_name": grab(b, "name"),
                "revenue_average": grab(b, "revenue_average"),
                "profit_average": grab(b, "profit_average"),
                "price": grab(b, "price") or grab(b, "current_price"),
                "original_price": grab(b, "original_price"),
                "annual_organic_traffic": grab(b, "annual_organic_traffic"),
                "app_rating": grab(b, "app_rating"),
                "listing_url": grab(b, "listing_url") or grab(b, "html_url"),
            })
            n += 1
        if n == 0:
            cards = parse_cards(h)
            rows += cards
            n = len(cards)
        print(f"page {p}: {n}")
        if n == 0:
            break

    seen: set[tuple[str, str]] = set()
    uniq = []
    for r in rows:
        k = (r["title"], r["summary"][:60])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    out = ws.raw("flippa_saas.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(uniq)
    if not uniq:
        print("warning: no Flippa listings parsed (the site may have changed or blocked the request); wrote an empty file")
    print(f"unique: {len(uniq)} -> {out}")
