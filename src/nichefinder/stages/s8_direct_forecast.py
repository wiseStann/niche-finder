"""Yandex Direct budget forecast per niche: the price of a click on the search engine Russians use (evidence only).

The Russian branch (s6_ru) scores Wordstat demand and App Store RU concentration and has no click price; the Russian
pool's CPC in S3 (gru_cpc_med) comes from Google Keyword Planner, a weak proxy for Yandex. This stage asks Direct itself.
It never changes a score, a gate or a verdict: passports and reports/S6-ru.md show it beside the Google figure.

Niches: shortlisted niches (with the shortlist tier `ru`) with geo both or ru. Phrases: the niche's Russian queries of the intents in
`direct_forecast.yaml: intents` (category and problem by default; brand clicks price a competitor, not the niche), at most
7 words and without characters Direct rejects. A niche's phrases always go into one report (up to 100 phrases), because
Direct may give the forecast of overlapping phrases to either of them: within one report the niche's shows and clicks
are not counted twice. Region: `geo` (225 = Russia), currency RUB.
Per niche (monthly forecast for the phrases, broad match as in Wordstat):
  shows, clicks (guarantee block), premium_clicks
  cpc_guarantee  = sum(Clicks x Min) / sum(Clicks): average price of a click in the guarantee block
  cpc_premium    = sum(PremiumClicks x PremiumMin) / sum(PremiumClicks): average price of a click in the premium block
  budget_premium = sum(PremiumClicks x PremiumMin): a month of premium clicks on these phrases, in RUB
  anchor_cpc_premium: PremiumMin of the anchor query
Output: data/out/direct_forecast.csv (per phrase), data/out/direct_niche.csv (per niche).
Key: YANDEX_DIRECT_TOKEN of an app with approved API access (sources/direct.py); until approval the stage is skipped.
Cost: free (forecasts spend no API points); one report takes up to a minute; cached per run month.
Usage: nf run s8_direct_forecast -- [--niches a,b]
"""
from __future__ import annotations

import argparse
import csv
import re

from nichefinder import niches
from nichefinder.sources import direct
from nichefinder.workspace import Workspace

SUMMARY = "Yandex Direct budget forecast per niche: click prices and clicks for its Russian queries (evidence)"
KEYS: tuple[str, ...] = ("YANDEX_DIRECT_TOKEN",)
NEEDS: tuple[str, ...] = ()

CONFIG = "direct_forecast.yaml"
GEO = ("both", "ru")
DEFAULTS = {"intents": ["category", "problem"], "geo": [225], "currency": "RUB", "max_words": 7, "poll_s": 10, "max_wait_s": 600}
PHRASE_OK = re.compile(r"^[\w\s\-!+\"]+$")   # letters, digits, spaces and Direct's own operators
PHRASE_COLS = ["niche_id", "phrase", "intent", "anchor", "shows", "clicks", "first_place_clicks", "premium_clicks", "ctr", "premium_ctr",
               "min", "max", "premium_min", "premium_max", "currency"]
NICHE_COLS = ["niche_id", "phrases", "shows", "clicks", "premium_clicks", "cpc_guarantee", "cpc_premium", "budget_premium",
              "anchor_phrase", "anchor_cpc_premium", "currency", "status"]


def settings(ws: Workspace) -> dict:
    return {**DEFAULTS, **(ws.load_config(CONFIG, {}) or {})}


def target_niches(ws: Workspace, only: str = "") -> list[str]:
    geo = {n["id"]: n.get("geo", "global") for n in niches.load_niches(ws)}
    ids = [i for i in niches.shortlist_ids(ws, ru=True) if geo.get(i) in GEO]
    wanted = {x.strip() for x in only.split(",") if x.strip()}
    return [i for i in ids if i in wanted] if wanted else ids


def niche_phrases(rows: list[dict], intents: list[str], max_words: int) -> list[dict]:
    """The niche's usable Russian queries of the given intents, anchor first, without repeats."""
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: -int(r["anchor"])):
        q = " ".join(str(r["q"]).split())
        if r["intent"] not in intents or q.lower() in seen or len(q.split()) > max_words or not PHRASE_OK.match(q):
            continue
        seen.add(q.lower())
        out.append({"q": q, "intent": r["intent"], "anchor": int(r["anchor"])})
    return out


