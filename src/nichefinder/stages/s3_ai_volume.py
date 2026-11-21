"""Experiment: does an "AI search volume" index rank niches differently from Google Ads volume?

Pulls DataForSEO AI Keyword Data (`ai_search_volume`, United States, English) for every English query of the US
pool and compares it with the Google Ads volume that s3_dataforseo already pulled (data/out/dfs_us.csv):
  - keywords: Spearman rank correlation of the two volumes, overall and per intent; median AI/Google ratio;
  - niches: category demand as in s3_metrics (sum over category queries, percentile of log10(x + 1) over all niches)
    from each source; Spearman across niches, the percentile shift of each niche, and that shift in S3 `demand_vol`
    points (weight from config/score.yaml);
  - months: total AI volume over total Google volume, month by month, over the months both series cover.

Caveat: DataForSEO models the index from Google People Also Ask data, not from chatbot logs. It is a second reading
of Google, not an independent source, so it never counts toward triangulation and never feeds the score.

Decision rule, fixed before the first run: the index adds nothing for screening when the niche-level Spearman on
category demand is at least SAME_RHO and at most SAME_MOVERS of the niches shift by MOVER_SHIFT percentile or more.
Otherwise the report lists the niches that move, to be read by hand.

Manual stage (not in `nf run all`): it costs money. Price COST_PER_AI_KEYWORD per keyword (about $0.17 for 1,700
keywords); batches of up to 1000 are cached by content, so a re-run is free. --dry prints the cost and stops.
Output: data/out/ai_volume_us.csv (per keyword), data/out/ai_volume_niches.csv, reports/S3-ai-volume.md.
Keys: DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import statistics
from collections import defaultdict

from nichefinder import niches as nf_niches
from nichefinder.sources import dataforseo as dfs
from nichefinder.workspace import Workspace

SUMMARY = "Experiment: DataForSEO AI search volume vs Google Ads volume (US), manual, never scored"
KEYS: tuple[str, ...] = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")

LOCATION, LANGUAGE = 2840, "en"
SAME_RHO = 0.8        # niche-level Spearman at or above this: the same ranking for screening
MOVER_SHIFT = 0.25    # a niche "moves" when its demand percentile shifts by this much or more
SAME_MOVERS = 0.10    # ... and at most this share of niches may move
INTENTS = ("category", "problem", "brand", "info")
COLLISION_RATIO = 10      # AI >= 10 x Google: suspected word-form collision
NO_QUESTION_MIN = 10_000  # Google volume from which a near-zero AI volume is reported
NO_QUESTION_RATIO = 0.01  # ... "near zero" = below 1 % of the Google volume


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry", action="store_true", help="print the keyword count and the expected cost, make no calls")


# ── statistics ─────────────────────────────────────────────────────────

def ranks(xs: list[float]) -> list[float]:
    """1-based ranks, ties get their average rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return round(cov / (vx * vy), 3) if vx and vy else None


def pct_rank(values: list[float], v: float) -> float:
    """As in s3_metrics: share of values at or below v."""
    return sum(1 for x in values if x <= v) / len(values) if values else 0.0


# ── data ───────────────────────────────────────────────────────────────

def keywords(ws: Workspace) -> tuple[list[str], dict[str, dict]]:
    """Unique English queries (lowercase, file order) and per keyword: niche ids and intents."""
    meta: dict[str, dict] = {}
    for r in nf_niches.keyword_rows(ws, "en"):
        q = r["q"].strip().lower()
        m = meta.setdefault(q, {"niches": [], "intents": []})
        if r["niche_id"] not in m["niches"]:
            m["niches"].append(r["niche_id"])
        if r["intent"] not in m["intents"]:
            m["intents"].append(r["intent"])
    return list(meta), meta


def load_google(ws: Workspace) -> dict[str, dict]:
    path = ws.out("dfs_us.csv")
    if not path.exists():
        raise SystemExit(f"{path} not found: run `nf run s3_dataforseo` first (the US pool)")
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        out[r["keyword"]] = {"vol": int(float(r["search_volume"])) if r["search_volume"] else 0,
                             "monthly": dict(json.loads(r["monthly_json"] or "[]"))}
    return out


