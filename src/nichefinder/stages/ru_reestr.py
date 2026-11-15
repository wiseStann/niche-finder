"""Russian B2B: the register of domestic software (reestr.digital.gov.ru) — supply per niche and a map of classes.

Searches by product name (PROD_NAME, substring) for the `reestr` keywords of each niche in config/ru_b2b_niches.yaml,
100 results per page. Per niche: products (deduplicated by id), owners, new products by registration year
(2023/2024/2025/2026), top classes, share of the largest owner, number of products flagged as AI.
`--classes` instead writes the class map of classifier 486 (products and AI products per class).
Cache: data/cache/reestr/. Output: data/out/ru_b2b_reestr.csv, ru_b2b_reestr_items.csv, ru_b2b_reestr_classes.csv. Free, no key.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import time
from collections import Counter
from urllib.parse import quote

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Russian B2B: domestic software register (supply per niche, class map)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)

BASE = "https://reestr.digital.gov.ru/reestr/"
ITEM = re.compile(r'data-href="/reestr/(\d+)/">(.*?)(?=<div class="item collection-item|<!--\'end_frame_cache|</div>\s*</div>\s*<div class="nav-line)', re.S)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--classes", action="store_true", help="write the class map of classifier 486 instead of the niche table")


def get(ws: Workspace, url: str) -> str:
    key = hashlib.sha1(url.encode()).hexdigest()
    path = ws.cache("reestr") / (key + ".html")
    if path.is_file():
        return path.read_text(encoding="utf-8")
    for attempt in range(3):
        try:
            s = http.request(url, backend="curl", timeout=60, tries=1, raise_for_status=False).text
        except OSError:
            s = ""
        if "collection-registry" in s or "tabs-list__item-counter" in s:
            path.write_text(s, encoding="utf-8")
            time.sleep(0.8)
            return s
        time.sleep(5 * (attempt + 1))
    return ""


def parse_items(s):
    out = []
    for m in ITEM.finditer(s):
        blk = m.group(2)
        date = re.search(r"<span>(\d\d\.\d\d\.\d{4})</span>", blk)
        name = re.search(r'data-name="Наименование ПО" data-title>([^<]*)', blk)
        owner = re.search(r'owner-name">([^<]*)', blk)
        classes = re.findall(r'class-code">([^<]+)</span>\s*<span>([^<]+)', blk)
        out.append({"id": m.group(1), "date": date.group(1) if date else "", "name": (name.group(1) if name else "").strip(),
                    "owner": (owner.group(1) if owner else "").strip(), "classes": "; ".join(f"{c} {n.strip()}" for c, n in classes)})
    return out


def count_active(s):
    m = re.search(r'tabs-list__item-counter">([\d\s]+)<', s)
    return int(re.sub(r"\D", "", m.group(1))) if m else 0


def search(ws, keyword, ai=False):
    extra = "&IS_AI=Y" if ai else ""
    url = f"{BASE}?PROD_NAME={quote(keyword)}&PAGE_S=100&PAGE_N=1{extra}"
    s = get(ws, url)
    if not s:
        return 0, []
    total = count_active(s)
    items = parse_items(s)
    page = 2
    while len(items) < min(total, 500) and page <= 5:
        s2 = get(ws, f"{BASE}?PROD_NAME={quote(keyword)}&PAGE_S=100&PAGE_N={page}{extra}")
        more = parse_items(s2)
        if not more:
            break
        items += more
        page += 1
    return total, items


def classes_map(ws):
    s = get(ws, BASE + "?CLASSIFIER=486")
    # the second select (js-class-po-sync without a name) holds class names, the first holds codes; the order matches
    sels = re.findall(r'<select[^>]*js-class-po-sync[^>]*>(.*?)</select>', s, flags=re.S)
    codes = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>\s*-?\s*([^<]*?)\s*</option>', sels[0]) if sels else []
    names = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>\s*-?\s*([^<]*?)\s*</option>', sels[1]) if len(sels) > 1 else []
    nm = {v: t for v, t in names}
    rows = []
    for v, code in codes:
        if v.startswith("s"):
            continue
        u = f"{BASE}?CLASSIFIER=486&PROD_CLASS[]={v}&PAGE_S=20&PAGE_N=1"
        page = get(ws, u)
        n = count_active(page)
        ai = count_active(get(ws, u + "&IS_AI=Y"))
        rows.append({"class_id": v, "code": code, "name": nm.get(v, ""), "products": n, "ai_products": ai})
        print(f"  class {code:6} {nm.get(v, '')[:60]:60} {n:6} (AI {ai})", flush=True)
    with open(ws.out("ru_b2b_reestr_classes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["class_id", "code", "name", "products", "ai_products"])
        w.writeheader()
        w.writerows(rows)
    print("-> ru_b2b_reestr_classes.csv", len(rows))


def run(ws: Workspace, args: argparse.Namespace) -> None:
    if args.classes:
        classes_map(ws)
        return
    niches = ws.load_config("ru_b2b_niches.yaml")
    rows, items_out = [], []
    for n in niches:
        seen = {}
        per_kw = []
        ai_ids = set()
        for kw in n.get("reestr") or []:
            total, items = search(ws, kw)
            per_kw.append(f"{kw}={total}")
            for it in items:
                seen.setdefault(it["id"], dict(it, keyword=kw))
            _, ai_items = search(ws, kw, ai=True)   # the register's AI flag: how many AI products the niche has
            ai_ids.update(it["id"] for it in ai_items)
        its = list(seen.values())
        for it in its:
            it["ai"] = int(it["id"] in ai_ids)
        years = Counter(it["date"][-4:] for it in its if it["date"])
        owners = Counter(it["owner"] for it in its if it["owner"])
        cls = Counter(c.strip() for it in its for c in it["classes"].split(";") if c.strip())
        top_owner, top_owner_n = (owners.most_common(1)[0] if owners else ("", 0))
        rows.append({"niche_id": n["id"], "products": len(its), "ai_products": sum(it["ai"] for it in its), "owners": len(owners), "top_owner": top_owner,
                     "top_owner_share": round(top_owner_n / len(its), 2) if its else "", "new_2023": years.get("2023", 0),
                     "new_2024": years.get("2024", 0), "new_2025": years.get("2025", 0), "new_2026": years.get("2026", 0),
                     "top_classes": " | ".join(f"{c} ({k})" for c, k in cls.most_common(3)), "per_keyword": "; ".join(per_kw)})
        for it in its:
            items_out.append(dict(niche_id=n["id"], **it))
        print(f"{n['id']:32} {len(its):4} products (AI {sum(it['ai'] for it in its)}), {len(owners):4} owners, new 24/25/26: {years.get('2024', 0)}/{years.get('2025', 0)}/{years.get('2026', 0)}  [{'; '.join(per_kw)}]", flush=True)
    with open(ws.out("ru_b2b_reestr.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("ru_b2b_reestr_items.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "id", "date", "name", "owner", "classes", "keyword", "ai"])
        w.writeheader()
        w.writerows(items_out)
    print("-> ru_b2b_reestr.csv", len(rows), "| items", len(items_out))
