"""S0: Kickstarter projects from the monthly Web Robots dumps (webrobots.io/kickstarter-datasets).

Web Robots crawls Kickstarter once a month and publishes every project it sees as line-delimited JSON (gzip, ~120 MB).
The stage picks the latest dump dated on or before ws.today (or --dump YYYY-MM-DD), downloads it once into
data/cache/kickstarter/, streams it and keeps the projects launched within the last 24 months (deduplicated by id).

Outputs:
  data/raw/kickstarter_projects.csv    id, name, blurb, category, subcategory, state, goal_usd, pledged_usd, backers,
                                       launched, deadline, country, url
  data/out/kickstarter_categories.csv  per subcategory: launches in the last 12 months and the 12 before (and their
                                       ratio), finished and successful projects, success rate, money pledged to
                                       successful projects (sum and median), median backers, the top project
  reports/S0-kickstarter.md            subcategories ranked by money pledged in the last 12 months, and the top projects

Kickstarter is demand paid in advance for physical products, games, books and design. It is empty for SaaS; it helps
with niches that sell a physical or an information product (guides, books and templates sit in Publishing) and with
the "accessory -> companion app" pattern. A dump is what the crawler saw, not the full history: the earlier window is
less complete, so read the launch ratio as a rough direction. The crawler also under-samples failed projects (in the
2026-11 dump ~79% of finished projects are successful, against Kickstarter's published all-time rate of about 40%), so
success rates are inflated: compare categories with each other, not with Kickstarter's own statistics. Pledged sums of
successful projects are the most reliable column. Success rate counts projects whose deadline has passed:
successful / (successful + failed); cancelled and suspended projects are left out. s0_merge takes successful projects
with >= 200 backers into the universe; s5_deals matches the projects of the last 12 months to niches.
No keys; one ~120 MB download per dump, kept in the cache.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from nichefinder import http
from nichefinder.workspace import Workspace

SUMMARY = "Kickstarter projects and per-category stats from the monthly Web Robots dump (~120 MB download)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

INDEX = "https://webrobots.io/kickstarter-datasets/"
DUMP = re.compile(r"""href=["']?(https://[^\s"'>]+/Kickstarter_(\d{4}-\d{2}-\d{2})T[^\s"'>]+\.json\.gz)""")
FIELDS = ["id", "name", "blurb", "category", "subcategory", "state", "goal_usd", "pledged_usd", "backers", "launched",
          "deadline", "country", "url"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dump", default="", help="dump date YYYY-MM-DD (default: the latest on or before the run date)")


def dumps(page: str) -> dict[str, str]:
    """Dump date -> JSON dump URL, from the Web Robots index page."""
    return {date: url for url, date in DUMP.findall(page)}


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _date(ts) -> str:
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date().isoformat() if ts else ""


def project(p: dict) -> dict | None:
    """One dump record (the `data` object) -> a flat row; None when it lacks an id or a launch date."""
    if not p.get("id") or not p.get("launched_at"):
        return None
    cat = p.get("category") or {}
    sub = cat.get("name") or ""
    rate = _f(p.get("static_usd_rate")) or _f(p.get("usd_exchange_rate")) or 1.0
    return {
        "id": p["id"], "name": re.sub(r"\s+", " ", p.get("name") or "").strip(), "blurb": re.sub(r"\s+", " ", p.get("blurb") or "").strip(),
        "category": cat.get("parent_name") or sub, "subcategory": sub, "state": p.get("state") or "",
        "goal_usd": round(_f(p.get("goal")) * rate), "pledged_usd": round(_f(p.get("usd_pledged"))),
        "backers": int(_f(p.get("backers_count"))), "launched": _date(p.get("launched_at")), "deadline": _date(p.get("deadline")),
        "country": p.get("country") or "", "url": ((p.get("urls") or {}).get("web") or {}).get("project", ""),
    }


def read_dump(path: Path, since: str, until: str) -> tuple[list[dict], int, int]:
    """Projects launched in [since, until] from a line-delimited JSON dump; returns (rows, lines read, bad lines)."""
    rows: dict[int, dict] = {}
    lines = bad = 0
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            lines += 1
            try:
                o = json.loads(line)
            except ValueError:
                bad += 1
                continue
            r = project(o.get("data", o) if isinstance(o, dict) else {})
            if r and since <= r["launched"] <= until:
                rows.setdefault(r["id"], r)
    return list(rows.values()), lines, bad


def category_stats(rows: list[dict], today: dt.date) -> list[dict]:
    """Per (category, subcategory): launches in the last 12 months vs the 12 before, outcomes of finished projects."""
    y1, y2, now = (today - dt.timedelta(days=365)).isoformat(), (today - dt.timedelta(days=730)).isoformat(), today.isoformat()
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["category"], r["subcategory"])].append(r)
    out = []
    for (cat, sub), items in groups.items():
        last = [r for r in items if y1 < r["launched"] <= now]
        prev = [r for r in items if y2 < r["launched"] <= y1]
        done = [r for r in last if r["deadline"] and r["deadline"] < now and r["state"] in ("successful", "failed")]
        ok = [r for r in done if r["state"] == "successful"]
        top = max(ok, key=lambda r: r["pledged_usd"], default=None)
        out.append({
            "category": cat, "subcategory": sub, "launched_12m": len(last), "launched_prev12m": len(prev),
            "launch_ratio": round(len(last) / len(prev), 2) if prev else "",
            "finished_12m": len(done), "successful_12m": len(ok), "success_rate_12m": round(len(ok) / len(done), 2) if done else "",
            "pledged_usd_12m": sum(r["pledged_usd"] for r in ok),
            "median_pledged_success": round(statistics.median(r["pledged_usd"] for r in ok)) if ok else "",
            "median_backers_success": round(statistics.median(r["backers"] for r in ok)) if ok else "",
            "top_project": top["name"][:80] if top else "", "top_pledged_usd": top["pledged_usd"] if top else "",
        })
    return sorted(out, key=lambda r: -r["pledged_usd_12m"])


def report(ws: Workspace, stats: list[dict], rows: list[dict], dump_date: str) -> Path:
    y1 = (ws.today - dt.timedelta(days=365)).isoformat()
    ok = sum(1 for r in rows if r["state"] == "successful")
    done = ok + sum(1 for r in rows if r["state"] == "failed")
    L = [f"# S0 Kickstarter: where people pay in advance ({ws.today.isoformat()})", "",
         f"Source: Web Robots dump of {dump_date}; projects launched within 24 months: {len(rows)}. "
         "Last 12 months vs the 12 before; success rate = successful / (successful + failed) among projects whose deadline has passed. "
         "The dump is what the crawler saw, so the earlier window is less complete: read the launch ratio as a direction, not a growth rate. "
         f"The crawler also under-samples failed projects: here {ok / done if done else 0:.0%} of finished projects are successful, against "
         "Kickstarter's published all-time rate of about 40%. Compare success rates between categories, not with Kickstarter's own statistics; "
         "money pledged to successful projects is the most reliable column.", "",
         "## Subcategories by money pledged to successful projects, last 12 months", "",
         "| Category / subcategory | Launched 12m | Launched prior 12m | Ratio | Success rate | Pledged (successful) | Median pledged | Median backers | Top project |",
         "|---|---|---|---|---|---|---|---|---|"]
    for s in stats:
        if not s["launched_12m"]:
            continue
        rate = f"{s['success_rate_12m']:.0%}" if s["success_rate_12m"] != "" else "—"
        L.append(f"| {s['category']} / {s['subcategory']} | {s['launched_12m']} | {s['launched_prev12m']} | {s['launch_ratio'] or '—'} | {rate} | "
                 f"${s['pledged_usd_12m']:,} | {('$' + format(s['median_pledged_success'], ',')) if s['median_pledged_success'] != '' else '—'} | "
                 f"{s['median_backers_success'] or '—'} | {s['top_project']} |")
    top = sorted((r for r in rows if r["state"] == "successful" and r["launched"] > y1), key=lambda r: -r["pledged_usd"])[:50]
    L += ["", "## Top 50 successful projects of the last 12 months", "", "| Project | Category | Pledged | Backers | Blurb |", "|---|---|---|---|---|"]
    for r in top:
        L.append(f"| [{r['name'][:60]}]({r['url']}) | {r['category']} / {r['subcategory']} | ${r['pledged_usd']:,} | {r['backers']:,} | {r['blurb'][:110]} |")
    path = ws.report("S0-kickstarter.md")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


def run(ws: Workspace, args: argparse.Namespace) -> None:
    page = http.get_text(INDEX, cache=ws.cache("kickstarter"), cache_key=f"index_{ws.today:%Y-%m}", ext=".html", hashed=False,
                         timeout=60, min_size=5_000)
    found = dumps(page)
    if not found:
        raise SystemExit(f"no dump links found on {INDEX} (the page layout may have changed)")
    if args.dump:
        if args.dump not in found:
            raise SystemExit(f"no dump dated {args.dump}; available: {', '.join(sorted(found)[-12:])}")
        date = args.dump
    else:
        older = [d for d in found if d <= ws.today.isoformat()]
        if not older:
            raise SystemExit(f"no dump dated on or before {ws.today}; the oldest is {min(found)}")
        date = max(older)
    url = found[date]
    path = ws.cache("kickstarter") / url.rsplit("/", 1)[-1]
    print(f"dump {date}: {url}" + (" (cached)" if path.is_file() else " - downloading"))
    http.download(url, path, timeout=300)
    since = (ws.today - dt.timedelta(days=730)).isoformat()
    rows, lines, bad = read_dump(path, since, ws.today.isoformat())
    print(f"records read: {lines:,} ({bad} unreadable); projects launched since {since}: {len(rows):,}")
    if not rows:
        raise SystemExit("no projects in the window - check the dump date and --dump")
    rows.sort(key=lambda r: r["launched"], reverse=True)
    out = ws.raw("kickstarter_projects.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    stats = category_stats(rows, ws.today)
    with open(ws.out("kickstarter_categories.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(stats[0].keys()))
        w.writeheader()
        w.writerows(stats)
    rpath = report(ws, stats, rows, date)
    for s in stats[:15]:
        print(f"  ${s['pledged_usd_12m']:>13,}  {s['category']} / {s['subcategory']}: {s['launched_12m']} launched, "
              f"success {s['success_rate_12m'] if s['success_rate_12m'] != '' else '-'}")
    print(f"-> {out}, {ws.out('kickstarter_categories.csv')}, {rpath}")