def pull(ws: Workspace, kws: list[str]) -> tuple[dict[str, dict], float]:
    data, cost = {}, 0.0
    for i in range(0, len(kws), dfs.BATCH):
        part, c = dfs.ai_search_volume(ws, kws[i:i + dfs.BATCH], LOCATION, LANGUAGE)
        data.update(part)
        cost += c or 0
    return data, cost


def ai_item(it: dict | None) -> tuple[int, dict[str, int]]:
    if not it:
        return 0, {}
    monthly = {f"{m['year']}-{int(m['month']):02d}": int(m.get("ai_search_volume") or 0)
               for m in (it.get("ai_monthly_searches") or []) if m.get("year") and m.get("month")}
    return int(it.get("ai_search_volume") or 0), monthly


# ── analysis ───────────────────────────────────────────────────────────

def keyword_table(kws: list[str], meta: dict, google: dict, ai: dict) -> list[dict]:
    rows = []
    for k in kws:
        g = google.get(k, {"vol": 0, "monthly": {}})
        a, am = ai_item(ai.get(k))
        rows.append({"keyword": k, "niches": "|".join(meta[k]["niches"]), "intents": "|".join(meta[k]["intents"]),
                     "google_volume": g["vol"], "ai_search_volume": a,
                     "ratio": round(a / g["vol"], 3) if g["vol"] else "", "ai_monthly_json": json.dumps(sorted(am.items())),
                     "_g_monthly": g["monthly"], "_a_monthly": am})
    return rows


def keyword_stats(rows: list[dict]) -> list[dict]:
    """Per intent and overall: n, Spearman, median ratio over keywords with Google volume, share with AI volume 0."""
    out = []
    for intent in ("all",) + INTENTS:
        sel = [r for r in rows if intent == "all" or intent in r["intents"].split("|")]
        if not sel:
            continue
        with_g = [r for r in sel if r["google_volume"] > 0]
        ratios = [r["ai_search_volume"] / r["google_volume"] for r in with_g]
        out.append({"intent": intent, "n": len(sel),
                    "rho": spearman([r["google_volume"] for r in sel], [r["ai_search_volume"] for r in sel]),
                    "median_ratio": round(statistics.median(ratios), 3) if ratios else None,
                    "ai_zero_share": round(sum(1 for r in with_g if r["ai_search_volume"] == 0) / len(with_g), 3) if with_g else None})
    return out


def niche_table(ws: Workspace, google: dict, ai: dict, drop: set[str] = frozenset()) -> list[dict]:
    """Category and problem demand per niche from both sources; `drop` leaves keywords out of both sums."""
    niches, queries = nf_niches.load(ws)
    rows = []
    for n in niches:
        items = (queries.get(n["id"]) or {}).get("en") or []
        if not items:
            continue
        r = {"niche_id": n["id"], "side": n.get("side", "")}
        for intent in ("category", "problem"):
            qs = [q for q in (it["q"].strip().lower() for it in items if it["i"] == intent) if q not in drop]
            r[f"google_{intent}"] = sum(google.get(q, {"vol": 0})["vol"] for q in qs)
            r[f"ai_{intent}"] = sum(ai_item(ai.get(q))[0] for q in qs)
        rows.append(r)
    for src in ("google", "ai"):
        logs = [math.log10(r[f"{src}_category"] + 1) for r in rows]
        for r, lv in zip(rows, logs):
            r[f"{src}_pct"] = round(pct_rank(logs, lv), 3)
    for r in rows:
        r["shift"] = round(r["ai_pct"] - r["google_pct"], 3)
        r["ai_ratio"] = round(r["ai_category"] / r["google_category"], 3) if r["google_category"] else ""
    return rows


