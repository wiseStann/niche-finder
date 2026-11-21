"""S5 evidence: free open-source substitutes on GitHub per shortlisted niche.

What it measures: whether a buyer could skip the product and run a free open-source project instead. For each
shortlisted niche it takes up to `phrases_per_niche` English category queries (niches.keyword_rows, intent category,
the anchor first), strips the generic tail ("... app", "... software for small business"), and searches GitHub for
the exact phrase in repository names, descriptions and topics, sorted by stars (top 100 per phrase, forks excluded).
A repository counts when its name + description + topics contain the phrase (word order kept, plural and hyphen
tolerant; a one-word phrase must be in the name or the topics) or match the niche's regex from niches.text_matchers,
and match neither the `exclude` regex (awesome lists, tutorials, clones, boilerplates...) nor the niche's `not` regex.
Metrics per niche: relevant repos, repos with >= 100 and >= 1,000 stars, the top repo (stars, last push, licence),
maintained repos with >= 1,000 stars (not archived, pushed within `maintained_months` of ws.today), and the flag
`O:oss-substitute` when at least one such repo exists.

Inputs: config/shortlist.yaml, queries/*.yaml (English category queries), config/oss.yaml (phrase count, generic
words, exclude regex, per-niche phrase overrides, `not` regexes and skips).
Outputs: data/out/oss_substitutes.csv (one row per niche), data/out/oss_repos.csv (relevant repos, plus irrelevant
ones with >= 100 stars so the filter can be audited).
Cache: data/cache/github/, keyed by the run month (ws.today:%Y-%m) and the query.
Cost: free. The search API allows 10 requests a minute without a token, so a cold run of ~70 niches x 3 phrases takes
about 25 minutes; GITHUB_TOKEN (optional, sent as a Bearer header, never in a URL) raises the limit to 30 a minute.
Caveats: evidence only, it never changes the S6 score or verdict. Stars measure developer attention, not end-user
adoption: a 5,000-star self-hosted app substitutes for a B2B tool bought by technical teams, much less for a consumer
mobile app. Stars can be bought: oss_repos.csv keeps `forks` so a repo with many stars and almost no forks can be
spotted. Phrase search misses projects described in other words, and the top 100 by stars can truncate the counts of
a popular phrase (column `truncated`).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import time
import urllib.parse

from nichefinder import http, niches
from nichefinder.workspace import Workspace

SUMMARY = "Open-source substitutes on GitHub per niche (evidence)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

API = "https://api.github.com/search/repositories"
PER_PAGE = 100
FLAG = "O:oss-substitute"
DEFAULTS = {
    "phrases_per_niche": 3,
    "maintained_months": 12,
    "max_words": 4,
    "trail_words": ["app", "apps", "application", "software", "tool", "tools", "platform", "service", "services", "system",
                    "solution", "solutions", "program", "website", "online", "free", "iphone", "android"],
    "lead_words": ["best", "free", "top", "online"],
    "cut_words": ["for", "with", "by", "from"],
    "exclude": r"\b(awesome|tutorials?|courses?|clone|boilerplate|starter|templates?|interview|cheat.?sheet|examples?|demo|homework assignment|learning project|portfolio)\b",
}


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--niche", action="append", default=[], help="measure only these niche ids (repeatable)")


# ---- phrases ------------------------------------------------------------------

def strip_phrase(q: str, st: dict) -> str:
    """'free invoice app for small business' -> 'invoice'; 'app blocker' stays (only the generic tail is cut)."""
    words = re.sub(r"[^\w\s'-]", " ", q.lower()).split()
    for i, w in enumerate(words):
        if w in st["cut_words"] and i > 0:
            words = words[:i]
            break
    while words and words[0] in st["lead_words"]:
        words = words[1:]
    while len(words) > 1 and words[-1] in st["trail_words"]:
        words = words[:-1]
    if len(words) == 1 and words[0] in st["trail_words"]:
        return ""
    return " ".join(words)


def phrases_for(nid: str, rows: list[dict], st: dict, overrides: dict) -> list[str]:
    if nid in overrides:
        return [p for p in overrides[nid] or [] if p]
    out: list[str] = []
    for r in sorted((r for r in rows if r["niche_id"] == nid and r["intent"] == "category"), key=lambda r: -r["anchor"]):
        p = strip_phrase(r["q"], st)
        if p and len(p.split()) <= int(st["max_words"]) and p not in out:
            out.append(p)
    return out[:int(st["phrases_per_niche"])]


def phrase_regex(phrase: str) -> re.Pattern:
    """Words in order, any separators (space, hyphen, underscore, none), short suffixes allowed (plural, -er)."""
    parts = [re.escape(w) + r"\w{0,3}" for w in re.split(r"[\s-]+", phrase) if w]
    return re.compile(r"(?<![a-z0-9])" + r"[\s\-_./]*".join(parts) + r"(?![a-z0-9])", re.I)


def repo_text(r: dict) -> str:
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", r.get("name") or "")
    return f"{name} {r.get('description') or ''} {' '.join(t.replace('-', ' ') for t in r.get('topics') or [])}"


# ---- GitHub -------------------------------------------------------------------

def search(ws: Workspace, phrase: str, token: str | None) -> dict | None:
    q = f'"{phrase}" in:name,description,topics fork:false'
    url = f"{API}?{urllib.parse.urlencode({'q': q, 'sort': 'stars', 'order': 'desc', 'per_page': PER_PAGE})}"
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    pause = 2.2 if token else 6.5            # 30 / 10 search requests a minute
    for attempt in range(4):
        try:
            return http.get_json(url, cache=ws.cache("github"), cache_key=f"{ws.today:%Y-%m}|{q}", headers=headers,
                                 sleep=pause, tries=2, retry_statuses=(500, 502, 503, 504))
        except http.HttpError as e:
            if e.status in (403, 429) and attempt < 3:
                print(f"    rate limited ({e.status}), waiting 65 s", flush=True)
                time.sleep(65)
                continue
            print(f"    {phrase!r}: HTTP {e.status} {e.body[:120]}")
            return None
        except (OSError, ValueError) as e:
            print(f"    {phrase!r}: {str(e)[:160]}")
            return None
    return None


# ---- run ----------------------------------------------------------------------

def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = dict(ws.load_config("oss.yaml", {}) or {})
    st = {**DEFAULTS, **(cfg.get("settings") or {})}
    for k in ("trail_words", "lead_words", "cut_words", "exclude"):
        if cfg.get(k):
            st[k] = cfg[k]
    overrides = cfg.get("queries") or {}
    skip = set(cfg.get("skip") or [])
    excl = re.compile(st["exclude"], re.I) if st["exclude"] else None
    nots = {nid: re.compile(rx, re.I) for nid, rx in (cfg.get("not") or {}).items() if rx}
    token = os.environ.get("GITHUB_TOKEN") or None
    ids = niches.shortlist_ids(ws)
    want = set(getattr(args, "niche", None) or [])
    if want:
        ids = [i for i in ids if i in want]
    rows_en = niches.keyword_rows(ws, "en")
    mx = niches.text_matchers(ws, ids)
    cutoff = ws.today - dt.timedelta(days=round(int(st["maintained_months"]) * 30.44))
    print(f"{len(ids)} shortlisted niches, GitHub token: {'yes' if token else 'no (10 searches a minute)'}; maintained = pushed since {cutoff}")
    out, repos_out = [], []
    for nid in ids:
        if nid in skip:
            print(f"{nid:34} skipped (config/oss.yaml)")
            continue
        phrases = phrases_for(nid, rows_en, st, overrides)
        if not phrases:
            print(f"{nid:34} no English category query - skipped")
            continue
        seen: dict[str, dict] = {}
        totals, truncated, failed = [], False, 0
        for ph in phrases:
            data = search(ws, ph, token)
            if data is None:
                failed += 1
                continue
            items = data.get("items") or []
            totals.append(f"{ph}={data.get('total_count', '?')}")
            pr = phrase_regex(ph)
            one_word = len(ph.split()) == 1
            for r in items:
                text = repo_text(r)
                # a one-word phrase ("recipe", "bible") must sit in the name or the topics, not just in the description
                where = repo_text({**r, "description": ""}) if one_word else text
                rel = (bool(pr.search(where) or (nid in mx and mx[nid](text)))
                       and not (excl is not None and excl.search(text)) and not (nid in nots and nots[nid].search(text)))
                key = r.get("full_name", "")
                if key in seen:
                    seen[key]["relevant"] |= int(rel)
                    continue
                pushed = (r.get("pushed_at") or "")[:10]
                seen[key] = {"full_name": key, "stars": int(r.get("stargazers_count") or 0), "forks": int(r.get("forks_count") or 0),
                             "pushed": pushed,
                             "license": ((r.get("license") or {}).get("spdx_id") or ""), "archived": int(bool(r.get("archived"))),
                             "maintained": int(bool(pushed) and not r.get("archived") and dt.date.fromisoformat(pushed) >= cutoff),
                             "language": r.get("language") or "", "topics": " ".join((r.get("topics") or [])[:8]),
                             "description": re.sub(r"\s+", " ", r.get("description") or "").strip()[:200],
                             "phrase": ph, "url": r.get("html_url", ""), "relevant": int(rel)}
            if len(items) >= PER_PAGE and int(items[-1].get("stargazers_count") or 0) >= 100:
                truncated = True
        rel = sorted((r for r in seen.values() if r["relevant"]), key=lambda r: -r["stars"])
        m1k = [r for r in rel if r["stars"] >= 1000 and r["maintained"]]
        top = rel[0] if rel else {}
        row = {"niche_id": nid, "phrases": " | ".join(phrases), "gh_total": " | ".join(totals),
               "fetched": len(seen), "relevant": len(rel),
               "stars_100": sum(1 for r in rel if r["stars"] >= 100), "stars_1k": sum(1 for r in rel if r["stars"] >= 1000),
               "maintained_1k": len(m1k), "top_repo": top.get("full_name", ""), "top_stars": top.get("stars", ""),
               "top_pushed": top.get("pushed", ""), "top_license": top.get("license", ""),
               "top_maintained": top.get("maintained", ""), "top_url": top.get("url", ""),
               "top3": " | ".join(f"{r['full_name']} ({r['stars']:,})" for r in rel[:3]),
               "truncated": int(truncated), "failed_phrases": failed, "flags": FLAG if m1k else ""}
        out.append(row)
        for r in sorted(seen.values(), key=lambda r: (-r["relevant"], -r["stars"])):
            if r["relevant"] or r["stars"] >= 100:
                repos_out.append({"niche_id": nid, **r})
        print(f"{nid:34} rel={len(rel):>3} >=100={row['stars_100']:>3} >=1k={row['stars_1k']:>3} maint1k={len(m1k):>2} "
              f"{row['flags']:16} | {row['top_repo'][:40]} {row['top_stars']}", flush=True)
    if not out:
        print("no niche measured - nothing written")
        return
    p, p2 = ws.out("oss_substitutes.csv"), ws.out("oss_repos.csv")
    if want:
        # a partial run (--niche) replaces only the niches it measured
        done = {r["niche_id"] for r in out}
        out = _kept(p, done) + out
        repos_out = _kept(p2, done) + repos_out
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[-1].keys()))
        w.writeheader()
        w.writerows(out)
    with open(p2, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["niche_id", "full_name", "stars", "forks", "pushed", "license", "archived", "maintained", "language",
                                          "topics", "description", "phrase", "url", "relevant"])
        w.writeheader()
        w.writerows(repos_out)
    print("->", p, len(out), f"({sum(1 for r in out if r['flags'])} flagged {FLAG}) |", p2, len(repos_out))


def _kept(path, done: set) -> list[dict]:
    if not path.is_file():
        return []
    return [r for r in csv.DictReader(open(path, encoding="utf-8")) if r.get("niche_id") not in done]
