"""Startpack (startpack.ru): a Russian catalogue of business software with user reviews - the Russian analogue of Capterra.

Category pages (/category/<slug>?page=N) list products with their review counts; review pages
(/application/<code>/reviews?sort_by=date&sort_desc=desc&page=N) carry 50 reviews each, marked up with schema.org Review:
headline, ratingValue, pros, cons, text, and a code that starts with the date (YYYYMMDD-...). robots.txt allows both
(it disallows /review/, /rest/ and /goto/, which are not used) and sets ai-input=yes, ai-train=no.

The HTML is cached per run month (the month is part of the key), so a re-run in the same month is free and offline and
the next month fetches fresh pages. Live requests pause PAUSE seconds. Short responses are not cached (block pages).
"""
from __future__ import annotations

import html as _html
import re

from nichefinder import http
from nichefinder.workspace import Workspace

BASE = "https://startpack.ru"
PAUSE = 1.0
MIN_PAGE = 20_000          # real category and review pages are 150-600 KB; a 404 page is about 1 KB
PER_PAGE = 50

_CARD = re.compile(r'class="app-list-panel[^"]*">(.*?)(?=class="app-list-panel|\Z)', re.S)
_CODE_NAME = re.compile(r'data-code="([a-z0-9-]+)"\s+data-name=\'([^\']*)\'')
_REVIEWS_LINK = re.compile(r"href='/application/([a-z0-9-]+)/reviews'[^>]*>\s*([\d\s ]+)")
_BRIEF = re.compile(r'<div class="app-list-brief"><p>(.*?)</p>', re.S)
_PAGE = re.compile(r"[?&]page=(\d+)")
_REVIEW = re.compile(r'<article itemprop="review"[^>]*data-strcode="(\d{8})-([^"]*)"(.*?)</article>', re.S)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _block(body: str, cls: str) -> str:
    """Text of the editor-view-text inside the element with class `cls` (pros, cons, text), or ''."""
    m = re.search(r'class="' + cls + r'[^"]*">.*?class="editor-view-text">(.*?)</div>', body, re.S)
    return _text(m.group(1)) if m else ""


def parse_category(page: str) -> tuple[list[dict], int]:
    """(products on a category page: code, name, reviews, stars, brief; the highest page number linked)."""
    out = []
    for card in _CARD.findall(page):
        cn = _CODE_NAME.search(card)
        if not cn:
            continue
        code, name = cn.group(1), _html.unescape(cn.group(2))
        rv = [m for m in _REVIEWS_LINK.finditer(card) if m.group(1) == code]
        reviews = int(re.sub(r"\D", "", rv[0].group(2)) or 0) if rv else 0
        stars = card.count("rating-star-15-full") + 0.5 * card.count("rating-star-15-half")
        brief = _BRIEF.search(card)
        out.append({"code": code, "name": name, "reviews": reviews, "stars": stars, "brief": _text(brief.group(1)) if brief else ""})
    pages = [int(p) for p in _PAGE.findall(page)]
    return out, max(pages, default=1)


def parse_reviews(page: str) -> list[dict]:
    """Reviews of one review page: id, date (YYYY-MM-DD), rating, title, pros, cons, text."""
    out = []
    for day, slug, body in _REVIEW.findall(page):
        rating = re.search(r"itemprop=\"ratingValue\"[^>]*content='(\d)'", body)
        title = re.search(r'class="review-content-name"[^>]*>(.*?)</div>', body, re.S)
        out.append({"id": f"{day}-{slug}", "date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "rating": int(rating.group(1)) if rating else 0,
                    "title": _text(title.group(1)) if title else "", "pros": _block(body, "review-content-pluses"),
                    "cons": _block(body, "review-content-minuses"), "text": _block(body, "review-content-text")})
    return out


def parse_meta(page: str) -> dict:
    """Product name, total review count and average rating from the schema.org AggregateRating of a review page."""
    agg = re.search(r'itemprop="aggregateRating"(.*?)</div>', page, re.S)
    body = agg.group(1) if agg else ""
    name = re.search(r'itemprop="name" content="([^"]*)"', body)
    count = re.search(r'itemprop="ratingCount" content="(\d+)"', body)
    value = re.search(r'itemprop="ratingValue" content="([\d.]+)"', body)
    return {"name": _html.unescape(name.group(1)) if name else "", "reviews": int(count.group(1)) if count else 0,
            "rating": round(float(value.group(1)), 2) if value else 0.0}


def _get(ws: Workspace, path: str, key: str) -> str | None:
    """A page through the month-keyed cache; None on HTTP 404/410 (the product or category is gone)."""
    try:
        return http.get_text(BASE + path, cache=ws.cache("startpack"), cache_key=key, ext=".html", min_size=MIN_PAGE,
                             sleep=PAUSE, backend="auto", tries=3)
    except http.HttpError as e:
        if e.status in (404, 410):
            return None
        raise


def category(ws: Workspace, slug: str, month: str, max_pages: int = 5) -> list[dict]:
    """All products of a category (up to max_pages pages), deduplicated by code."""
    page = _get(ws, f"/category/{slug}", f"{month}|category|{slug}|1")
    if page is None:
        return []
    apps, last = parse_category(page)
    for n in range(2, min(last, max_pages) + 1):
        more = _get(ws, f"/category/{slug}?page={n}", f"{month}|category|{slug}|{n}")
        if more:
            apps += parse_category(more)[0]
    seen, out = set(), []
    for a in apps:
        if a["code"] not in seen:
            seen.add(a["code"])
            out.append(a)
    return out


def reviews(ws: Workspace, code: str, month: str, pages: int, since: str = "") -> tuple[list[dict], str, dict]:
    """Newest reviews of one product, up to `pages` pages; stops at a short page or once a page is older than `since`.
    Returns (reviews, status, meta from the first page: name, reviews, rating)."""
    out, meta = [], {}
    for n in range(1, int(pages) + 1):
        try:
            page = _get(ws, f"/application/{code}/reviews?sort_by=date&sort_desc=desc&page={n}", f"{month}|reviews|{code}|{n}")
        except (http.HttpError, OSError) as e:
            return out, f"failed on page {n}: {str(e)[:60]}", meta
        if page is None:
            return out, ("not found" if n == 1 else "ok"), meta
        if n == 1:
            meta = parse_meta(page)
        items = parse_reviews(page)
        out += items
        if len(items) < PER_PAGE or (since and items and min(x["date"] for x in items) < since):
            break
    return out, "ok", meta


def review_text(r: dict) -> str:
    """One text for the LLM from the structured review."""
    parts = [f"Pros: {r['pros']}" if r.get("pros") else "", f"Cons: {r['cons']}" if r.get("cons") else "", r.get("text") or ""]
    return "\n".join(p for p in parts if p)
