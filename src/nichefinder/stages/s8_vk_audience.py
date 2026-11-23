"""VK communities per niche: how many Russian-speaking people follow its topic or its trade (evidence, never the score).

The Russian counterpart of s8_subreddit_stats. It is not a voice source: a probe on 2026-11-23 found that VK
communities are content feeds and the businesses' own client pages, where tools are almost never discussed (the
Telegram chats of s10_tg_* carry that voice). What VK does show is the size of the audience around a topic.

Niches: shortlisted niches with geo both or ru.
1. Phrases. An LLM (LLM_API_KEY, one cached call per niche) writes `vk_audience.phrases_llm` short Russian phrases that
   names of VK communities about the niche's topic or its users would contain; `vk_audience.niches.<id>.phrases` adds
   phrases by hand. Without the key only the hand phrases are searched.
2. Communities. groups.search (VK_USER_TOKEN, up to 100 per phrase, VK's relevance order), then groups.getById
   (VK_SERVICE_TOKEN) for members_count, activity and description. Events, closed communities and communities under
   `vk_audience.min_members` members are left out.
3. Check. An LLM (one cached call per 60 communities) keeps the communities whose members are people interested in
   the niche's task or topic, or the niche's users as a trade community, and drops single businesses' pages (a salon,
   a shop, a service), brand and vendor pages, sales and flea markets, city news and other topics.
   `vk_audience.niches.<id>.keep` / `drop` (screen names or ids) override it.
Metrics per niche: kept communities, members of the 10 largest (`members_top10`, an upper bound: people join several
communities and member counts include bots), the largest community, and the counts above 10k and 100k members.

Output: data/out/vk_groups.csv (per candidate community: phrase, members, activity, fit, why, by) and
data/out/vk_audience.csv (per niche). Settings: config/vk_audience.yaml. Keys: VK_SERVICE_TOKEN, VK_USER_TOKEN (lives
about a day, see sources/vk.py); LLM_API_KEY for the phrases and the check. Every VK answer is cached per run month.
Usage: nf run s8_vk_audience -- [--niches a,b]
"""
from __future__ import annotations

import argparse
import csv

from nichefinder import keys, llm, niches
from nichefinder.sources import vk
from nichefinder.workspace import Workspace

SUMMARY = "VK communities per niche: audience size around its topic or trade (evidence; Russian counterpart of subreddit sizes)"
KEYS: tuple[str, ...] = ("VK_SERVICE_TOKEN",)
NEEDS: tuple[str, ...] = ()

CONFIG = "vk_audience.yaml"
GEO = ("both", "ru")
BATCH = 60
GROUP_COLS = ["niche_id", "phrase", "id", "screen_name", "name", "type", "members", "activity", "fit", "why", "by"]
AUD_COLS = ["niche_id", "phrases", "candidates", "communities", "members_top10", "top1", "top1_members", "n_10k", "n_100k", "by", "status"]
DEFAULTS = {"phrases_llm": 5, "per_phrase": 100, "min_members": 1000, "check_candidates": 120, "top_n": 10}
PHRASE_SYSTEM = (
    "You help find VK (VKontakte) communities around a market niche. A niche is who x task x product. Write short Russian search "
    "phrases (1-3 words each) that the names of VK communities about this niche's topic would contain: the topic or hobby itself, "
    "the people who do the task, and for a business niche the trade and its owners or masters. No product or software words, no "
    "city names, no English. "
    'Output JSON {"phrases": ["...", ...]}.')
CHECK_SYSTEM = (
    "You check which VK communities gather the audience of a market niche. A niche is who x task x product. You get the niche and "
    "a numbered list of communities (name | members | VK activity category | start of the description). For each decide fit: yes = "
    "its members are people interested in the niche's task or topic (a topical community, public page or blog about it), or the "
    "niche's users as a community of their trade; no = anything else: a single business's own page (a salon, a shop, a workshop, "
    "a school, a service), a brand or vendor page, sales, ads or flea markets, city news, and communities about another topic or "
    "where the topic is a side mention. "
    'Output JSON: {"items": [{"k": <number>, "fit": "yes" or "no", "why": "<5-12 words>"}]} with every number.')


def settings(ws: Workspace) -> dict:
    cfg = ws.load_config(CONFIG, {}) or {}
    return {**DEFAULTS, **{k: v for k, v in cfg.items() if k != "niches"}}


def target_niches(ws: Workspace, only: str = "") -> list[str]:
    geo = {n["id"]: n.get("geo", "global") for n in niches.load_niches(ws)}
    ids = [i for i in niches.shortlist_ids(ws) if geo.get(i) in GEO]
    wanted = {x.strip() for x in only.split(",") if x.strip()}
    return [i for i in ids if i in wanted] if wanted else ids


def niche_text(n: dict) -> str:
    return f"Niche: {n.get('name') or n['id']}\nWho: {n.get('who', '')}\nTask: {n.get('task', '')}\nProduct: {n.get('product', '')}"


def llm_phrases(ws: Workspace, n: dict, k: int) -> list[str] | None:
    content, _, _ = llm.chat_json(ws, [{"role": "system", "content": PHRASE_SYSTEM},
                                       {"role": "user", "content": f"{niche_text(n)}\n\nPhrases wanted: {k}"}], max_tokens=600, temperature=0.0)
    if not content:
        return None
    out = [" ".join(str(p).split()) for p in content.get("phrases") or [] if str(p).strip()]
    return [p for p in dict.fromkeys(out) if len(p) >= 3][:k]


