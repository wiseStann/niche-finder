"""Switching intent in search: how many people look for a way out of the niche's incumbents.

For every brand query in queries/*.yaml (intent `brand`, brand name `b`) the stage builds phrases from config/switch_intent.yaml:
  alternative - "<brand> alternative(s)", "apps like <brand>", "analog <brand>" (in Russian): people shopping for a substitute;
  churn       - "cancel <brand>", "cancel subscription <brand>" (in Russian): people leaving, a B2C churn signal.
Phrases that Keyword Planner answers as one group of close variants (identical monthly history for the same brand and
kind, e.g. singular and plural) are counted once. Volumes come from DataForSEO Google Ads search volume with 24 months of history (one call per pool and batch of up to 1000
phrases, about $0.09), pools us (United States, English) and ru (Russian-language worldwide), as in s3_dataforseo.
Per niche and pool: brand demand (from dfs_<pool>.csv), alternative and churn volumes, their ratio to brand demand
(switching intensity that does not grow with brand size), the last-12 vs prior-12 change of alternative searches, the brand
people most want to leave, and the percentile of the alternative ratio within the B2C or B2B cohort.

Outputs: data/out/switch_intent_kw.csv (phrase level), data/out/switch_intent.csv (niche level).
Evidence only: shown in passports beside the manual lock-in and the S10 switching shares, never in the score.
Cost: printed before any call (--dry stops there); batches are cached by content, so re-runs are free.
Homonyms: a brand that is also a common word ("Paprika", "Choco", "Sling" TV) draws switching phrases about the word. Brands
listed under `homonyms` in config/switch_intent.yaml are left out of the niche's sums; a brand whose phrases exceed half of
its own brand demand (and 300 a month) is only marked in `suspects` for a human to decide. Caveats: a common-word brand below that line still inflates its phrases; Keyword Planner rounds small volumes and
returns nothing below ~10/month, so a missing phrase is "too small to measure", not zero demand.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections import defaultdict

from nichefinder import niches
from nichefinder.sources import dataforseo as dfs
from nichefinder.workspace import Workspace

SUMMARY = "Switching intent: search volume of '<brand> alternative' / 'analog <brand>' queries"
KEYS: tuple[str, ...] = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")

POOLS = {"us": {"lang": "en", "location_code": 2840, "language_code": "en"},
         "ru": {"lang": "ru", "location_code": None, "language_code": "ru"}}
DEFAULT_TEMPLATES = {
    "en": {"alternative": ["{b} alternative", "{b} alternatives", "alternatives to {b}", "apps like {b}"],
           "churn": ["cancel {b}", "{b} cancel subscription"]},
    "ru": {"alternative": ["аналог {b}", "аналоги {b}"],
           "churn": ["отменить подписку {b}"]},
}
B2B = {"b2b-smb", "b2b", "b2b-mid"}


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("pools", nargs="*", help="us, ru (default: those of nf.yaml markets)")
    p.add_argument("--dry", action="store_true", help="print the phrase counts and the expected cost, make no calls")


def templates(ws: Workspace) -> dict:
    return (ws.load_config("switch_intent.yaml", {}) or {}).get("templates") or DEFAULT_TEMPLATES


def phrases(ws: Workspace, lang: str) -> list[dict]:
    """[{phrase, niche_id, brand, kind}] for every brand query of the language, de-duplicated per (niche, phrase)."""
    tpl = templates(ws).get(lang) or {}
    out, seen = [], set()
    for r in niches.keyword_rows(ws, lang):
        if r["intent"] != "brand" or not r["brand"]:
            continue
        b = " ".join(re.sub(r"[^\w\s'&.+-]", " ", str(r["brand"]).lower()).split())   # the API rejects (), quotes and the like
        if not b:
            continue
        for kind, forms in tpl.items():
            for f in forms:
                ph = " ".join(f.format(b=b).lower().split())
                if (r["niche_id"], ph) not in seen:
                    seen.add((r["niche_id"], ph))
                    out.append({"phrase": ph, "niche_id": r["niche_id"], "brand": r["brand"], "kind": kind})
    return out


def date_from(ws: Workspace, months: int = 24) -> str:
    idx = ws.today.year * 12 + (ws.today.month - 1) - months
    return f"{idx // 12}-{idx % 12 + 1:02d}-01"


def batches(items: list[str]) -> list[list[str]]:
    uniq = sorted(set(items))
    return [uniq[i:i + dfs.BATCH] for i in range(0, len(uniq), dfs.BATCH)]


def last12_vs_prev12(monthly: list[tuple[str, int]]) -> tuple[int, int]:
    m = sorted(monthly)[-24:]
    return sum(v for _, v in m[-12:]), sum(v for _, v in m[:-12]) if len(m) > 12 else 0


def brand_volumes(ws: Workspace, pool: str, lang: str) -> dict[tuple[str, str], int]:
    """(niche_id, brand) -> monthly volume of its brand queries, from dfs_<pool>.csv (s3_dataforseo)."""
    p = ws.out(f"dfs_{pool}.csv")
    vol = {}
    if p.is_file():
        vol = {r["keyword"]: int(float(r["search_volume"] or 0)) for r in csv.DictReader(open(p, encoding="utf-8"))}
    out: dict[tuple[str, str], int] = defaultdict(int)
    for r in niches.keyword_rows(ws, lang):
        if r["intent"] == "brand" and r["brand"]:
            out[(r["niche_id"], r["brand"])] += vol.get(r["q"].strip().lower(), 0)
    return out


def percentiles(values: dict[str, float]) -> dict[str, float]:
    xs = sorted(values.values())
    if not xs:
        return {}
    return {k: round(sum(1 for x in xs if x <= v) / len(xs), 2) for k, v in values.items()}


HOMONYM_RATIO = 0.5    # switching phrases above half of the brand's own demand mean another word ("paprika alternative")
HOMONYM_MIN = 300      # ... and above this monthly volume, so small brands with a few searches are not dropped by noise


def summarize(kw_rows: list[dict], bvol: dict, side: dict[str, str], pool: str, exclude: set[str] | None = None) -> list[dict]:
    # per (niche, brand): alternative / churn volumes and the alternative series sums, close variants counted once.
    # Keyword Planner returns one volume for a group of close variants ("x alternative" / "x alternatives": identical
    # history in 265 of 273 brands on 2026-11-23), so a phrase whose monthly series repeats one already counted for the
    # same niche, brand and kind is the same searches.
    per_brand: dict[tuple[str, str], dict] = {}
    seen: set = set()
    for r in kw_rows:
        if int(r["volume"] or 0):
            key = (r["niche_id"], r["brand"], r["kind"], r["volume"], r.get("monthly_json", ""))
            if key in seen:
                continue
            seen.add(key)
        b = per_brand.setdefault((r["niche_id"], r["brand"]), {"alt": 0, "churn": 0, "alt12": 0, "altprev": 0})
        v = int(r["volume"] or 0)
        b["alt" if r["kind"] == "alternative" else "churn"] += v
        if r["kind"] == "alternative":
            b["alt12"] += int(r["last12"] or 0)
            b["altprev"] += int(r["prev12"] or 0)
    per: dict[str, dict] = {}
    for (nid, brand), b in per_brand.items():
        d = per.setdefault(nid, {"alt": 0, "churn": 0, "alt12": 0, "altprev": 0, "by_brand": defaultdict(int),
                                 "homonyms": [], "suspects": []})
        own = bvol.get((nid, brand), 0)
        tot = b["alt"] + b["churn"]
        # A brand that is also a common word ("Paprika", "Choco", "Sling" TV) draws "alternative" / "cancel" searches about
        # the word. Brands listed under `homonyms` in config/switch_intent.yaml are left out of the niche's sums. The ratio
        # rule only marks suspects for a human: genuine switching is a few percent of brand demand, but a narrow brand
        # query ("mindbody app") makes a real brand look high and a homonymous brand query ("sling") hides a homonym.
        if brand.lower() in (exclude or set()):
            d["homonyms"].append(f"{brand} ({tot:,})")
            continue
        if tot > max(HOMONYM_RATIO * own, HOMONYM_MIN):
            d["suspects"].append(f"{brand} ({tot:,} vs brand {own:,})")
        for k2 in ("alt", "churn", "alt12", "altprev"):
            d[k2] += b[k2]
        d["by_brand"][brand] += b["alt"]
    rows = []
    for nid, d in per.items():
        bv = sum(v for (n, _), v in bvol.items() if n == nid)
        top = max(d["by_brand"].items(), key=lambda kv: kv[1], default=("", 0))
        rows.append({"niche_id": nid, "pool": pool, "side": side.get(nid, ""), "brand_volume": bv,
                     "alt_volume": d["alt"], "churn_volume": d["churn"],
                     "alt_ratio": round(d["alt"] / bv, 4) if bv else "", "churn_ratio": round(d["churn"] / bv, 4) if bv else "",
                     "alt_yoy": round(d["alt12"] / d["altprev"] - 1, 2) if d["altprev"] >= 120 else "",
                     "top_alt_brand": top[0] if top[1] else "", "top_alt_share": round(top[1] / d["alt"], 2) if d["alt"] else "",
                     "homonyms": "; ".join(d["homonyms"]), "suspects": "; ".join(d["suspects"])})
    for seg in (True, False):
        vals = {r["niche_id"]: r["alt_ratio"] for r in rows if r["alt_ratio"] != "" and (r["side"] in B2B) == seg}
        pct = percentiles(vals)
        for r in rows:
            if r["niche_id"] in pct:
                r["alt_ratio_pct"] = pct[r["niche_id"]]
    for r in rows:
        r.setdefault("alt_ratio_pct", "")
    return rows


def run(ws: Workspace, args: argparse.Namespace) -> None:
    pools = args.pools or [p for p in ws.markets if p in POOLS]
    side = {n["id"]: n.get("side", "") for n in niches.load_niches(ws)}
    plan, expected = {}, 0.0
    for pool in pools:
        cfg = POOLS[pool]
        ph = phrases(ws, cfg["lang"])
        bs = batches([x["phrase"] for x in ph])
        paid = sum(1 for b in bs if not dfs.search_volume_cached(ws, b, cfg["location_code"], cfg["language_code"], date_from(ws)))
        expected += paid * dfs.COST_PER_CALL
        plan[pool] = (ph, bs)
        print(f"[{pool}] {len(ph)} phrases from brand queries -> {len(bs)} call(s), {paid} not cached")
    print(f"expected cost: about ${expected:.2f}")
    if args.dry:
        return
    if expected > 0:
        bal = dfs.balance()
        print("balance before:", bal)
        if bal < expected * 1.5:
            raise SystemExit(f"DataForSEO balance ${bal:.2f} is below the expected ${expected:.2f} (x1.5 margin): "
                             "top up at https://app.dataforseo.com/ and re-run; cached batches stay free")
    kw_out, niche_out, spent = [], [], 0.0
    for pool, (ph, bs) in plan.items():
        cfg = POOLS[pool]
        data = {}
        for b in bs:
            live = not dfs.search_volume_cached(ws, b, cfg["location_code"], cfg["language_code"], date_from(ws))
            d, cost = dfs.search_volume(ws, b, cfg["location_code"], cfg["language_code"], date_from(ws))
            data.update(d)
            spent += (cost or 0) if live else 0      # a cached batch keeps the cost it had when it was paid
        rows = []
        for x in ph:
            it = data.get(x["phrase"]) or {}
            monthly = [(f"{m['year']}-{int(m['month']):02d}", m.get("search_volume") or 0) for m in (it.get("monthly_searches") or [])]
            l12, p12 = last12_vs_prev12(monthly)
            rows.append({**x, "pool": pool, "volume": it.get("search_volume") or 0, "last12": l12, "prev12": p12,
                         "monthly_json": json.dumps(sorted(monthly))})
        kw_out += rows
        excl = {str(b).lower() for b in ((ws.load_config("switch_intent.yaml", {}) or {}).get("homonyms") or {})}
        niche_out += summarize(rows, brand_volumes(ws, pool, cfg["lang"]), side, pool, excl)
    with open(ws.out("switch_intent_kw.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["pool", "niche_id", "brand", "kind", "phrase", "volume", "last12", "prev12", "monthly_json"])
        w.writeheader()
        w.writerows(kw_out)
    cols = ["niche_id", "pool", "side", "brand_volume", "alt_volume", "churn_volume", "alt_ratio", "churn_ratio",
            "alt_ratio_pct", "alt_yoy", "top_alt_brand", "top_alt_share", "homonyms", "suspects"]
    with open(ws.out("switch_intent.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(niche_out)
    for r in sorted(niche_out, key=lambda r: -(r["alt_volume"] or 0))[:25]:
        print(f"  [{r['pool']}] {r['niche_id']:36} alt {r['alt_volume']:>7,} churn {r['churn_volume']:>7,} "
              f"ratio {r['alt_ratio']!s:>7} pct {r['alt_ratio_pct']!s:>4} top {r['top_alt_brand']}")
    print(f"-> switch_intent.csv {len(niche_out)} rows, switch_intent_kw.csv {len(kw_out)} phrases"
          + (f"; spent ${spent:.2f}; balance after: {dfs.balance()} ({dt.datetime.now():%H:%M})" if expected > 0 else ""))
