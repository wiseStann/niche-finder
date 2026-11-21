"""S5 evidence: supply inside two more app ecosystems, the Chrome Web Store and the Atlassian Marketplace.

What it measures: for the shortlisted niches where the channel is real (config/ecosystems_map.yaml), how many products
the store already has and how adoption is spread among them, the way s5_shopify_metrics does for Shopify: relevant
products, players above size thresholds, the leader's share, the top-3 share, HHI, the free share and the top 3.
  - Chrome Web Store: size = users (Chrome counts a user as an install that checked for updates in the last week; the
    store rounds the number and caps the display at 10,000,000+). Search goes through the store's own data endpoint
    (batchexecute RPC zTyKYc, the call the search page makes), 150 results per page; when that endpoint fails, the
    server-rendered search page gives the first 10. Extensions have no store price (payments were retired in 2020),
    so free_share stays empty.
  - Atlassian Marketplace: size = active installs (distribution.totalInstalls of the REST v2 listing; one install is
    one Jira/Confluence site, not one user). Hosting is cloud by default. free = the app is also returned by the same
    search with cost=free (a free app, not a free tier).
Every result is kept only if its name + description matches the niche: the `match`/`not` regexes of the map, or the
niche's regex from niches.text_matchers (config/deal_keywords.yaml / coverage phrases) when the map has none.
Products are deduplicated per niche and store across its queries.

Inputs: config/ecosystems_map.yaml (niche -> cws / atlassian queries, match, not), config/shortlist.yaml.
Outputs: data/out/ecosystems_metrics.csv (one row per niche x store), data/out/ecosystems_items.csv (every fetched
product with a `relevant` flag, so the filter can be audited).
Cache: data/cache/cws/ and data/cache/atlassian/, keyed by the run month (ws.today:%Y-%m): a re-run in the same month
is free, the next month fetches fresh lists. Cost: free, no key; about one request per CWS query and 8 per Atlassian
query (4 pages of 50, plus the same for cost=free), 0.5-1 s apart.
Caveats: evidence only, it never changes the S6 score or verdict. CWS user counts are rounded weekly users, not
buyers; many extensions are free companions of a web product, so a big extension can be the tip of a paid SaaS.
Store search ranks by relevance, and the deeper pages are long tail; a niche whose market sits outside the browser
(mobile-first B2C) has no entry in the map.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
from typing import Any, Callable

from nichefinder import http, niches
from nichefinder.workspace import Workspace

SUMMARY = "Chrome Web Store and Atlassian Marketplace supply per niche (evidence)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

CWS_RPC = "zTyKYc"
CWS_RPC_URL = f"https://chromewebstore.google.com/_/ChromeWebStoreConsumerFeUi/data/batchexecute?rpcids={CWS_RPC}&hl=en&rt=c"
CWS_SEARCH_URL = "https://chromewebstore.google.com/search/{q}?hl=en"
CWS_PAGE = 150            # the store caps one RPC page at 150 results
CWS_ID = re.compile(r"[a-p]{32}")
ATL_URL = "https://marketplace.atlassian.com/rest/2/addons"
ATL_PAGE = 50
THRESHOLDS = (100, 1_000, 10_000, 100_000)
DEFAULTS = {"cws_pages": 1, "atlassian_pages": 4, "atlassian_hosting": "cloud"}


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--niche", action="append", default=[], help="measure only these niche ids (repeatable)")
    p.add_argument("--store", choices=("cws", "atlassian"), action="append", default=[], help="only this store (repeatable)")


# ---- Chrome Web Store ---------------------------------------------------------

def _cws_walk(data: Any) -> list[list]:
    """Item tuples anywhere in a search payload: a list that starts with a 32-letter extension id and a name."""
    out: list[list] = []

    def walk(o: Any) -> None:
        if isinstance(o, list):
            if len(o) > 15 and isinstance(o[0], str) and CWS_ID.fullmatch(o[0]) and isinstance(o[2], str):
                out.append(o)
                return
            for x in o:
                walk(x)
    walk(data)
    return out


def _num(v: Any) -> float:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def cws_items(data: Any) -> list[dict]:
    """[id, icon, name, rating, ratings, image, description, website, ..., [category], ..., users, ...] -> dicts."""
    items = []
    for o in _cws_walk(data):
        cat = o[11][0] if isinstance(o[11], list) and o[11] and isinstance(o[11][0], str) else ""
        items.append({"id": o[0], "name": o[2], "text": o[6] if isinstance(o[6], str) else "", "size": int(_num(o[14])),
                      "rating": round(_num(o[3]), 2) if o[3] else "", "ratings": int(_num(o[4])), "free": "",
                      "category": cat, "url": f"https://chromewebstore.google.com/detail/{o[0]}"})
    return items


def cws_tail(data: Any) -> tuple[str | None, int | None]:
    """(continuation token, total results the store reports) from the last element of a search payload."""
    tail = data[-1] if isinstance(data, list) and data and isinstance(data[-1], list) else []
    token = tail[0] if tail and isinstance(tail[0], str) else None
    total = tail[3] if len(tail) > 3 and isinstance(tail[3], int) else None
    return token, total


def parse_rpc(text: str) -> Any:
    """The payload of the zTyKYc answer in a batchexecute response (`)]}'` + length-prefixed JSON lines), or None."""
    for line in text.splitlines():
        if line.startswith('[["wrb.fr"'):
            try:
                arr = json.loads(line)
            except ValueError:
                continue
            for part in arr:
                if isinstance(part, list) and len(part) > 2 and part[0] == "wrb.fr" and part[1] == CWS_RPC and isinstance(part[2], str):
                    return json.loads(part[2])
    return None


def parse_search_page(html: str) -> Any:
    """The ds:1 data block of the server-rendered search page (its first 10 results), or None."""
    m = re.search(r"AF_initDataCallback\(\{key: 'ds:1', hash: '\d+', data:", html)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(html[m.end():])[0]
    except ValueError:
        return None


def _cached(ws: Workspace, ns: str, key: str, fetch: Callable[[], Any]) -> Any:
    path = http.cache_file(ws.cache(ns), key, ".json")
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    if data is not None:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def cws_search(ws: Workspace, q: str, pages: int) -> tuple[list[dict], int | None, str]:
    """Up to pages x 150 results for one query: (items, reported total, how they were fetched)."""
    month = f"{ws.today:%Y-%m}"
    items: list[dict] = []
    total, token, how = None, None, "rpc"
    for p in range(max(1, pages)):
        req = [[None, [None, None, None, [q, [CWS_PAGE, token] if token else [CWS_PAGE]]]]]

        def fetch(req=req):
            body = "f.req=" + urllib.parse.quote(json.dumps([[[CWS_RPC, json.dumps(req), None, "generic"]]]))
            try:
                r = http.request(CWS_RPC_URL, method="POST", data=body, tries=2, raise_for_status=False,
                                 headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
                data = parse_rpc(r.text) if r.status == 200 else None
            except (OSError, ValueError):
                data = None
            time.sleep(1.0)
            return data
        data = _cached(ws, "cws", f"{month}|rpc|{q}|{p}", fetch)
        if data is None and p == 0:
            how = "page"

            def fetch_page():
                try:
                    html = http.request(CWS_SEARCH_URL.format(q=urllib.parse.quote(q)), tries=2).text
                except OSError:
                    return None
                time.sleep(1.0)
                return parse_search_page(html)
            data = _cached(ws, "cws", f"{month}|page|{q}", fetch_page)
        if data is None:
            how = how if items else "failed"
            break
        got = cws_items(data)
        items += got
        token, t = cws_tail(data)
        total = t if t is not None else total
        if how == "page" or not token or len(got) < CWS_PAGE:
            break
    return items, total, how


# ---- Atlassian Marketplace ----------------------------------------------------

def atl_items(data: dict) -> list[dict]:
    out = []
    for a in (data.get("_embedded") or {}).get("addons") or []:
        e = a.get("_embedded") or {}
        dist, rev = e.get("distribution") or {}, e.get("reviews") or {}
        alt = ((a.get("_links") or {}).get("alternate") or {}).get("href", "")
        out.append({"id": a.get("key", ""), "name": a.get("name", ""), "text": f"{a.get('tagLine') or ''} {a.get('summary') or ''}",
                    "size": max(int(_num(dist.get("totalInstalls"))), 0),
                    "rating": round(_num(rev.get("averageStars")), 2) if rev.get("averageStars") else "",
                    "ratings": int(_num(rev.get("count"))), "free": 0,
                    "category": " | ".join(c.get("name", "") for c in e.get("categories") or []),
                    "url": "https://marketplace.atlassian.com" + alt if alt else ""})
    return out


def atl_search(ws: Workspace, q: str, pages: int, hosting: str, cost: str = "") -> tuple[list[dict], int | None]:
    month = f"{ws.today:%Y-%m}"
    items: list[dict] = []
    total = None
    for p in range(max(1, pages)):
        params = {"text": q, "limit": ATL_PAGE, "offset": p * ATL_PAGE}
        if hosting:
            params["hosting"] = hosting
        if cost:
            params["cost"] = cost
        url = f"{ATL_URL}?{urllib.parse.urlencode(params)}"
        try:
            data = http.get_json(url, cache=ws.cache("atlassian"), cache_key=f"{month}|{url}", sleep=0.5, tries=3)
        except (OSError, ValueError, http.HttpError) as e:
            print(f"    atlassian {q!r} page {p}: {str(e)[:120]}")
            break
        got = atl_items(data)
        items += got
        total = data.get("count", total)
        if len(got) < ATL_PAGE:
            break
    return items, total


# ---- metrics ------------------------------------------------------------------

def concentration(items: list[dict]) -> dict:
    """Shopify-style concentration of `size` (users or installs) over the relevant products."""
    lst = sorted(items, key=lambda r: -r["size"])
    v = [r["size"] for r in lst]
    tot = sum(v)
    free = [r["free"] for r in lst if r["free"] != ""]
    row = {"products": len(lst), **{f"players_{_k(t)}": sum(1 for x in v if x >= t) for t in THRESHOLDS},
           "users_total": tot, "top1": lst[0]["name"] if lst else "", "top1_users": v[0] if v else "",
           "top1_share": round(v[0] / tot, 3) if tot else "", "top3_share": round(sum(v[:3]) / tot, 3) if tot else "",
           "hhi": round(sum((x / tot) ** 2 for x in v), 3) if tot else "",
           "free_share": round(sum(free) / len(free), 2) if free else "",
           "ratings_total": sum(r["ratings"] for r in lst),
           "top3": " | ".join(f"{r['name']} ({r['size']:,})" for r in lst[:3])}
    return row


def _k(t: int) -> str:
    return f"{t // 1000}k" if t >= 1000 else str(t)


def matcher_for(nid: str, entry: dict, fallback: dict[str, Callable[[str], bool]]) -> Callable[[str], bool] | None:
    pos, neg = entry.get("match"), entry.get("not")
    if pos:
        rp, rn = re.compile(pos, re.I), re.compile(neg, re.I) if neg else None
        return lambda t: bool(rp.search(t)) and not (rn is not None and rn.search(t))
    base = fallback.get(nid)
    if base and neg:
        rn = re.compile(neg, re.I)
        return lambda t: base(t) and not rn.search(t)
    return base


# ---- run ----------------------------------------------------------------------

def run(ws: Workspace, args: argparse.Namespace) -> None:
    emap = dict(ws.load_config("ecosystems_map.yaml", {}) or {})
    st = {**DEFAULTS, **(emap.pop("_settings", None) or {})}
    if not emap:
        print("config/ecosystems_map.yaml has no niches - nothing to measure")
        return
    short = set(niches.shortlist_ids(ws))
    want = set(getattr(args, "niche", None) or [])
    stores = getattr(args, "store", None) or ["cws", "atlassian"]
    fallback = niches.text_matchers(ws, sorted(short))
    rows, items_out = [], []
    for nid, entry in emap.items():
        entry = entry or {}
        if want and nid not in want:
            continue
        if nid not in short:
            print(f"{nid:34} not shortlisted - skipped")
            continue
        match = matcher_for(nid, entry, fallback)
        if match is None:
            print(f"{nid:34} no `match` in the map and no regex in deal_keywords/coverage_keywords - every result counts")
        for store in ("cws", "atlassian"):
            qs = [q for q in entry.get(store) or [] if q]
            if not qs or store not in stores:
                continue
            seen: dict[str, dict] = {}
            reported: list[str] = []
            free_ids: set[str] = set()
            for q in qs:
                if store == "cws":
                    got, total, how = cws_search(ws, q, int(st["cws_pages"]))
                    reported.append(f"{q}={total if total is not None else '?'}" + ("" if how == "rpc" else f" ({how})"))
                else:
                    got, total = atl_search(ws, q, int(st["atlassian_pages"]), st["atlassian_hosting"] or "")
                    free, _ = atl_search(ws, q, int(st["atlassian_pages"]), st["atlassian_hosting"] or "", cost="free")
                    free_ids |= {r["id"] for r in free}
                    reported.append(f"{q}={total if total is not None else '?'}")
                for r in got:
                    if r["id"] not in seen:
                        seen[r["id"]] = dict(r, query=q, relevant=int(match is None or match(f"{r['name']} {r['text']}")))
            if store == "atlassian":
                for r in seen.values():
                    r["free"] = int(r["id"] in free_ids)
            rel = [r for r in seen.values() if r["relevant"]]
            row = {"niche_id": nid, "store": store, "unit": "users" if store == "cws" else "installs",
                   "queries": " | ".join(qs), "reported": " | ".join(reported), "fetched": len(seen), **concentration(rel)}
            rows.append(row)
            for r in sorted(seen.values(), key=lambda r: (-r["relevant"], -r["size"])):
                items_out.append({"niche_id": nid, "store": store, "id": r["id"], "name": r["name"], "relevant": r["relevant"],
                                  "users": r["size"], "rating": r["rating"], "ratings": r["ratings"], "free": r["free"],
                                  "category": r["category"], "query": r["query"], "url": r["url"],
                                  "description": re.sub(r"\s+", " ", r["text"]).strip()[:200]})
            t1 = row["top1_share"]
            print(f"{nid:34} {store:9} fetched={len(seen):>4} products={row['products']:>4} >=1k={row['players_1k']:>3} "
                  f">=10k={row['players_10k']:>3} total={row['users_total']:>10,} top1={'' if t1 == '' else format(t1, '.0%')} "
                  f"free={row['free_share']} | {row['top1'][:40]}", flush=True)
    if not rows:
        print("no niche measured - check config/ecosystems_map.yaml against config/shortlist.yaml")
        return
    p, p2 = ws.out("ecosystems_metrics.csv"), ws.out("ecosystems_items.csv")
    if want or getattr(args, "store", None):
        # a partial run (--niche / --store) replaces only the rows it measured
        done = {(r["niche_id"], r["store"]) for r in rows}
        rows = _kept(p, done) + rows
        items_out = _kept(p2, done) + items_out
    for path, data in ((p, rows), (p2, items_out)):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()) if data else ["niche_id"])
            w.writeheader()
            w.writerows(data)
    print("->", p, len(rows), "|", p2, len(items_out))


def _kept(path, done: set) -> list[dict]:
    if not path.is_file():
        return []
    return [r for r in csv.DictReader(open(path, encoding="utf-8")) if (r.get("niche_id"), r.get("store")) not in done]