def check(ws: Workspace, n: dict, groups: list[dict]) -> list[tuple[str, str]]:
    """(fit, why) per community, in order; ("", "no answer from the model") where the model said nothing."""
    out: list[tuple[str, str]] = []
    for i in range(0, len(groups), BATCH):
        part = groups[i:i + BATCH]
        lines = [f"{k}: {g['name']} | {g.get('members_count', 0)} members | {g.get('activity') or '-'} | "
                 f"{' '.join(str(g.get('description') or '').split())[:140]}" for k, g in enumerate(part, 1)]
        content, _, _ = llm.chat_json(ws, [{"role": "system", "content": CHECK_SYSTEM},
                                           {"role": "user", "content": f"{niche_text(n)}\n\nCommunities:\n" + "\n".join(lines)}],
                                      max_tokens=4000, temperature=0.0)
        got: dict[int, tuple[str, str]] = {}
        for it in (content or {}).get("items") or []:
            try:
                got[int(it.get("k"))] = ("yes" if str(it.get("fit")).lower() == "yes" else "no", str(it.get("why") or "")[:120])
            except (TypeError, ValueError, AttributeError):
                continue
        out += [got.get(k, ("", "no answer from the model")) for k in range(1, len(part) + 1)]
    return out


def ref(x) -> str:
    return str(x).strip().lstrip("@").lower()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: the shortlisted niches with geo both or ru)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = settings(ws)
    per = (ws.load_config(CONFIG, {}) or {}).get("niches") or {}
    only = getattr(args, "niches", "") or ""
    ids = target_niches(ws, only)
    if not ids:
        print("  no shortlisted niches with geo both or ru")
        return
    by_id = {n["id"]: n for n in niches.load_niches(ws)}
    use_llm = bool(keys.get("LLM_API_KEY"))
    if not use_llm:
        print("  LLM_API_KEY missing: only hand phrases are searched and every community counts (by = none)")
    groups_out, aud_out = [], []
    for nid in ids:
        n, ncfg = by_id[nid], per.get(nid) or {}
        keep, drop = {ref(x) for x in ncfg.get("keep") or []}, {ref(x) for x in ncfg.get("drop") or []}
        phrases = [str(p) for p in ncfg.get("phrases") or []]
        if use_llm and int(cfg["phrases_llm"]) > 0:
            phrases += llm_phrases(ws, n, int(cfg["phrases_llm"])) or []
        phrases = list(dict.fromkeys(p for p in phrases if p.strip()))
        row = {"niche_id": nid, "phrases": " | ".join(phrases), "candidates": 0, "communities": 0, "members_top10": 0, "top1": "",
               "top1_members": 0, "n_10k": 0, "n_100k": 0, "by": "llm" if use_llm else "none", "status": "ok"}
        if not phrases:
            aud_out.append({**row, "status": "no phrases"})
            continue
        found: dict[int, str] = {}
        for q in phrases:
            for g in vk.search_groups(ws, q, int(cfg["per_phrase"])):
                if g.get("type") != "event" and not g.get("is_closed"):
                    found.setdefault(int(g["id"]), q)
        info = vk.groups_by_id(ws, list(found)) if found else []
        cands = sorted((g for g in info if int(g.get("members_count") or 0) >= int(cfg["min_members"])
                        or ref(g.get("screen_name", "")) in keep or str(g.get("id")) in keep),
                       key=lambda g: -int(g.get("members_count") or 0))[:int(cfg["check_candidates"])]
        fits = check(ws, n, cands) if use_llm and cands else [("yes", "") for _ in cands]
        kept = []
        for g, (fit, why) in zip(cands, fits):
            by = row["by"]
            names = {ref(g.get("screen_name", "")), str(g.get("id"))}
            if names & keep or names & drop:
                fit, by = ("yes" if names & keep else "no"), "config"
            groups_out.append({"niche_id": nid, "phrase": found.get(int(g["id"]), ""), "id": g["id"], "screen_name": g.get("screen_name", ""),
                               "name": g.get("name", ""), "type": g.get("type", ""), "members": int(g.get("members_count") or 0),
                               "activity": g.get("activity", ""), "fit": fit, "why": why, "by": by})
            if fit == "yes":
                kept.append(g)
        top = sorted(kept, key=lambda g: -int(g.get("members_count") or 0))
        mem = [int(g.get("members_count") or 0) for g in top]
        row.update({"candidates": len(cands), "communities": len(top), "members_top10": sum(mem[:int(cfg["top_n"])]),
                    "top1": top[0]["name"][:80] if top else "", "top1_members": mem[0] if mem else 0,
                    "n_10k": sum(1 for m in mem if m >= 10_000), "n_100k": sum(1 for m in mem if m >= 100_000),
                    "status": "ok" if top else "no communities"})
        aud_out.append(row)
        print(f"  {nid:36} phrases {len(phrases)} cand {len(cands):>3} kept {len(top):>3} top10 {row['members_top10']:>11,} "
              f"| {row['top1'][:40]} ({row['top1_members']:,})", flush=True)
    for name, rows, cols in ((("vk_groups.csv"), groups_out, GROUP_COLS), ("vk_audience.csv", aud_out, AUD_COLS)):
        prev = []
        if only and ws.out(name).is_file():   # a run with --niches keeps the other niches' rows
            prev = [r for r in csv.DictReader(open(ws.out(name), encoding="utf-8")) if r["niche_id"] not in set(ids)]
        with open(ws.out(name), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(prev + rows)
    st: dict[str, int] = {}
    for r in aud_out:
        st[r["status"]] = st.get(r["status"], 0) + 1
    print(f"-> vk_audience.csv: {len(aud_out)} niches {st}; vk_groups.csv: {len(groups_out)} communities")
