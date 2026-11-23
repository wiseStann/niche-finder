"""Who owns the first page of Google for a niche's category queries, and how hard it is to rank there.

For each shortlisted niche: the anchor and up to --per-niche English category queries (queries/*.yaml), one live Google
SERP each (DataForSEO serp/google/organic/live/advanced, US, top 10, about $0.002 a page), plus DataForSEO Labs keyword
difficulty (0-100) for the same queries in one bulk task. The organic top 10 is sorted into groups by config/serp_domains.yaml:
review directories, app stores and marketplaces, user-generated content, media listicles (the listed publishers plus any
page titled like a comparison: "best ... apps", "8 top picks"), the niche's own brands (domain contains a brand name from
queries/*.yaml) and other sites (smaller vendors, blogs). SERP features are counted too:
an AI Overview answers the query on Google itself (platform risk evidence), a local pack means local intent.

Flags (evidence, never a gate or a score input):
  R:serp-leaders   brands of the niche hold at least 2 of the top 3 on average: SEO entry is hard, leaders own the page
  R:serp-listicles directories + media hold at least half of the top 10: entry goes through listings and listicles
  R:ai-overview    at least half of the queries show an AI Overview
Outputs: data/out/serp_ownership.csv (niche level), data/out/serp_items.csv (every organic result).
Cost: printed before any call (--dry stops there); a run stops before paying when the balance is below the estimate.
Every SERP and difficulty task is cached in data/cache/dfs/, so re-runs are free.
Caveats: one snapshot of a personalised, daily-changing page; the brand match is by name and misses renamed domains. Since
2026-11 the vendor returns many organic results as google.com redirects (the real domain is read from the breadcrumb), and
some US pages carry European results (hl=nl, .de sites).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
from urllib.parse import urlparse

from nichefinder import niches
from nichefinder.sources import dataforseo as dfs
from nichefinder.workspace import Workspace

SUMMARY = "SERP ownership and keyword difficulty for category queries (DataForSEO Labs)"
KEYS: tuple[str, ...] = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")
GROUPS = ("directory", "store", "ugc", "media")


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--per-niche", type=int, default=3, help="category queries per niche, anchor first (default 3)")
    p.add_argument("--dry", action="store_true", help="print the plan and the expected cost, make no calls")
    p.add_argument("--niches", nargs="*", help="only these niche ids (default: the shortlist)")


def plan(ws: Workspace, ids: list[str], per: int) -> dict[str, list[str]]:
    """niche -> [anchor, other category queries...] in English."""
    rows = niches.keyword_rows(ws, "en")
    out: dict[str, list[str]] = {}
    for nid in ids:
        mine = [r for r in rows if r["niche_id"] == nid and r["intent"] == "category"]
        mine.sort(key=lambda r: -r["anchor"])
        qs = list(dict.fromkeys(r["q"].strip().lower() for r in mine))[:per]
        if qs:
            out[nid] = qs
    return out


def brand_slugs(ws: Workspace) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in niches.keyword_rows(ws, "en") + niches.keyword_rows(ws, "ru"):
        if r["intent"] == "brand" and r["brand"]:
            s = re.sub(r"[^a-z0-9]", "", str(r["brand"]).lower())
            if len(s) >= 4 and s not in out.setdefault(r["niche_id"], []):
                out[r["niche_id"]].append(s)
    return out


PLATFORMS = {"facebook": "facebook.com", "reddit": "reddit.com", "youtube": "youtube.com", "quora": "quora.com",
             "medium": "medium.com", "linkedin": "linkedin.com", "instagram": "instagram.com", "tiktok": "tiktok.com",
             "x": "x.com", "twitter": "twitter.com", "pinterest": "pinterest.com", "vk": "vk.com"}


def domain_of(item: dict) -> str:
    """The result's own domain. Since 2026-11 many organic items carry a google.com/goto redirect as `url` and google.com as
    `domain`; the real address is then in `breadcrumb` ("https://promapranker.com › Blog"), or for social sites only in
    `website_name` ("Facebook · Stellarium Labs")."""
    d = (item.get("domain") or urlparse(item.get("url") or "").netloc or "").lower()
    d = d[4:] if d.startswith("www.") else d
    if d == "google.com":
        m = re.match(r"https?://([^\s/›]+)", item.get("breadcrumb") or "")
        if m:
            d = m.group(1).lower()
        else:
            name = (item.get("website_name") or "").split("·")[0].strip().lower()
            d = PLATFORMS.get(name, d)
    return d[4:] if d.startswith("www.") else d


# A comparison page of any site counts as a media listicle: "Best Reward Card Apps 2026", "8 Top Picks", "Top 10 ... software".
LISTICLE = re.compile(r"\b(best|top)\b.{0,60}\b(apps?|software|tools?|platforms?|services|picks|options|alternatives)\b"
                      r"|\b\d{1,2}\s+(best|top)\b|\btop\s+\d{1,2}\b", re.I)


def classify(domain: str, groups: dict[str, list[str]], brands: list[str], title: str = "") -> str:
    for g in GROUPS:
        for x in groups.get(g) or []:
            if domain == x or domain.endswith("." + x):
                return g
    label = re.sub(r"[^a-z0-9]", "", ".".join(domain.split(".")[:-1]) if "." in domain else domain)
    if any(b in label for b in brands):
        return "brand"
    return "media" if LISTICLE.search(title or "") else "other"


def niche_metrics(nid: str, serps: dict[str, list[dict]], kd: dict[str, float], groups: dict, brands: list[str]):
    items_out, counts, top3_brand, ai, local, paid, domains = [], {}, [], 0, 0, 0, set()
    n_org = 0
    for q, items in serps.items():
        types = {it.get("type") for it in items}
        ai += int("ai_overview" in types)
        local += int("local_pack" in types)
        paid += sum(1 for it in items if it.get("type") == "paid")
        org = sorted((it for it in items if it.get("type") == "organic"), key=lambda it: it.get("rank_group") or 99)[:10]
        t3 = 0
        for it in org:
            d = domain_of(it)
            g = classify(d, groups, brands, it.get("title") or "")
            counts[g] = counts.get(g, 0) + 1
            domains.add(d)
            n_org += 1
            t3 += int(g == "brand" and (it.get("rank_group") or 99) <= 3)
            items_out.append({"niche_id": nid, "query": q, "rank": it.get("rank_group"), "domain": d, "group": g,
                              "title": (it.get("title") or "")[:150], "url": it.get("url") or ""})
        top3_brand.append(t3)
    nq = len(serps)
    sh = lambda g: round(counts.get(g, 0) / n_org, 2) if n_org else ""  # noqa: E731
    kds = [kd[q] for q in serps if q in kd]
    row = {"niche_id": nid, "queries": nq, "organic": n_org, "distinct_domains": len(domains),
           **{f"{g}_share": sh(g) for g in (*GROUPS, "brand", "other")},
           "top3_brand_avg": round(sum(top3_brand) / nq, 2) if nq else "",
           "ai_overview_share": round(ai / nq, 2) if nq else "", "local_pack_share": round(local / nq, 2) if nq else "",
           "paid_items": paid, "kd_mean": round(sum(kds) / len(kds), 1) if kds else ""}
    flags = []
    if nq and sum(top3_brand) / nq >= 2:
        flags.append("R:serp-leaders")
    if n_org and (counts.get("directory", 0) + counts.get("media", 0)) / n_org >= 0.5:
        flags.append("R:serp-listicles")
    if nq and ai / nq >= 0.5:
        flags.append("R:ai-overview")
    row["flags"] = " ".join(flags)
    top = sorted(((d, sum(1 for i in items_out if i["domain"] == d)) for d in domains), key=lambda kv: -kv[1])[:5]
    row["top_domains"] = " | ".join(f"{d} ({c})" for d, c in top)
    return row, items_out


def run(ws: Workspace, args: argparse.Namespace) -> None:
    ids = args.niches or niches.shortlist_ids(ws)
    queries = plan(ws, ids, max(1, args.per_niche))
    allq = sorted({q for qs in queries.values() for q in qs})
    unc = [q for q in allq if not dfs.serp_cached(ws, q)]
    kd_batches = [allq[i:i + dfs.BATCH] for i in range(0, len(allq), dfs.BATCH)]
    kd_unc = [b for b in kd_batches if not dfs.keyword_difficulty_cached(ws, b)]
    expected = len(unc) * dfs.COST_SERP + sum(dfs.COST_KD_TASK + len(b) * dfs.COST_KD_KEYWORD for b in kd_unc)
    print(f"{len(queries)} niches, {len(allq)} queries: {len(unc)} SERPs and {len(kd_unc)} difficulty task(s) not cached; "
          f"expected cost about ${expected:.2f}")
    if args.dry:
        return
    if expected > 0:
        bal = dfs.balance()
        print("balance before:", bal)
        if bal < expected * 1.5:
            raise SystemExit(f"DataForSEO balance ${bal:.2f} is below the expected ${expected:.2f} (x1.5 margin): "
                             "top up at https://app.dataforseo.com/ and re-run; cached SERPs stay free")
    kd: dict[str, float] = {}
    for b in kd_batches:
        try:
            kd.update(dfs.keyword_difficulty(ws, b)[0])
        except dfs.AccountError as e:
            raise SystemExit(f"{e} - the account cannot run paid tasks; fix it at https://app.dataforseo.com/ and re-run")
        except RuntimeError as e:
            print(f"  keyword difficulty unavailable: {e}")
    groups = ws.load_config("serp_domains.yaml", {}) or {}
    slugs = brand_slugs(ws)
    rows, items = [], []
    for nid, qs in queries.items():
        serps = {}
        for q in qs:
            try:
                serps[q] = dfs.serp(ws, q)[0]
            except dfs.AccountError as e:
                raise SystemExit(f"{e} - the account cannot run paid tasks; fix it at https://app.dataforseo.com/ and re-run")
            except RuntimeError as e:
                print(f"  {nid}: {q!r}: {e}")
        if not serps:
            continue
        r, its = niche_metrics(nid, serps, kd, groups, slugs.get(nid, []))
        rows.append(r)
        items += its
        print(f"  {nid:36} dir {r['directory_share']!s:>4} media {r['media_share']!s:>4} brand {r['brand_share']!s:>4} "
              f"top3 brand {r['top3_brand_avg']!s:>4} AIO {r['ai_overview_share']!s:>4} KD {r['kd_mean']!s:>5} {r['flags']}")
    if not rows:
        print("no SERPs - nothing written")
        return
    with open(ws.out("serp_ownership.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("serp_items.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "query", "rank", "domain", "group", "title", "url"])
        w.writeheader()
        w.writerows(items)
    print(f"-> serp_ownership.csv {len(rows)}, serp_items.csv {len(items)}"
          + (f"; balance after: {dfs.balance()} ({dt.datetime.now():%H:%M})" if expected > 0 else ""))
