"""S0: TrustMRR - startups whose revenue is verified through the payment provider's API (Stripe, Lemon Squeezy, Paddle...).

Two modes (--mode auto picks api when TRUSTMRR_API_KEY is set, public otherwise):

- api: the official API, GET https://trustmrr.com/api/v1/startups?sort=revenue-desc, with the server-side filter
  minRevenue (--min-revenue, USD of revenue in the last 30 days, default 100). The key is free with a TrustMRR account
  (trustmrr.com/docs/api, keys start with tmrr_) and goes in the Authorization header. 10 startups per page and 10
  requests per minute on a standard key, so the stage waits 6.5 s after each live page (--max-pages caps a run; about
  40 minutes per 4,000 startups). The API reports money in USD cents; the CSV holds dollars.
- public (keyless): a bounded snapshot of public pages. The home page (~470 startups with the highest revenue, with the
  30-day growth), the first page of each category (/category/<slug>: the 30 startups with the highest total revenue in
  the category) and the two public AI endpoints (/api/ai/discovery: 25 recently added and 25 fastest growing;
  /api/ai: 25 recently listed for sale and 25 best deals, with founded date, category and asking price). About 35
  requests. The pages are Next.js: the startup objects sit in the RSC payload (the self.__next_f.push chunks).
  TrustMRR's llms.txt asks automated clients not to scrape the site for full access and to use the authenticated API
  for pagination and filtering, so this mode stays bounded: no /startups/page/N directory walk, no per-startup pages.

Output: data/raw/trustmrr.csv, one row per startup (merged by slug over the sources): slug, name, description,
category (category slugs, `|`-joined), target_audience, country, founded, revenue_30d, mrr, revenue_total (USD),
growth_30d (revenue growth over 30 days, %), on_sale (1/0), asking_price (USD), multiple (price / annual revenue),
website, url, source (`|`-joined: api, home, category, ai_discovery, ai_market).
Cache: data/cache/trustmrr, one file per page with the run month (ws.today) in the key: a re-run within the month is
free, the next month fetches fresh numbers.

Caveats: founders list themselves (mostly indie hackers from Marc Lou's audience), so AI, SaaS and developer tools are
over-represented and offline or B2B-enterprise niches under-represented. The public snapshot leans to the top earners:
it shows whether a niche has proven revenue, not how many small players there are. Stealth startups hide the name
("Hidden Business"); their description still matches. Revenue is a 30-day snapshot, not a trend. s5_deals matches the
rows to niches; the columns are evidence and never enter the score.
"""
from __future__ import annotations

import argparse
import csv
import json
import re

from nichefinder import http, keys
from nichefinder.workspace import Workspace

SUMMARY = "TrustMRR: startups with payment-provider-verified revenue (API with a key, a bounded public snapshot without)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

BASE = "https://trustmrr.com"
FIELDS = ["slug", "name", "description", "category", "target_audience", "country", "founded", "revenue_30d", "mrr",
          "revenue_total", "growth_30d", "on_sale", "asking_price", "multiple", "website", "url", "source"]
# the category slugs of trustmrr.com/category on 2026-11-21, used when the index page cannot be parsed
CATEGORIES = ["ai", "analytics", "community", "content-creation", "crypto-web3", "customer-support", "design-tools",
              "developer-tools", "ecommerce", "education", "entertainment", "fintech", "games", "green-tech",
              "health-fitness", "iot-hardware", "legal", "marketing", "marketplace", "mobile-apps", "news-magazines",
              "no-code", "productivity", "real-estate", "recruiting", "saas", "sales", "security", "social-media",
              "travel", "utilities"]
PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
CATEGORY_LINK = re.compile(r'href="/category/([a-z0-9-]+)"')


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=["auto", "api", "public"], default="auto",
                        help="api needs TRUSTMRR_API_KEY; auto uses it when set (default auto)")
    parser.add_argument("--min-revenue", type=float, default=100,
                        help="api mode: minimum revenue in the last 30 days, USD (default 100; 0 = all startups)")
    parser.add_argument("--max-pages", type=int, default=400, help="api mode: cap on pages of 10 startups (default 400)")


# ---- parsing -------------------------------------------------------------------

def rsc_payload(page: str) -> str:
    """The React Server Components payload of a Next.js page: the self.__next_f.push string chunks, decoded and joined."""
    out = []
    for m in PUSH.finditer(page):
        try:
            out.append(json.loads('"' + m.group(1) + '"'))
        except ValueError:
            continue
    return "".join(out)


