"""Russian B2B: supply inside Russian SMB app marketplaces (MoySklad integrations, amoCRM widgets) per niche.

Like ru_bitrix, but for two more platforms that Russian small businesses run on. The catalogs are small, so each is read
in full once a month and its apps are matched to the niches of config/ru_b2b_niches.yaml by keywords (no search):
  MoySklad  www.moysklad.ru/integratsii/ (apps.moysklad.ru redirects there): ~590 apps. The sitemap lists every app
            page (/integratsii/apps/<slug>/); each app page gives the name, "paid" or "free" solution, the developer,
            an upload date (an update date, not the launch: 409 of 589 apps carry a 2026 date) and the description. Category pages give category tags, page 1 only (robots.txt disallows
            URLs with `?`, so their "show more" pages are not read); the "popular" category marks popular apps.
  amoCRM    www.amocrm.ru/extensions/ (the old /integrations/ is 404): the public showcase of ~100 widgets with a
            one-line description, and six group pages (phone, site, mail, chats, useful, recommended). The live
            amoMarket (market.amocrm.ru) needs a login (401) and lists far more widgets, so this is a curated subset.
  YCLIENTS  not read: the marketplace page is a Vue front end that loads apps from /api/, which robots.txt disallows
            and which answers only with a partner token; there are no server-rendered app pages or sitemap entries.
None of the catalogs shows installs or ratings, so the "leader" here is the developer with the most matched apps.
Matching: the `bitrix` keywords of each niche (config/ru_ecosystems.yaml `keywords` replaces them per niche) against the
app name and the start of its description, with crude Russian stemming (word endings are free, words of up to 4
letters must match whole); `categories` in the same file adds every app of a marketplace category to a niche.
Outputs: data/out/ru_ecosystems.csv (niche x marketplace), ru_ecosystems_apps.csv (every matched app).
Cache: data/cache/ecosystems/ (catalog pages keyed by month; app pages by slug, fetched once). Free, no key; the first
run reads ~630 pages with polite sleeps (~12 minutes), later months only the catalog pages and new apps.
Caveats: keyword matching on short texts misses apps described in other words and catches some neighbours; MoySklad is
a retail and warehouse platform, so service niches (salons, clinics) are expected to have few apps there. Evidence
only: never changes the S6 score or verdict.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import re
from collections import Counter

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Russian SMB app marketplaces (MoySklad, amoCRM): apps per niche"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

MS = "https://www.moysklad.ru"
AMO = "https://www.amocrm.ru"
AMO_GROUPS = ("recommended", "phone", "site", "mail", "chats", "useful")
APP_FIELDS = ["marketplace", "niche_id", "slug", "name", "paid", "developer", "categories", "popular", "upload_date",
              "matched_by", "description", "url"]
WORD = "a-zа-яё0-9"


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--marketplace", choices=["moysklad", "amocrm", "all"], default="all", help="which catalog to read")
    p.add_argument("--max-apps", type=int, default=0, help="read at most N MoySklad app pages (0 = all; for a quick test)")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _get(ws: Workspace, url: str, key: str, sleep: float, min_size: int = 20_000) -> str:
    try:
        return http.get_text(url, cache=ws.cache("ecosystems"), cache_key=key, ext=".html", min_size=min_size,
                             sleep=sleep, raise_for_status=False)
    except OSError as e:
        print(f"  {url}: {e}")
        return ""


def keyword_regex(kw: str) -> str:
    """One keyword as a regex: left word boundary, free endings for words of 5+ letters (a trailing vowel, soft sign or
    short i is dropped first), whole-word match for words of up to 4 letters; spaces and hyphens are interchangeable."""
    parts = []
    for w in re.split(r"[\s-]+", kw.strip().lower()):
        if not w:
            continue
        if len(w) <= 4:
            parts.append(re.escape(w) + f"(?![{WORD}])")
        else:
            stem = re.sub(r"[аяыиеоуюйь]{1,2}$", "", w) if re.search("[а-яё]", w) else w
            parts.append(re.escape(stem) + f"[{WORD}]*")
    return f"(?<![{WORD}])" + r"[\s-]+".join(parts)


def niche_matchers(ws: Workspace) -> list[tuple[dict, re.Pattern | None]]:
    cfg = ws.load_config("ru_ecosystems.yaml", {}) or {}
    over = cfg.get("keywords") or {}
    out = []
    for n in ws.load_config("ru_b2b_niches.yaml", []) or []:
        kws = over.get(n["id"], n.get("bitrix") or [])
        out.append((n, re.compile("|".join(keyword_regex(str(k)) for k in kws), re.I) if kws else None))
    return out


# --- MoySklad --------------------------------------------------------------------------------------------------------

def parse_ms_categories(front: str) -> dict[str, str]:
    """Category slug -> name from the /integratsii/ page (the side menu)."""
    out = {}
    for slug, name in re.findall(r'href="/integratsii/([a-z0-9-]+)/"[^>]*>\s*([^<]+?)\s*</a>', front):
        if slug not in ("apps", "blog"):
            out.setdefault(slug, html.unescape(name).strip())
    return out


def parse_ms_tiles(page: str) -> list[tuple[str, str, str]]:
    """App tiles of a category page: (slug, name, short description)."""
    i = page.find('data-load-more="container"')
    grid = page[i:page.find('data-load-more="skeleton"', i)] if i >= 0 else page
    return [(s, html.unescape(n).strip(), _text(d)) for s, n, d in
            re.findall(r'href="/integratsii/apps/([^/"]+)/">([^<]+)</a></h3>\s*(?:<p[^>]*>(.*?)</p>)?', grid, re.S)]


def parse_ms_app(page: str) -> dict:
    name = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    dev = re.search(r'Разработчик</div>\s*(?:<a[^>]*>)?\s*([^<]+?)\s*<', page)
    up = re.search(r'data-ms-upload-date="([0-9-]{10})', page)
    body = page[name.end():] if name else ""
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.S)
    body = body.split("Другие решения этого разработчика")[0]     # the developer's other apps follow the description
    paid = 1 if "Платное решение" in page else 0 if "Бесплатное решение" in page else ""
    return {"name": _text(name.group(1)) if name else "", "developer": html.unescape(dev.group(1)).strip() if dev else "",
            "upload_date": up.group(1) if up else "", "paid": paid, "description": _text(body)[:600]}


def fetch_moysklad(ws: Workspace, sleep: float, max_apps: int = 0) -> list[dict]:
    month = f"{ws.today:%Y-%m}"
    sm = _get(ws, f"{MS}/sitemap.xml", f"ms_sitemap_{month}", sleep, min_size=10_000)
    slugs = list(dict.fromkeys(re.findall(r"/integratsii/apps/([^/<\s]+)/", sm)))
    front = _get(ws, f"{MS}/integratsii/", f"ms_front_{month}", sleep)
    cats = parse_ms_categories(front)
    tags: dict[str, list[str]] = {}
    tiles: dict[str, str] = {}
    for slug in cats:
        for app, _, desc in parse_ms_tiles(_get(ws, f"{MS}/integratsii/{slug}/", f"ms_cat_{slug}_{month}", sleep)):
            tags.setdefault(app, []).append(slug)
            tiles.setdefault(app, desc)
    if not slugs:          # sitemap unavailable: fall back to the apps seen on category pages
        slugs = list(tags)
    apps = []
    for i, slug in enumerate(slugs[:max_apps] if max_apps else slugs):
        page = _get(ws, f"{MS}/integratsii/apps/{slug}/", f"ms_app_{slug}", sleep)
        a = parse_ms_app(page) if page else {"name": "", "developer": "", "upload_date": "", "paid": "", "description": ""}
        if not a["name"]:
            continue
        a.update(slug=slug, categories=" ".join(tags.get(slug, [])), popular=int("populyarnoe" in tags.get(slug, [])),
                 text=f"{a['name']} {tiles.get(slug, '')} {a['description'][:400]}", url=f"{MS}/integratsii/apps/{slug}/")
        apps.append(a)
        if (i + 1) % 100 == 0:
            print(f"  moysklad: {i + 1}/{len(slugs)} app pages", flush=True)
    print(f"  moysklad: {len(slugs)} apps in the sitemap, {len(apps)} read, {len(cats)} categories")
    return apps


# --- amoCRM ----------------------------------------------------------------------------------------------------------

def parse_amo(page: str) -> list[tuple[str, str]]:
    """Widget tiles of an /extensions/ page: (slug, one-line description)."""
    return [(s, _text(d)) for s, d in re.findall(
        r'href="/extensions/([^"?/]+)/">.*?extensions__item-description">(.*?)</div>', page, re.S)]


def fetch_amocrm(ws: Workspace, sleep: float) -> list[dict]:
    month = f"{ws.today:%Y-%m}"
    apps: dict[str, dict] = {}
    for slug, desc in parse_amo(_get(ws, f"{AMO}/extensions/", f"amo_ext_{month}", sleep)):
        apps.setdefault(slug, {"slug": slug, "name": html.unescape(slug), "description": desc, "paid": "", "developer": "",
                               "upload_date": "", "popular": 0, "groups": []})
    for g in AMO_GROUPS:
        for slug, desc in parse_amo(_get(ws, f"{AMO}/extensions/?group={g}", f"amo_ext_{g}_{month}", sleep)):
            a = apps.setdefault(slug, {"slug": slug, "name": html.unescape(slug), "description": desc, "paid": "",
                                       "developer": "", "upload_date": "", "popular": 0, "groups": []})
            a["groups"].append(g)
    out = []
    for a in apps.values():
        a["popular"] = int("recommended" in a["groups"])
        a["categories"] = " ".join(a.pop("groups"))
        a["text"] = f"{a['name']} {a['description']}"
        a["url"] = f"{AMO}/extensions/{a['slug']}/"
        out.append(a)
    print(f"  amocrm: {len(out)} widgets in the public showcase")
    return out


# --- matching and metrics --------------------------------------------------------------------------------------------

def match_apps(ws: Workspace, market: str, apps: list[dict]) -> dict[str, list[dict]]:
    cats = ((ws.load_config("ru_ecosystems.yaml", {}) or {}).get("categories") or {}).get(market) or {}
    out: dict[str, list[dict]] = {}
    for n, rx in niche_matchers(ws):
        hits = []
        for a in apps:
            m = rx.search(a["text"]) if rx else None
            by = f"kw:{m.group(0).lower()}" if m else ""
            cat = next((c for c in cats.get(n["id"], []) if c in a["categories"].split()), "")
            if cat:
                by = (by + " " if by else "") + f"cat:{cat}"
            if by:
                hits.append(dict(a, matched_by=by))
        out[n["id"]] = hits
    return out


def metrics(nid: str, market: str, catalog: int, hits: list[dict], today: dt.date) -> dict:
    devs = Counter(a["developer"] for a in hits if a["developer"])
    paid_known = [a["paid"] for a in hits if a["paid"] != ""]
    top = devs.most_common(1)[0] if devs else ("", 0)
    cutoff = (today - dt.timedelta(days=365)).isoformat()
    return {"niche_id": nid, "marketplace": market, "catalog": catalog, "apps": len(hits),
            "share_of_catalog": round(len(hits) / catalog, 3) if catalog else "",
            "developers": len(devs) if devs else "", "top_developer": top[0], "top_developer_apps": top[1] or "",
            "top_developer_share": round(top[1] / len(hits), 2) if top[1] and hits else "",
            "paid_share": round(sum(paid_known) / len(paid_known), 2) if paid_known else "",
            "popular": sum(a["popular"] for a in hits),
            "updated_12m": sum(1 for a in hits if a["upload_date"] and a["upload_date"] >= cutoff) if market == "moysklad" else "",
            "examples": " | ".join(a["name"][:50] for a in hits[:5])}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    sleep = float((ws.load_config("ru_ecosystems.yaml", {}) or {}).get("sleep", 1.0))
    which = getattr(args, "marketplace", "all") or "all"
    catalogs: dict[str, list[dict]] = {}
    if which in ("moysklad", "all"):
        catalogs["moysklad"] = fetch_moysklad(ws, sleep, getattr(args, "max_apps", 0) or 0)
    if which in ("amocrm", "all"):
        catalogs["amocrm"] = fetch_amocrm(ws, sleep)
    print("  yclients: not read (catalog only through /api/, disallowed by robots.txt and token-gated)")
    rows, app_rows = [], []
    for market, apps in catalogs.items():
        if not apps:
            print(f"  {market}: catalog empty (blocked or layout changed) - no rows")
            continue
        for nid, hits in match_apps(ws, market, apps).items():
            hits.sort(key=lambda a: (-a["popular"], a["name"]))
            rows.append(metrics(nid, market, len(apps), hits, ws.today))
            for a in hits:
                app_rows.append({k: (a.get(k, "") if k not in ("marketplace", "niche_id") else "") for k in APP_FIELDS}
                                | {"marketplace": market, "niche_id": nid, "description": a["description"][:300]})
    if not rows:
        print("no catalog read - nothing written")
        return
    with open(ws.out("ru_ecosystems.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("ru_ecosystems_apps.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=APP_FIELDS)
        w.writeheader()
        w.writerows(app_rows)
    for nid in dict.fromkeys(r["niche_id"] for r in rows):
        rs = {r["marketplace"]: r for r in rows if r["niche_id"] == nid}
        print(f"  {nid:32} " + "  ".join(f"{m}={r['apps']:3} paid={r['paid_share']!s:4} top={r['top_developer'][:20]!r}"
                                          for m, r in rs.items()), flush=True)
    print(f"-> ru_ecosystems.csv {len(rows)} rows | apps {len(app_rows)}")
