"""B2C pricing (switching cost / monetization): in-app purchases of the top niche apps from apps.apple.com pages.

Top-N relevant US apps by ratings -> the app page -> the "In-App Purchases" block (name, price). From the list it derives
whether the app has IAP and the lowest monthly / yearly / weekly / lifetime price.
Inputs: data/out/appstore_apps.csv, config/appstore_relevance.yaml (niches with `na: true` are skipped).
Outputs: data/out/pricing_b2c.csv (per app) and data/out/pricing_b2c_niche.csv (per niche aggregate).
Pages are cached in data/cache/appstore_pages/. Needs curl. No key.
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import time
from collections import defaultdict

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "In-app purchase prices of top App Store apps (apps.apple.com pages)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("curl",)

TOP_N = 8


def fetch(ws: Workspace, track_id, country: str = "us") -> str:
    path = ws.cache("appstore_pages") / f"{country}_{track_id}.html"
    if path.exists() and path.stat().st_size > 20000:
        return path.read_text(encoding="utf-8", errors="ignore")
    url = f"https://apps.apple.com/{country}/app/id{track_id}"
    for attempt in range(3):
        try:
            text = http.request(url, backend="curl", timeout=60, headers={"Accept-Language": "en-US"},
                                tries=1, raise_for_status=False).text
        except OSError:
            text = ""
        if len(text) > 20000:
            path.write_text(text, encoding="utf-8")
            time.sleep(0.8)
            return text
        time.sleep(5 * (attempt + 1))
    return ""


def parse_iap(s: str):
    i = s.find("In-App Purchases")
    if i < 0:
        return None
    seg = s[i:i + 6000]
    txt = re.sub(r"<[^>]+>", "|", seg)
    txt = html.unescape(re.sub(r"[\s|]*\|[\s|]*", "|", txt))
    items = re.findall(r"\|([^|]{2,80})\|\$([\d,]+\.\d\d)", txt)
    return [(n.strip(), float(p.replace(",", ""))) for n, p in items]


def classify(items):
    monthly = [p for n, p in items if re.search(r"month|monthly|/mo\b|1 mo", n, re.I) and not re.search(r"3.month|6.month|12.month|year", n, re.I)]
    yearly = [p for n, p in items if re.search(r"year|annual|12.month|yr\b", n, re.I)]
    weekly = [p for n, p in items if re.search(r"week", n, re.I)]
    lifetime = [p for n, p in items if re.search(r"lifetime|forever|one.time|unlock", n, re.I)]
    return {"iap_n": len(items), "min_monthly": min(monthly) if monthly else "", "min_yearly": min(yearly) if yearly else "",
            "min_weekly": min(weekly) if weekly else "", "min_lifetime": min(lifetime) if lifetime else "",
            "max_price": max((p for _, p in items), default="")}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    src = ws.out("appstore_apps.csv")
    if not src.is_file():
        print(f"{src} not found - run s5_appstore first; skipping")
        return
    rel = ws.load_config("appstore_relevance.yaml", {}) or {}
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    by = defaultdict(list)
    for r in rows:
        if r["relevant"] == "1" and r["store"] == "us":
            by[r["niche_id"]].append(r)
    out, agg = [], []
    for nid, rs in sorted(by.items()):
        if ((rel.get(nid) or {}).get("us") or {}).get("na"):
            continue
        rs.sort(key=lambda r: -int(r["ratings"]))
        top = rs[:TOP_N]
        stats = []
        for r in top:
            s = fetch(ws, r["track_id"])
            items = parse_iap(s) if s else None
            c = classify(items or [])
            rec = {"niche_id": nid, "track_id": r["track_id"], "name": r["name"][:40], "ratings": r["ratings"],
                   "price": r["price"], "fetched": int(bool(s)), "has_iap": int(bool(items)), **c,
                   "iap_sample": "; ".join(f"{n[:25]} ${p}" for n, p in (items or [])[:5])}
            out.append(rec); stats.append(rec)
            print(f"{nid:32} {r['name'][:28]:28} iap={rec['has_iap']} mo={rec['min_monthly']} yr={rec['min_yearly']} wk={rec['min_weekly']} life={rec['min_lifetime']}")
        paid = [x for x in stats if x["has_iap"] or float(x["price"]) > 0]
        mo = [x["min_monthly"] for x in stats if x["min_monthly"] != ""]
        yr = [x["min_yearly"] for x in stats if x["min_yearly"] != ""]
        agg.append({"niche_id": nid, "n": len(stats), "monetized_share": round(len(paid) / len(stats), 2) if stats else "",
                    "with_monthly": len(mo), "median_monthly": round(sorted(mo)[len(mo) // 2], 2) if mo else "",
                    "median_yearly": round(sorted(yr)[len(yr) // 2], 2) if yr else "",
                    "with_weekly": sum(1 for x in stats if x["min_weekly"] != ""),
                    "with_lifetime": sum(1 for x in stats if x["min_lifetime"] != "")})
    if not out:
        print("no apps to price - nothing written")
        return
    with open(ws.out("pricing_b2c.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    with open(ws.out("pricing_b2c_niche.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(agg[0].keys())); w.writeheader(); w.writerows(agg)
    print("-> pricing_b2c.csv", len(out), "| pricing_b2c_niche.csv", len(agg))