def rsc_startups(payload: str) -> list[dict]:
    """Startup objects in an RSC payload: JSON objects that start with "_id" and carry a slug, a name and the 30-day revenue."""
    dec = json.JSONDecoder()
    out = []
    for m in re.finditer(r'\{"_id":\s*"', payload):
        try:
            o, _ = dec.raw_decode(payload, m.start())
        except ValueError:
            continue
        if isinstance(o, dict) and o.get("slug") and o.get("name") and "currentLast30DaysRevenue" in o:
            out.append(o)
    return out


def _num(v, scale: float = 1.0, digits: int = 2):
    if v is None or v == "":
        return ""
    try:
        x = round(float(v) / scale, digits)
    except (TypeError, ValueError):
        return ""
    return int(x) if digits == 0 else x


def _usd(v, scale: float = 1.0):
    """Money as whole dollars."""
    return _num(v, scale, 0)


def _text(v, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _cat(v) -> str:
    """A category as a slug: 'saas' stays, 'Health & Fitness' -> 'health-fitness'."""
    s = re.sub(r"[^a-z0-9]+", "-", str(v or "").lower()).strip("-")
    return {"artificial-intelligence": "ai", "recruiting-hr": "recruiting", "e-commerce": "ecommerce"}.get(s, s)


def row_from_rsc(o: dict, source: str, category: str = "") -> dict:
    """A startup object from a page's RSC payload (dollars; growth in %)."""
    growth = o.get("growth30d", o.get("cachedGrowth30d"))
    on_sale = int(bool(o["onSale"])) if o.get("onSale") is not None else (1 if o.get("askingPrice") else "")
    return {"slug": o["slug"], "name": _text(o["name"], 120), "description": _text(o.get("description")),
            "category": category, "target_audience": "", "country": "", "founded": "",
            "revenue_30d": _usd(o.get("currentLast30DaysRevenue")), "mrr": _usd(o.get("currentMrr")),
            "revenue_total": _usd(o.get("currentTotalRevenue")), "growth_30d": _num(growth, 1, 1), "on_sale": on_sale,
            "asking_price": _usd(o.get("askingPrice")), "multiple": _num(o.get("multiple", o.get("cachedMultiple"))),
            "website": o.get("website") or "", "url": f"{BASE}/startup/{o['slug']}", "source": source}


def row_from_api(o: dict, source: str, scale: float) -> dict:
    """A startup of the JSON APIs: /api/v1 (scale=100, money in cents) or the public /api/ai endpoints (scale=1, dollars)."""
    rev = o.get("revenue") or {}
    return {"slug": o["slug"], "name": _text(o.get("name"), 120), "description": _text(o.get("description")),
            "category": _cat(o.get("category")), "target_audience": str(o.get("targetAudience") or "").lower(),
            "country": o.get("country") or "", "founded": str(o.get("foundedDate") or "")[:10],
            "revenue_30d": _usd(rev.get("last30Days"), scale), "mrr": _usd(rev.get("mrr"), scale),
            "revenue_total": _usd(rev.get("total"), scale), "growth_30d": _num(o.get("growth30d"), 1, 1),
            "on_sale": "" if o.get("onSale") is None else int(bool(o["onSale"])),
            "asking_price": _usd(o.get("askingPrice"), scale), "multiple": _num(o.get("multiple")),
            "website": o.get("website") or "", "url": f"{BASE}/startup/{o['slug']}", "source": source}


def merge(rows: list[dict]) -> dict[str, dict]:
    """Rows by slug: the first non-empty value of each field wins; categories and sources are joined."""
    out: dict[str, dict] = {}
    for r in rows:
        cur = out.get(r["slug"])
        if cur is None:
            out[r["slug"]] = dict(r)
            continue
        for k, v in r.items():
            if k in ("category", "source"):
                parts = [p for p in (cur[k].split("|") if cur[k] else []) + ([v] if v else []) if p]
                cur[k] = "|".join(dict.fromkeys(parts))
            elif cur.get(k) in ("", None) and v not in ("", None):
                cur[k] = v
    return out


# ---- fetching ------------------------------------------------------------------

def _page(ws: Workspace, path: str, stamp: str) -> str:
    key = f"{stamp}_{re.sub(r'[^a-z0-9]+', '_', path.lower()).strip('_') or 'home'}"
    return http.get_text(BASE + path, cache=ws.cache("trustmrr"), cache_key=key, ext=".html", hashed=False,
                         timeout=60, min_size=20_000, sleep=1.5)


def fetch_public(ws: Workspace, stamp: str) -> list[dict]:
    rows: list[dict] = []
    for path, src in (("/api/ai/discovery", "ai_discovery"), ("/api/ai", "ai_market")):
        try:
            d = http.get_json(BASE + path, cache=ws.cache("trustmrr"), cache_key=f"{stamp}_{src}", hashed=False,
                              timeout=60, sleep=1.5)
        except (http.HttpError, OSError, ValueError) as e:
            print(f"  ! {path}: {e}")
            continue
        n = 0
        for group in d.values():
            if isinstance(group, list):
                for o in group:
                    if isinstance(o, dict) and o.get("slug"):
                        rows.append(row_from_api(o, src, 1.0))
                        n += 1
        print(f"  {path}: {n} startups")
    try:
        home = _page(ws, "/", stamp)
        found = rsc_startups(rsc_payload(home))
        rows += [row_from_rsc(o, "home") for o in found]
        print(f"  home page: {len({o['slug'] for o in found})} startups")
    except (http.HttpError, OSError) as e:
        print(f"  ! home page: {e}")
    try:
        cats = sorted(set(CATEGORY_LINK.findall(_page(ws, "/category", stamp)))) or CATEGORIES
    except (http.HttpError, OSError) as e:
        print(f"  ! category index: {e}; using the built-in list")
        cats = CATEGORIES
    for c in cats:
        try:
            found = rsc_startups(rsc_payload(_page(ws, f"/category/{c}", stamp)))
        except (http.HttpError, OSError) as e:
            print(f"  ! category {c}: {e}")
            continue
        rows += [row_from_rsc(o, "category", c) for o in found]
        print(f"  category {c:18} {len(found):3} startups")
    return rows


def fetch_api(ws: Workspace, key: str, stamp: str, min_revenue: float, max_pages: int) -> list[dict]:
    rows: list[dict] = []
    cents = int(round(min_revenue * 100))
    for page in range(1, max_pages + 1):
        url = f"{BASE}/api/v1/startups?sort=revenue-desc&limit=10&page={page}" + (f"&minRevenue={cents}" if cents > 0 else "")
        try:
            d = http.get_json(url, cache=ws.cache("trustmrr"), cache_key=f"{stamp}_api_min{cents}_p{page}", hashed=False,
                              headers={"Authorization": f"Bearer {key}"}, timeout=60, sleep=6.5, tries=4,
                              backoff=(15, 30, 60), user_agent=http.BOT_UA)
        except (http.HttpError, OSError, ValueError) as e:
            print(f"  ! page {page}: {e}")
            break
        data, meta = d.get("data") or [], d.get("meta") or {}
        rows += [row_from_api(o, "api", 100.0) for o in data if isinstance(o, dict) and o.get("slug")]
        if page == 1 or page % 20 == 0:
            print(f"  page {page}: {len(rows)} of {meta.get('total', '?')} startups", flush=True)
        if not data or not meta.get("hasMore"):
            break
    else:
        print(f"  stopped at --max-pages {max_pages}")
    return rows


def run(ws: Workspace, args: argparse.Namespace) -> None:
    stamp = f"{ws.today:%Y-%m}"
    key = keys.get("TRUSTMRR_API_KEY")
    mode = args.mode if args.mode != "auto" else ("api" if key else "public")
    if mode == "api" and not key:
        raise keys.MissingKey(("TRUSTMRR_API_KEY",), purpose="the TrustMRR API (trustmrr.com/docs/api)")
    print(f"mode: {mode}" + (f", revenue >= ${args.min_revenue:,.0f} in 30 days" if mode == "api" else
                             " (bounded snapshot; set TRUSTMRR_API_KEY for the full list)"))
    rows = fetch_api(ws, key, stamp, args.min_revenue, args.max_pages) if mode == "api" else fetch_public(ws, stamp)
    merged = sorted(merge(rows).values(), key=lambda r: -(r["revenue_30d"] or 0))
    out = ws.raw("trustmrr.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(merged)
    if not merged:
        print("warning: no TrustMRR startups parsed (the site may have changed or blocked the request); wrote an empty file")
    paying = sum(1 for r in merged if (r["revenue_30d"] or 0) > 0)
    mrr_1k = sum(1 for r in merged if (r["mrr"] or 0) >= 1000)
    print(f"startups: {len(merged)} ({paying} with revenue in the last 30 days, {mrr_1k} with MRR >= $1k, "
          f"{sum(1 for r in merged if r['on_sale'] == 1)} for sale) -> {out}")
