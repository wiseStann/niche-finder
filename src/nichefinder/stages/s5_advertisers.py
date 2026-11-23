"""Who pays for traffic in a niche: competitors' ads in the Google Ads Transparency Center (through DataForSEO).

The live SERP almost never shows paid blocks to the vendor (2 of 223 cached pages had any), so advertisers are counted
from the other end: for each shortlisted niche, the websites of its competitors are looked up in the Ads Transparency
Center (DataForSEO serp/google/ads_search, `target` = domain, location US, one page of 40 ads, $0.0006 a task). Domains
come from earlier stages and must carry one of the niche's brand names (queries/*.yaml): its brand domains on the Google page
(s5_serp, serp_items.csv) first, then the websites of its top App Store apps (s9_wayback, wayback_domains.csv). Other app
sites are left out: the store's top results include giants that advertise everything. A niche without brand domains is
not measured.

Per domain: total ads Google lists for it, ads seen, ads shown within --active-days (30) of ws.today, and the longest run
(last shown - first shown) of an ad that is still running. An advertiser that keeps one ad running for --long-days (90) or
more is very likely paying back its clicks: acquisition through ads works for it. Per niche: competitors checked, how many
advertise now, how many have a long-running ad, the longest run, the share of text ads (Google Search) among active ads,
and the biggest advertiser.
Flags (evidence, never a gate or a score input):
  A:ads-pay   at least 2 competitors run an ad for --long-days or more: paid acquisition is sustained in the niche
  A:no-ads    at least 4 competitors checked and none advertises in the US now: the paid channel is unused (unprofitable,
              or open)
Outputs: data/out/advertisers.csv (per niche), advertisers_domains.csv (per niche and domain).
Cost: printed before any task (--dry stops there); a run stops before paying when the balance is below 1.5x the estimate.
Tasks are asynchronous: posted in batches of 100 and polled; ids not ready when a run ends are kept in
data/cache/dfs/ads_pending.json and collected by the next run. Results are cached per domain and month.
Caveats: a domain shared by a company's other products counts all of its ads; Transparency covers Search, YouTube and
Display together (format text ~ Search); "approx" totals are Google's own; a competitor without its own site is missed.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path

from nichefinder import niches
from nichefinder.sources import dataforseo as dfs
from nichefinder.stages.s5_serp import brand_slugs
from nichefinder.stages.s9_wayback import skip as platform_domain
from nichefinder.workspace import Workspace

SUMMARY = "Who pays for traffic: competitors' ads in the Google Ads Transparency Center (DataForSEO)"
KEYS: tuple[str, ...] = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")

COST_TASK = 0.0006      # USD, serp/google/ads_search, one page of up to 40 ads (measured 2026-11-23)
LOCATION = 2840         # United States
DEPTH = 40


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--per-niche", type=int, default=5, help="competitor domains per niche (default 5)")
    p.add_argument("--active-days", type=int, default=30, help="an ad shown within this many days counts as running")
    p.add_argument("--long-days", type=int, default=90, help="a running ad this old is a long runner")
    p.add_argument("--wait", type=int, default=900, help="seconds to wait for posted tasks before saving them as pending")
    p.add_argument("--niches", nargs="*", help="only these niche ids (default: the shortlist)")
    p.add_argument("--dry", action="store_true", help="print the plan and the cost, post nothing")


def _label(domain: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ".".join(domain.split(".")[:-1]) if "." in domain else domain)


def competitor_domains(ws: Workspace, ids: list[str], per: int) -> dict[str, list[tuple[str, str]]]:
    """niche -> [(domain, source)]: the niche's own brands only - brand domains on the Google page first, then the websites
    of top App Store apps whose domain contains a brand name from queries/*.yaml. Unmatched app sites are left out: the
    store's top results include giants (eBay, AliExpress, Shop, Zoom) that advertise everything, and on the first run they
    made 40 of 74 niches look like paid-acquisition markets."""
    slugs = brand_slugs(ws)
    out: dict[str, list[tuple[str, str]]] = {n: [] for n in ids}

    def add(nid: str, d: str, src: str) -> None:
        d = (d or "").lower().strip()
        d = d[4:] if d.startswith("www.") else d
        if nid in out and d and not platform_domain(d) and d not in [x for x, _ in out[nid]] and len(out[nid]) < per:
            out[nid].append((d, src))

    sp = ws.out("serp_items.csv")
    if sp.is_file():
        for r in csv.DictReader(open(sp, encoding="utf-8")):
            if r.get("group") == "brand":
                add(r["niche_id"], r["domain"], "serp")
    wp = ws.out("wayback_domains.csv")
    if wp.is_file():
        rows = sorted(csv.DictReader(open(wp, encoding="utf-8")), key=lambda r: (r["niche_id"], int(r.get("rank") or 999)))
        for r in rows:
            if any(b in _label(r["domain"].lower()) for b in slugs.get(r["niche_id"], [])):
                add(r["niche_id"], r["domain"], "app")
    return out


def _cache_path(ws: Workspace, domain: str) -> Path:
    key = hashlib.sha1(f"{domain}|{LOCATION}|{DEPTH}|{ws.today:%Y-%m}".encode()).hexdigest()
    return ws.cache("dfs") / f"ads_{key}.json"


def _pending_path(ws: Workspace) -> Path:
    return ws.cache("dfs") / "ads_pending.json"


def collect(ws: Workspace, domains: list[str], wait: int) -> int:
    """Post the uncached domains, poll until ready (or `wait` seconds), cache each result. Returns tasks posted."""
    pend: dict[str, str] = json.loads(_pending_path(ws).read_text(encoding="utf-8")) if _pending_path(ws).is_file() else {}
    todo = [d for d in domains if not _cache_path(ws, d).is_file() and d not in pend.values()]
    posted = 0
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        res = dfs._request("POST", "/serp/google/ads_search/task_post",
                           [{"target": d, "location_code": LOCATION, "depth": DEPTH, "tag": d} for d in batch])
        for t in res.get("tasks") or []:
            d = (t.get("data") or {}).get("tag") or (t.get("data") or {}).get("target")
            if t.get("status_code") == 20100 and d:
                pend[t["id"]] = d
                posted += 1
            else:
                print(f"    {d}: not posted: {t.get('status_code')} {t.get('status_message')}")
        _pending_path(ws).write_text(json.dumps(pend), encoding="utf-8")
    deadline = time.time() + wait
    while pend and time.time() < deadline:
        time.sleep(10)
        for tid, d in list(pend.items()):
            g = dfs._raw_request("GET", f"/serp/google/ads_search/task_get/advanced/{tid}")
            t = (g.get("tasks") or [{}])[0]
            code = t.get("status_code")
            if code == 20000:
                _cache_path(ws, d).write_text(json.dumps((t.get("result") or [{}])[0], ensure_ascii=False), encoding="utf-8")
                del pend[tid]
            elif code in (40601, 40602) or not code:      # handed / in queue: not ready yet
                continue
            elif dfs.is_account_error(code):               # the account itself is refused: stop, keep the pending ids
                _pending_path(ws).write_text(json.dumps(pend), encoding="utf-8")
                raise dfs.AccountError(f"DataForSEO {code}: {t.get('status_message')}")
            else:                                            # 40102 no results = no ads; other final errors recorded as empty
                if code != 40102:
                    print(f"    {d}: {code} {t.get('status_message')} - recorded as no ads")
                _cache_path(ws, d).write_text(json.dumps({"items": [], "se_results_count": 0, "status": code}), encoding="utf-8")
                del pend[tid]
        _pending_path(ws).write_text(json.dumps(pend), encoding="utf-8")
        print(f"    {len(domains) - len(pend)}/{len(domains)} domains ready", flush=True)
    if pend:
        print(f"  {len(pend)} tasks not ready after {wait} s: kept in {_pending_path(ws).name}; re-run to collect them (no new cost)")
    return posted


def _ts(s: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def domain_stats(res: dict, today: dt.date, active_days: int, long_days: int) -> dict:
    items = res.get("items") or []
    now = dt.datetime.combine(today, dt.time(23, 59))
    active, longest, long_runs, text = 0, 0, 0, 0
    names = {}
    for it in items:
        f, l = _ts(it.get("first_shown") or ""), _ts(it.get("last_shown") or "")
        if it.get("title"):
            names[it["title"]] = names.get(it["title"], 0) + 1
        if not (f and l) or (now - l).days > active_days:
            continue
        active += 1
        run = (l - f).days
        longest = max(longest, run)
        long_runs += int(run >= long_days)
        text += int(it.get("format") == "text")
    total = res.get("se_results_count")
    return {"ads_total": total if isinstance(total, int) else len(items), "ads_seen": len(items), "active": active,
            "longest_active_days": longest if active else "", "long_runners": long_runs,
            "text_share": round(text / active, 2) if active else "",
            "advertiser": max(names, key=names.get) if names else ""}


def niche_row(nid: str, doms: list[dict]) -> dict:
    measured = [d for d in doms if d["measured"]]
    adv = [d for d in measured if d["active"]]
    longs = [d for d in adv if d["long_runners"]]
    act = sum(d["active"] for d in adv)
    text = sum(d["active"] * float(d["text_share"] or 0) for d in adv)
    top = max(adv, key=lambda d: d["ads_total"] or 0, default=None)
    flags = []
    if len(longs) >= 2:
        flags.append("A:ads-pay")
    if len(measured) >= 4 and not adv:
        flags.append("A:no-ads")
    return {"niche_id": nid, "checked": len(measured), "advertisers_now": len(adv),
            "adv_share": round(len(adv) / len(measured), 2) if measured else "",
            "long_runner_advertisers": len(longs),
            "longest_active_days": max((d["longest_active_days"] or 0 for d in adv), default=""),
            "text_share": round(text / act, 2) if act else "",
            "top_advertiser": f"{top['domain']} ({top['ads_total']} ads)" if top else "",
            "advertisers": " | ".join(f"{d['domain']} ({d['active']} running)" for d in adv[:5]),
            "flags": " ".join(flags)}


def run(ws: Workspace, args: argparse.Namespace) -> None:
    ids = args.niches or niches.shortlist_ids(ws)
    doms = competitor_domains(ws, ids, max(1, args.per_niche))
    if not any(doms.values()):
        print("no competitor domains: run s5_serp and s9_wayback first; skipping")
        return
    uniq = sorted({d for lst in doms.values() for d, _ in lst})
    pend = json.loads(_pending_path(ws).read_text(encoding="utf-8")) if _pending_path(ws).is_file() else {}
    new = [d for d in uniq if not _cache_path(ws, d).is_file() and d not in pend.values()]
    expected = len(new) * COST_TASK
    print(f"{sum(1 for v in doms.values() if v)} niches, {len(uniq)} competitor domains: {len(new)} to post, "
          f"{len(pend)} pending; expected cost about ${expected:.2f}")
    if args.dry:
        return
    if expected > 0:
        bal = dfs.balance()
        print("balance before:", bal)
        if bal < expected * 1.5:
            raise SystemExit(f"DataForSEO balance ${bal:.2f} is below the expected ${expected:.2f} (x1.5 margin): top up or "
                             "lower --per-niche; cached domains stay free")
    try:
        collect(ws, uniq, args.wait)
    except dfs.AccountError as e:
        raise SystemExit(f"{e} - the account cannot run paid tasks; fix it at https://app.dataforseo.com/ and re-run")
    rows, drows = [], []
    for nid, lst in doms.items():
        if not lst:
            continue
        ds = []
        for d, src in lst:
            p = _cache_path(ws, d)
            st = domain_stats(json.loads(p.read_text(encoding="utf-8")), ws.today, args.active_days, args.long_days) if p.is_file() else {}
            ds.append({"niche_id": nid, "domain": d, "source": src, "measured": int(bool(st)),
                       **{k: st.get(k, "") for k in ("ads_total", "ads_seen", "active", "longest_active_days", "long_runners",
                                                     "text_share", "advertiser")}})
        for x in ds:
            x["active"] = x["active"] or 0
            x["long_runners"] = x["long_runners"] or 0
        rows.append(niche_row(nid, ds))
        drows += ds
        r = rows[-1]
        print(f"  {nid:36} {r['advertisers_now']}/{r['checked']} advertise now, long runners {r['long_runner_advertisers']}, "
              f"longest {r['longest_active_days'] or '-'} d, text {r['text_share'] or '-'} {r['flags']}")
    with open(ws.out("advertisers.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("advertisers_domains.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(drows[0].keys()))
        w.writeheader()
        w.writerows(drows)
    print(f"-> advertisers.csv {len(rows)}, advertisers_domains.csv {len(drows)}"
          + (f"; balance after: {dfs.balance()}" if expected > 0 else ""))
