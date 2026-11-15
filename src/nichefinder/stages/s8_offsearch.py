"""Summary of demand outside search per shortlisted niche.

Sources: youtube_trends.csv (YouTube search interest: level against the reference topic and the trend over two
years), reddit_niche.csv (community size), appstore_velocity.csv (rating velocity and the pull of new entrants
within 24 months, US/RU), gplay_metrics.csv (Android installs, players, new apps, US/RU storefronts),
hh_niche.csv (Russian B2B: vacancies that name the brands). Missing source files simply leave their columns empty.
The score is not changed (weights are fixed in advance): the summary feeds the passports and the report, and
offsearch_flags lists what confirms or contradicts the demand picture.

Input: data/out/*.csv above and score_final.csv (for the verdict column). Output: data/out/offsearch.csv.
"""
from __future__ import annotations

import argparse
import csv

from nichefinder import niches
from nichefinder.workspace import Workspace

SUMMARY = "Off-search demand summary and flags per niche"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()


def load(ws, name, key=("niche_id",)):
    p = ws.out(name)
    if not p.exists():
        return {}
    d = {}
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        d[tuple(r[k] for k in key)] = r
    return d


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def col(row, prefix):
    """Value of the first column whose name starts with `prefix` (the YouTube columns carry the window's years)."""
    for k, v in row.items():
        if k.startswith(prefix):
            return v
    return None


def run(ws: Workspace, args: argparse.Namespace) -> None:
    ids = niches.shortlist_ids(ws)
    score = load(ws, "score_final.csv")
    yt, rd, hh = load(ws, "youtube_trends.csv"), load(ws, "reddit_niche.csv"), load(ws, "hh_niche.csv")
    av, gp = load(ws, "appstore_velocity.csv", ("niche_id", "store")), load(ws, "gplay_metrics.csv", ("niche_id", "country"))
    rows = []
    for nid in ids:
        y, r, h = yt.get((nid,), {}), rd.get((nid,), {}), hh.get((nid,), {})
        au, ar, gu, gr = av.get((nid, "us"), {}), av.get((nid, "ru"), {}), gp.get((nid, "us"), {}), gp.get((nid, "ru"), {})
        row = {"niche_id": nid, "verdict": score.get((nid,), {}).get("verdict", ""),
               "yt_topic": y.get("anchor", ""), "yt_level": f(col(y, "yt_level_vs_ref_")), "yt_r_24_22": f(col(y, "yt_r_")), "yt_verdict": y.get("yt_verdict", "NA"),
               "reddit_primary": r.get("primary_sub", ""), "reddit_primary_subs": f(r.get("primary_subscribers")), "reddit_sum_subs": f(r.get("sum_subscribers")),
               "as_us_vel_pm": f(au.get("vel_total_pm")), "as_us_new24": f(au.get("new_24m")), "as_us_new24_pm": f(au.get("new_24m_ratings_pm")), "as_us_new_share": f(au.get("new_share")), "as_us_fastest_new": au.get("fastest_new", ""), "as_us_fastest_new_pm": f(au.get("fastest_new_pm")),
               "as_ru_vel_pm": f(ar.get("vel_total_pm")), "as_ru_new24": f(ar.get("new_24m")), "as_ru_new24_pm": f(ar.get("new_24m_ratings_pm")),
               "gp_us_apps": f(gu.get("apps")), "gp_us_installs": f(gu.get("installs_sum")), "gp_us_players_100k": f(gu.get("players_100k")), "gp_us_players_1m": f(gu.get("players_1m")), "gp_us_top1": gu.get("top1", ""), "gp_us_top1_share": f(gu.get("top1_share")), "gp_us_new24": f(gu.get("new_24m")), "gp_us_new24_installs": f(gu.get("new_24m_installs")),
               "gp_ru_apps": f(gr.get("apps")), "gp_ru_installs": f(gr.get("installs_sum")), "gp_ru_players_100k": f(gr.get("players_100k")), "gp_ru_top1": gr.get("top1", ""), "gp_ru_top1_share": f(gr.get("top1_share")), "gp_ru_new24": f(gr.get("new_24m")),
               "hh_vacancies": f(h.get("vacancies_sum")), "hh_top_brand": h.get("top_brand", ""), "hh_top_vacancies": f(h.get("top_vacancies"))}
        flags = []
        if row["yt_verdict"] == "UP":
            flags.append("YT:up")
        elif row["yt_verdict"] == "DOWN":
            flags.append("YT:down")
        if (row["as_us_new_share"] or 0) >= 0.4 and (row["as_us_new24_pm"] or 0) >= 500:
            flags.append("AS:new-entrants")   # new apps (24 months) collect >= 40% of the niche's ratings: open for entry (or a clone factory)
        if (row["gp_us_players_100k"] or 0) >= 8 and (row["gp_us_top1_share"] or 1) <= 0.5:
            flags.append("GP:fragmented")
        if (row["gp_us_top1_share"] or 0) > 0.7:
            flags.append("GP:top1>70%")
        if (row["hh_vacancies"] or 0) >= 50:
            flags.append("HH:adopted")
        row["offsearch_flags"] = ";".join(flags)
        rows.append(row)
        print(f"{nid:36} YT={row['yt_verdict']:4} lvl={row['yt_level'] if row['yt_level'] is not None else '-':>6} r/{row['reddit_primary'][:14]:14} {int(row['reddit_primary_subs'] or 0):>8} | AS new24={int(row['as_us_new24'] or 0):>3} share={row['as_us_new_share'] or '-'} | GP inst={int(row['gp_us_installs'] or 0):>12,} >=100k={int(row['gp_us_players_100k'] or 0):>2} top1={row['gp_us_top1_share'] or '-'} | hh={int(row['hh_vacancies'] or 0)} {row['offsearch_flags']}")
    keys = list(rows[0].keys())
    with open(ws.out("offsearch.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    print("-> data/out/offsearch.csv", len(rows))
