"""Google Trends depth check on the shortlist anchors (trendspy): a growth signal independent of Keyword Planner.

Years after `last_year` (config/trends.yaml, default 2021-2024) are not used: recent history is contaminated by
bot and AI-agent traffic. One request = one phrase, so the series keeps its own shape (no relative scaling).
Per niche it fetches the English anchor (geo US), the Russian anchor (geo RU, for geo both/ru niches), optional broad
English anchors from config/trends_extra.yaml (kind=extra) and brand anchors from config/trends_brands.yaml (kind=brand).
Niches: the union of the tiers in config/shortlist.yaml.
Cache: data/cache/trends/<geo>__<phrase>.json. Output: data/out/trends_deep.csv (yearly means, year-over-year changes,
slope between last_year and last_year - 2, low_signal flag, verdict UP / DOWN / FLAT / NA).
Needs the trendspy package; live requests are slow (a pause after each) and Google may rate-limit.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time

from nichefinder import niches as nf_niches
from nichefinder.workspace import Workspace

SUMMARY = "Google Trends yearly means and verdict for shortlist anchors, extra broad anchors and brands"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("trendspy",)


def fetch(tr, cache, timeframe, pause, word, geo):
    path = cache / f"{geo}__{word.replace(' ', '_')}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(4):
        try:
            df = tr.interest_over_time([word], timeframe=timeframe, geo=geo)
            data = {"dates": [str(d)[:10] for d in df.index.tolist()], "v": [int(x) for x in df[word].tolist()]}
            path.write_text(json.dumps(data), encoding="utf-8")
            time.sleep(pause)
            return data
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"  retry {attempt + 1} {word}: {type(e).__name__} {str(e)[:80]}\n")
            time.sleep(45 * (attempt + 1))
    return None


def yearly(data, min_points):
    by = {}
    for d, v in zip(data["dates"], data["v"]):
        by.setdefault(d[:4], []).append(v)
    return {y: sum(v) / len(v) for y, v in by.items() if len(v) >= min_points}


def run(ws: Workspace, args: argparse.Namespace | None = None) -> None:
    from trendspy import Trends

    tcfg = ws.load_config("trends.yaml", {})
    first, last = int(tcfg.get("first_year", 2021)), int(tcfg.get("last_year", 2024))
    ctx = {"years": list(range(first, last + 1)), "last": last, "min_points": int(tcfg.get("min_weeks_per_year", 40)),
           "timeframe": f"{first}-01-01 {last}-12-31", "pause": float(tcfg.get("pause_seconds", 12)),
           "cache": ws.cache("trends")}
    niches = {x["id"]: x for x in nf_niches.load_niches(ws)}
    queries = nf_niches.load_queries(ws)
    ids = nf_niches.shortlist_ids(ws)
    extra = ws.load_config("trends_extra.yaml", {})
    brands = ws.load_config("trends_brands.yaml", {})
    tr = Trends()
    rows = []
    for nid in ids:
        n = niches[nid]
        langs = [("en", "US")] + ([("ru", "RU")] if n.get("geo") in ("both", "ru") else [])
        for lang, geo in langs:
            anchor = next((e["q"] for e in queries[nid].get(lang, []) if e.get("anchor")), None)
            if not anchor:
                continue
            for kind, word in [("anchor", anchor)] + ([("extra", extra[nid])] if lang == "en" and nid in extra else []):
                one(tr, ctx, rows, nid, lang, geo, kind, word)
            # brand anchors check a single "X software" phrase; s5_merge applies the majority rule
            if lang == "en":
                for word in brands.get(nid) or []:
                    one(tr, ctx, rows, nid, lang, geo, "brand", word)
    out = ws.out("trends_deep.csv")
    yoy_cols = [f"yoy_{str(y)[2:]}_{str(y - 1)[2:]}" for y in ctx["years"][1:]]
    r_col = f"r_{str(last)[2:]}_{str(last - 2)[2:]}"
    keys = ["niche_id", "lang", "kind", "anchor", "status", "geo"] + [f"mean_{y}" for y in ctx["years"]] + yoy_cols + [r_col, "low_signal", "verdict"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print("->", out)


def one(tr, ctx, rows, nid, lang, geo, kind, anchor):
    last = ctx["last"]
    sy = lambda k: str(last - k)  # noqa: E731  (year as string, k years before last_year)
    data = fetch(tr, ctx["cache"], ctx["timeframe"], ctx["pause"], anchor, geo)
    if not data:
        rows.append({"niche_id": nid, "lang": lang, "kind": kind, "anchor": anchor, "status": "FAILED"})
        return
    y = yearly(data, ctx["min_points"])
    m = {k: round(v, 1) for k, v in y.items()}
    g = lambda a, b: (round(y[a] / y[b] - 1, 3) if y.get(b) else None)  # noqa: E731
    yoy = {yr: g(str(yr), str(yr - 1)) for yr in ctx["years"][1:]}
    yoy_last = yoy.get(last)
    # verdict over the window: UP if last_year > last_year-2 by >= 15 % and last/prev >= -5 %; DOWN if below by >= 15 % and last/prev <= +5 %
    r42 = (y[sy(0)] / y[sy(2)] - 1) if y.get(sy(2)) and y.get(sy(0)) else None
    mean_last = y.get(sy(0), 0)
    if mean_last < 5:
        verdict = "NA"          # signal too weak in Trends (index < 5)
    elif r42 is None:
        verdict = "UP" if (y.get(sy(2), 0) == 0 and mean_last >= 10) else "NA"   # category born after the base year
    elif r42 >= 0.15 and (yoy_last or 0) >= -0.05:
        verdict = "UP"
    elif r42 <= -0.15 and (yoy_last or 0) <= 0.05:
        verdict = "DOWN"
    else:
        verdict = "FLAT"
    row = {"niche_id": nid, "lang": lang, "kind": kind, "anchor": anchor, "status": "ok", "geo": geo}
    for yr in ctx["years"]:
        row[f"mean_{yr}"] = m.get(str(yr))
    for yr in ctx["years"][1:]:
        row[f"yoy_{str(yr)[2:]}_{str(yr - 1)[2:]}"] = yoy[yr]
    row[f"r_{str(last)[2:]}_{str(last - 2)[2:]}"] = round(r42, 3) if r42 is not None else None
    row["low_signal"] = int(mean_last < 10)
    row["verdict"] = verdict
    rows.append(row)
    means = " ".join(f"{str(yr)[2:]}={m.get(str(yr))}" for yr in ctx["years"])
    print(f"{nid:36} {lang} {kind:6} {anchor[:30]:30} {means} -> {verdict}")
