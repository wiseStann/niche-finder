"""S0: Product Radar (productradar.ru) - Russian-language product launches, month by month.

The site loads its feed through WordPress admin-ajax (action=more-handler, group_by=month): period 0 is the current
month, 1 the previous one, and so on; each period has pages of 15 cards. The stage walks --months periods (default 12)
and writes data/raw/productradar.csv: name, slug, description, month (YYYY-MM), votes, comments, categories, asks, url.
`asks` lists the founder requests that the site keeps as categories (partners, investors, mentor, co-founder, interns,
selling the project, hiring, "roast me", startup cemetery): who has not found a model yet.

Small volume (30-50 launches a month): weak as a source of niches, useful as a list of Russian competitors in a chosen
niche and as a pulse of what Russian-speaking founders build. The site's TLS chain fails Python's certificate check, so
requests go through curl. The cache key carries the month of the run (ws.today), because period numbers shift every
month. No keys; 1 s between live requests; about 3 requests per month of history.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Product Radar: Russian-language launches by month (productradar.ru)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)

AJAX = "https://productradar.ru/wp-admin/admin-ajax.php"
FIELDS = ["name", "slug", "description", "month", "votes", "comments", "categories", "asks", "url"]
ASKS = {"seeking-partners": "partners", "seeking-investors": "investors", "seeking-mentor": "mentor",
        "seeking-cofounder": "cofounder", "seeking-interns": "interns", "selling-startup-project": "selling",
        "hiring": "hiring", "roasting": "roast", "startup-cemetery": "cemetery"}
MONTHS = {"январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6, "июль": 7, "август": 8,
          "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12}
CARD = re.compile(r'<article class="products__item[^"]*">(.*?)</article>', re.S)
CAT = re.compile(r'<a href="https://productradar\.ru/category/((?:[^"/?]+/)*[^"/?]+)/?(?:\?[^"]*)?"[^>]*>(.*?)</a>', re.S)
HEADER = re.compile(r"<time[^>]*>\s*([^\W\d_]+)\s+(\d{4})\s*</time>")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--months", type=int, default=12, help="months of history, the current one included (default 12)")


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_cards(h: str) -> list[dict]:
    rows = []
    for b in CARD.findall(h):
        url = re.search(r'href="(https://productradar\.ru/product/([^/"]+)/?)"', b)
        title = re.search(r'class="card__title"[^>]*>(.*?)</h\d>', b, re.S)
        if not url or not title:
            continue
        desc = re.search(r'class="card__description"[^>]*>(.*?)</p>', b, re.S)
        comments = re.search(r'class="card__comments"[^>]*>(.*?)</a>', b, re.S)
        votes = re.search(r'data-votes="(\d+)"', b)
        cats, asks = [], []
        for slug, label in CAT.findall(b):
            if slug.split("/")[0] in ASKS:
                asks.append(ASKS[slug.split("/")[0]])
            else:
                cats.append(_plain(label))
        rows.append({"name": _plain(title.group(1)), "slug": url.group(2), "description": _plain(desc.group(1)) if desc else "",
                     "month": "", "votes": votes.group(1) if votes else "", "comments": re.sub(r"\D", "", _plain(comments.group(1))) if comments else "",
                     "categories": "|".join(dict.fromkeys(cats)), "asks": "|".join(dict.fromkeys(asks)), "url": url.group(1)})
    return rows


def header_month(h: str) -> str:
    """'Октябрь 2026' heading of a period -> '2026-10'; empty when the page has no heading."""
    for name, year in HEADER.findall(h):
        if name.lower() in MONTHS:
            return f"{year}-{MONTHS[name.lower()]:02d}"
    return ""


def shift_month(year: int, month: int, back: int) -> str:
    k = year * 12 + month - 1 - back
    return f"{k // 12}-{k % 12 + 1:02d}"


def fetch(ws: Workspace, stamp: str, period: int, page: int) -> dict:
    path = http.cache_file(ws.cache("productradar"), f"pr_{stamp}_m{period}_p{page}", ".json", hashed=False)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    body = f"action=more-handler&next_period={period}&next_page={page}&group_by=month"
    data = http.request(AJAX, method="POST", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"},
                        backend="curl", timeout=60).json()
    if isinstance(data, dict) and data.get("html"):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(1.0)
    return data


def run(ws: Workspace, args: argparse.Namespace) -> None:
    stamp = f"{ws.today:%Y-%m}"
    rows: dict[str, dict] = {}
    period, page, label = 0, 0, {}
    for _ in range(args.months * 10):   # safety cap: a month rarely has more than 4 pages
        if period >= args.months:
            break
        try:
            d = fetch(ws, stamp, period, page)
        except (http.HttpError, OSError, ValueError) as e:
            print(f"  ! period {period} page {page}: {e}")
            break
        if not isinstance(d, dict) or (isinstance(d.get("data"), dict) and d["data"].get("error")):
            print(f"  ! period {period} page {page}: unexpected answer {str(d)[:120]}")
            break
        h = d.get("html") or ""
        label.setdefault(period, header_month(h) or shift_month(ws.today.year, ws.today.month, period))
        cards = parse_cards(h)
        for c in cards:
            c["month"] = label[period]
            rows.setdefault(c["slug"], c)
        print(f"{label[period]} page {page}: {len(cards)} launches")
        if d.get("last") or (isinstance(d.get("data"), dict) and d["data"].get("last_page")):
            break
        nxt = (int(d.get("next_period", period)), int(d.get("next_page", page + 1)))
        if nxt == (period, page):
            break
        period, page = nxt
    out = ws.raw("productradar.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows.values())
    if not rows:
        print("warning: no Product Radar launches parsed (the site may have changed or refused the request); wrote an empty file")
    by_month: dict[str, int] = {}
    for r in rows.values():
        by_month[r["month"]] = by_month.get(r["month"], 0) + 1
    print(f"launches: {len(rows)} ({', '.join(f'{m}: {n}' for m, n in sorted(by_month.items()))}) -> {out}")
