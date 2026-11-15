"""Russian B2B: Bitrix24 Market (bitrix24.ru/apps/search/) — supply inside the most widespread Russian SMB platform.

For the `bitrix` keywords of each niche in config/ru_b2b_niches.yaml: up to 3 result pages -> apps (slug, name, installs,
ratings), deduplicated by slug within a niche. Metrics: number of apps, apps with at least 100 installs, sum of installs,
name and share of the leader, share of paid apps.
Cache: data/cache/bitrix/. Output: data/out/ru_b2b_bitrix.csv, ru_b2b_bitrix_apps.csv. Free, no key.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import time
from urllib.parse import quote

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Russian B2B: Bitrix24 Market apps per niche"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)


def get(ws: Workspace, u: str) -> str:
    key = hashlib.sha1(u.encode()).hexdigest()
    path = ws.cache("bitrix") / (key + ".html")
    if path.is_file():
        return path.read_text(encoding="utf-8")
    for attempt in range(3):
        try:
            s = http.request(u, backend="curl", timeout=60, tries=1, raise_for_status=False).text
        except OSError:
            s = ""
        if "market-app-tile" in s or "market-app-list" in s:
            path.write_text(s, encoding="utf-8")
            time.sleep(1.0)
            return s
        time.sleep(5 * (attempt + 1))
    return ""


def parse(s):
    apps = []
    for blk in re.split(r'class="market-app-list-items__item"', s)[1:]:
        m = re.search(r'market-app-tile-title"\s+title="([^"]*)"\s+href="/apps/app/([^/"]+)/"', blk)
        if not m:
            continue
        dl = re.search(r'rating-item:download">.*?rating-item__amount">\(?([\d\s]+)\)?', blk, flags=re.S)
        rt = re.search(r'rating-item:star">.*?rating-item__amount">\(?([\d\s]+)\)?', blk, flags=re.S)
        paid = "Подписка" in blk or "Платн" in blk    # the page's "Subscription" / "Paid" labels
        apps.append({"slug": m.group(2), "name": m.group(1), "installs": int(re.sub(r"\D", "", dl.group(1)) or 0) if dl else 0,
                     "ratings": int(re.sub(r"\D", "", rt.group(1)) or 0) if rt else 0, "paid": int(paid)})
    return apps


def run(ws: Workspace, args: argparse.Namespace) -> None:
    niches = ws.load_config("ru_b2b_niches.yaml")
    rows, apps_out = [], []
    for n in niches:
        seen = {}
        for kw in n.get("bitrix") or []:
            for page in (1, 2, 3):
                s = get(ws, f"https://www.bitrix24.ru/apps/search/?q={quote(kw)}&page={page}")
                apps = parse(s) if s else []
                if not apps:
                    break
                for a in apps:
                    seen.setdefault(a["slug"], dict(a, keyword=kw))
                if len(apps) < 20:
                    break
        its = sorted(seen.values(), key=lambda a: -a["installs"])
        total = sum(a["installs"] for a in its)
        rows.append({"niche_id": n["id"], "apps": len(its), "apps_100": sum(1 for a in its if a["installs"] >= 100),
                     "installs_sum": total, "top1": its[0]["name"] if its else "", "top1_installs": its[0]["installs"] if its else 0,
                     "top1_share": round(its[0]["installs"] / total, 2) if its and total else "", "paid_share": round(sum(a["paid"] for a in its) / len(its), 2) if its else ""})
        for a in its:
            apps_out.append(dict(niche_id=n["id"], **a))
        r = rows[-1]
        print(f"{n['id']:32} apps={r['apps']:3} >=100={r['apps_100']:3} installs={r['installs_sum']:7} top1={r['top1'][:40]!r} {r['top1_share']}", flush=True)
    with open(ws.out("ru_b2b_bitrix.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("ru_b2b_bitrix_apps.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "slug", "name", "installs", "ratings", "paid", "keyword"])
        w.writeheader()
        w.writerows(apps_out)
    print("-> ru_b2b_bitrix.csv", len(rows), "| apps", len(apps_out))