def batches(plan: list[tuple[str, list[dict]]], size: int = 100) -> list[list[tuple[str, list[dict]]]]:
    """Whole niches packed into reports of at most `size` phrases, in order (a niche over `size` is cut to it)."""
    out: list[list[tuple[str, list[dict]]]] = []
    cur: list[tuple[str, list[dict]]] = []
    n = 0
    for nid, ph in plan:
        ph = ph[:size]
        if cur and n + len(ph) > size:
            out.append(cur)
            cur, n = [], 0
        cur.append((nid, ph))
        n += len(ph)
    if cur:
        out.append(cur)
    return out


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def niche_row(nid: str, rows: list[dict], currency: str) -> dict:
    clicks = sum(_f(r["clicks"]) for r in rows)
    prem = sum(_f(r["premium_clicks"]) for r in rows)
    anchor = next((r for r in rows if r["anchor"]), None)
    return {"niche_id": nid, "phrases": len(rows), "shows": int(sum(_f(r["shows"]) for r in rows)), "clicks": int(clicks),
            "premium_clicks": int(prem),
            "cpc_guarantee": round(sum(_f(r["clicks"]) * _f(r["min"]) for r in rows) / clicks, 2) if clicks else "",
            "cpc_premium": round(sum(_f(r["premium_clicks"]) * _f(r["premium_min"]) for r in rows) / prem, 2) if prem else "",
            "budget_premium": round(sum(_f(r["premium_clicks"]) * _f(r["premium_min"]) for r in rows)),
            "anchor_phrase": anchor["phrase"] if anchor else "", "anchor_cpc_premium": anchor["premium_min"] if anchor else "",
            "currency": currency, "status": "ok" if rows else "no data"}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: the shortlisted niches with geo both or ru)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = settings(ws)
    only = getattr(args, "niches", "") or ""
    ids = target_niches(ws, only)
    if not ids:
        print("  no shortlisted niches with geo both or ru")
        return
    rows = niches.keyword_rows(ws, "ru")
    plan, skipped = [], []
    for nid in ids:
        ph = niche_phrases([r for r in rows if r["niche_id"] == nid], list(cfg["intents"]), int(cfg["max_words"]))
        (plan if ph else skipped).append((nid, ph))
    groups = batches(plan)
    print(f"  {len(plan)} niches, {sum(len(p) for _, p in plan)} phrases in {len(groups)} forecast reports; region {cfg['geo']}, {cfg['currency']}"
          + (f"; no usable phrases: {', '.join(n for n, _ in skipped)}" if skipped else ""))
    phrase_out, niche_out = [], []
    for k, group in enumerate(groups, 1):
        phrases = [p["q"] for _, ph in group for p in ph]
        res = direct.forecast(ws, phrases, [int(g) for g in cfg["geo"]], str(cfg["currency"]), float(cfg["poll_s"]), float(cfg["max_wait_s"]))
        got = {str(r.get("Phrase", "")).strip().lower(): r for r in res["phrases"]}
        for nid, ph in group:
            nrows = []
            for p in ph:
                r = got.get(p["q"].lower())
                if not r:
                    continue
                nrows.append({"niche_id": nid, "phrase": p["q"], "intent": p["intent"], "anchor": p["anchor"], "shows": r.get("Shows", 0),
                              "clicks": r.get("Clicks", 0), "first_place_clicks": r.get("FirstPlaceClicks", 0),
                              "premium_clicks": r.get("PremiumClicks", 0), "ctr": r.get("CTR", ""), "premium_ctr": r.get("PremiumCTR", ""),
                              "min": r.get("Min", ""), "max": r.get("Max", ""), "premium_min": r.get("PremiumMin", ""),
                              "premium_max": r.get("PremiumMax", ""), "currency": r.get("Currency") or cfg["currency"]})
            phrase_out += nrows
            nr = niche_row(nid, nrows, str(cfg["currency"]))
            niche_out.append(nr)
            print(f"  {nid:36} phrases {nr['phrases']:>2} shows {nr['shows']:>9,} premium clicks {nr['premium_clicks']:>6,} "
                  f"cpc guarantee {nr['cpc_guarantee'] or '-':>6} premium {nr['cpc_premium'] or '-':>6} {cfg['currency']}", flush=True)
        print(f"  report {k}/{len(groups)}: {len(phrases)} phrases")
    niche_out += [{"niche_id": nid, "phrases": 0, "status": "no phrases"} for nid, _ in skipped]
    for name, out, cols in (("direct_forecast.csv", phrase_out, PHRASE_COLS), ("direct_niche.csv", niche_out, NICHE_COLS)):
        prev = []
        if only and ws.out(name).is_file():   # a run with --niches keeps the other niches' rows
            prev = [r for r in csv.DictReader(open(ws.out(name), encoding="utf-8")) if r["niche_id"] not in set(ids)]
        with open(ws.out(name), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(prev + out)
    print(f"-> direct_niche.csv: {len(niche_out)} niches; direct_forecast.csv: {len(phrase_out)} phrases")