def artifacts(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Two kinds of keywords where the index measures its own construction rather than demand:
    collisions: AI volume >= COLLISION_RATIO x Google volume (word forms collapse, so a brand like "whering" can
      inherit every question with "where");
    no_question: Google volume >= NO_QUESTION_MIN with AI volume below NO_QUESTION_RATIO of it (navigational or tool
      queries that nobody phrases as a question, so People Also Ask never sees them)."""
    coll = [r for r in rows if r["google_volume"] > 0 and r["ai_search_volume"] >= COLLISION_RATIO * r["google_volume"]]
    noq = [r for r in rows if r["google_volume"] >= NO_QUESTION_MIN
           and r["ai_search_volume"] < NO_QUESTION_RATIO * r["google_volume"]]
    return (sorted(coll, key=lambda r: -r["ai_search_volume"]), sorted(noq, key=lambda r: -r["google_volume"]))


def monthly_ratio(rows: list[dict]) -> list[tuple[str, int, int]]:
    """Totals over category and problem queries, without collisions (a single collision can outweigh the rest)."""
    coll = {r["keyword"] for r in artifacts(rows)[0]}
    g, a = defaultdict(int), defaultdict(int)
    for r in rows:
        if r["keyword"] in coll or not ({"category", "problem"} & set(r["intents"].split("|"))):
            continue
        for m, v in r["_g_monthly"].items():
            g[m] += v
        for m, v in r["_a_monthly"].items():
            a[m] += v
    return [(m, g[m], a[m]) for m in sorted(set(g) & set(a))]


def decide(niche_rows: list[dict]) -> tuple[float | None, float, bool]:
    rho = spearman([r["google_category"] for r in niche_rows], [r["ai_category"] for r in niche_rows])
    movers = sum(1 for r in niche_rows if abs(r["shift"]) >= MOVER_SHIFT) / max(1, len(niche_rows))
    return rho, round(movers, 3), rho is not None and rho >= SAME_RHO and movers <= SAME_MOVERS


def report(ws: Workspace, kstats: list[dict], krows: list[dict], nrows: list[dict], clean: list[dict], w_demand: float,
           cost: float) -> str:
    rho, movers, same = decide(nrows)
    c_rho, c_movers, _ = decide(clean)
    months = monthly_ratio(krows)
    shortlist = set(nf_niches.shortlist_ids(ws)) if ws.config("shortlist.yaml").is_file() else set()
    lines = ["# S3 experiment: AI search volume vs Google Ads volume (US)", "",
             f"Run {ws.today}. Source: DataForSEO AI Keyword Data, location {LOCATION}, language `{LANGUAGE}`; "
             f"{sum(k['n'] for k in kstats[:1])} keywords, {len(nrows)} niches. Cost of this run: ${cost:.2f}.", "",
             "> The AI index is modeled by DataForSEO from Google People Also Ask data, not from chatbot logs. It is a "
             "second reading of Google, so it never counts as an independent source and never feeds the score.", "",
             "## Verdict", "",
             f"Rule (fixed before the first run): the index adds nothing for screening when niche-level Spearman >= {SAME_RHO} "
             f"and at most {SAME_MOVERS:.0%} of niches shift by {MOVER_SHIFT:.0%} or more in demand percentile.", "",
             f"- niche-level Spearman on category demand: **{rho}**",
             f"- niches that shift by {MOVER_SHIFT:.0%} or more: **{movers:.0%}**",
             f"- **{'Adds nothing: the AI index ranks niches like Google.' if same else 'Diverges: read the movers below before drawing a conclusion.'}**",
             f"- diagnostic, not part of the rule: without the collision and no-question keywords listed below, "
             f"niche-level Spearman {c_rho}, movers {c_movers:.0%}",
             "", "## Keywords", "",
             "| intent | keywords | Spearman | median AI / Google | AI volume 0 while Google > 0 |", "|---|---|---|---|---|"]
    for k in kstats:
        lines.append(f"| {k['intent']} | {k['n']} | {k['rho']} | {k['median_ratio']} | "
                     f"{'-' if k['ai_zero_share'] is None else format(k['ai_zero_share'], '.0%')} |")
    movers_rows = sorted(nrows, key=lambda r: -abs(r["shift"]))[:25]
    lines += ["", "## Niches with the largest shift", "",
              f"Shift = AI percentile - Google percentile of category demand; points = shift x `demand_vol` ({w_demand:g}).", "",
              "| niche | shortlist | Google cat | AI cat | AI / Google | Google pct | AI pct | shift | points |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in movers_rows:
        lines.append(f"| {r['niche_id']} | {'yes' if r['niche_id'] in shortlist else ''} | {r['google_category']} | "
                     f"{r['ai_category']} | {r['ai_ratio']} | {r['google_pct']:.2f} | {r['ai_pct']:.2f} | "
                     f"{r['shift']:+.2f} | {r['shift'] * w_demand:+.1f} |")
    coll, noq = artifacts(krows)
    if coll or noq:
        lines += ["", "## Where the index measures its own construction", "",
                  f"Suspected collisions: AI volume at least {COLLISION_RATIO}x the Google volume (word forms collapse, "
                  "so a short brand can inherit unrelated questions; a few may be real, such as photo identification "
                  f"asked of a chatbot). No question: Google volume of {NO_QUESTION_MIN:,} "
                  f"or more with AI volume below {NO_QUESTION_RATIO:.0%} of it (navigational or tool queries that "
                  "nobody phrases as a question). A niche whose shift comes from such keywords moves for a reason "
                  "unrelated to chatbots.", "",
                  f"{len(coll)} collisions, {len(noq)} no-question keywords.", "",
                  "| kind | keyword | intents | niches | Google | AI |", "|---|---|---|---|---|---|"]
        lines += [f"| {kind} | {r['keyword']} | {r['intents']} | {r['niches']} | {r['google_volume']} | {r['ai_search_volume']} |"
                  for kind, sel in (("collision", coll[:15]), ("no question", noq[:15])) for r in sel]
    if months:
        lines += ["", "## Month by month (category and problem queries, collisions excluded)", "",
                  "| month | Google | AI | AI / Google |", "|---|---|---|---|"]
        lines += [f"| {m} | {g} | {a} | {a / g:.3f} |" if g else f"| {m} | {g} | {a} | - |" for m, g, a in months]
    return "\n".join(lines) + "\n"


def run(ws: Workspace, args: argparse.Namespace) -> None:
    google = load_google(ws)
    kws, meta = keywords(ws)
    batches = [kws[i:i + dfs.BATCH] for i in range(0, len(kws), dfs.BATCH)]
    unpaid = [b for b in batches if not dfs.ai_search_volume_cached(ws, b, LOCATION, LANGUAGE)]
    expected = sum(len(b) for b in unpaid) * dfs.COST_PER_AI_KEYWORD
    print(f"keywords: {len(kws)} in {len(batches)} call(s), {len(unpaid)} not cached; expected cost about ${expected:.2f}")
    if args.dry:
        return
    if expected > 0:
        print("balance before:", dfs.balance())
    ai, cost = pull(ws, kws)
    if expected > 0:
        print(f"spent ${cost:.2f}; balance after: {dfs.balance()}  ({dt.datetime.now():%Y-%m-%d %H:%M})")
    krows = keyword_table(kws, meta, google, ai)
    nrows = niche_table(ws, google, ai)
    with open(ws.out("ai_volume_us.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[c for c in krows[0] if not c.startswith("_")] if krows else ["keyword"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(krows)
    with open(ws.out("ai_volume_niches.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(nrows[0]) if nrows else ["niche_id"])
        w.writeheader()
        w.writerows(nrows)
    w_demand = float((ws.load_config("score.yaml", {}) or {}).get("weights", {}).get("demand_vol", 20))
    kstats = keyword_stats(krows)
    path = ws.report("S3-ai-volume.md")
    coll, noq = artifacts(krows)
    clean = niche_table(ws, google, ai, drop={r["keyword"] for r in coll + noq})
    path.write_text(report(ws, kstats, krows, nrows, clean, w_demand, cost), encoding="utf-8")
    rho, movers, same = decide(nrows)
    print(f"keyword Spearman {kstats[0]['rho'] if kstats else '-'}; niche Spearman {rho}; movers {movers:.0%} -> "
          f"{'adds nothing' if same else 'diverges, read the report'}")
    print("->", ws.out("ai_volume_us.csv"), ws.out("ai_volume_niches.csv"), path)
