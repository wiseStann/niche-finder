"""Telegram group chats of each niche's users: Russian buyer voice where owners and practitioners talk among themselves.

Why: Russian small businesses rarely review software in public (Startpack reviews are mostly five-star) and do not talk
about tools in VK communities, which are the businesses' own pages for their clients (probe of 2026-11-23). They do ask
each other in Telegram chats: which booking app, how to link YCLIENTS with Avito, is AvtoDiler worth it.

Niches: shortlisted niches (with the shortlist tier `ru`) with geo both or ru, as for the Russian reviews and YouTube comments.
1. Chat search phrases. An LLM (LLM_API_KEY, one cached call per niche) writes `fetch.phrases_llm` short Russian phrases
   that the titles of these users' group chats would contain: the nouns people use for themselves and their trade, not
   product words. `niches.<id>.phrases` in config/tg_voice.yaml adds phrases by hand. Without the key only the hand
   phrases are searched; a niche with none is `no phrases`.
2. Chats. Telegram's global search (contacts.search, up to 50 public chats per phrase) gives the candidates. Only groups
   (supergroups and forums) count, not broadcast channels: a channel is one voice, usually a vendor or a medium.
   A candidate needs at least `fetch.min_members` members.
3. Chat check. An LLM (one cached call per niche) sees the `fetch.check_candidates` largest candidates (title, members)
   with the niche (who, task, product) and keeps the chats whose members are the niche's users talking about their
   work: owners, practitioners, specialists of the trade, or the users of a product for the task. It drops chats of the
   other side of the market (clients, guests, tenants), job, advertising and barter chats, local neighbourhood chats and
   other trades. A title alone does not tell a trade's chat from one business's customer chat ("Geely Garage"), so with
   `fetch.confirm` the 2 x `fetch.chats` largest chats that passed are checked again with their own description
   (channels.getFullChannel, one cached call per chat); only confirmed chats are read. `niches.<id>.keep` / `drop`
   (usernames) override both checks.
4. Messages. In the `fetch.chats` largest kept chats, Telegram's message search (its own word matching, Russian word
   forms included) for each term: `fetch.terms` (program, app, CRM, accounting, which do you use, recommend, ...) plus
   the niche's brands (the `b` of its Russian brand queries) when `fetch.brands` is on; at most `fetch.max_per_term`
   messages per term, published from the first day of the month `fetch.window_months` before the run month.
Messages are deduplicated per niche by (chat, id). No chat is joined and no author name or id is stored (telegram.py).
Every call is cached per run month in data/cache/telegram/. A FloodWait longer than `fetch.max_flood_wait` seconds stops
live calls: the remaining niches are read from the cache only, a niche the run did not reach is marked `flood` and keeps
its rows from an earlier run.

Output:
  data/out/tg_docs.jsonl   per message: niche_id, chat_id, chat, username, members, term, id, date, reply, fwd, text
  data/out/tg_chats.csv    per candidate chat: the phrase that found it, members, the LLM check (fit, why, by), picked,
                           messages kept, status
  data/out/tg_fetch.csv    per niche: phrases, candidates, relevant, picked, messages, by, status (ok, no phrases,
                           no chats, check failed, flood)
Settings: config/tg_voice.yaml (`fetch`, `niches`). Keys: TG_API_ID and TG_API_HASH plus a session (`nf setup
telegram`); LLM_API_KEY for the phrases and the chat check.
Usage: nf run s10_tg_fetch -- [--niches a,b]
"""
from __future__ import annotations

import argparse

from nichefinder import keys, llm, niches, telegram
from nichefinder.stages.s10_yt_comments_fetch import read_rows, window_start, write_merged
from nichefinder.workspace import Workspace

SUMMARY = "Telegram group chats of each niche's users: public chat search and messages that name tools (Russian buyer voice)"
KEYS: tuple[str, ...] = ("TG_API_ID", "TG_API_HASH")
NEEDS: tuple[str, ...] = ("telegram",)

CONFIG = "tg_voice.yaml"
GEO = ("both", "ru")
DOCS, CHATS, FETCH = "tg_docs.jsonl", "tg_chats.csv", "tg_fetch.csv"
CHAT_COLS = ["niche_id", "phrase", "chat_id", "username", "title", "members", "fit", "why", "by", "confirm", "confirm_why", "picked",
             "messages", "status"]
FETCH_COLS = ["niche_id", "phrases", "candidates", "relevant", "picked", "messages", "by", "status"]
DEFAULTS = {
    "fetch": {"window_months": 24, "phrases_llm": 10, "min_members": 300, "check_candidates": 40, "chats": 5,
              "terms": ["программа", "приложение", "crm", "срм", "учет", "таблица", "excel", "пользуетесь",
                        "посоветуйте", "подскажите", "порекомендуйте"],
              "confirm": True, "brands": True, "max_per_term": 200, "pace_s": 1.5, "max_flood_wait": 120},
    "sample": {"max_messages": 300, "min_chars": 25},
    "verdict": {"min_niche_messages": 40, "min_chats": 2, "min_cohort": 6, "gap_pct": 0.67, "gap_floor": 0.10, "pain_pct": 0.67,
                "pain_floor": 0.20, "seek_pct": 0.67, "seek_floor": 0.12, "howto_pct": 0.67, "howto_floor": 0.20,
                "content_praise": 0.25, "top_chat_warn": 0.60},
}
PHRASE_SYSTEM = (
    "You help find public Telegram group chats where a market niche's users (the 'who') talk among themselves. A niche is who x "
    "task x product. Write short Russian search phrases for Telegram's chat search, which matches words in chat titles, so short "
    "phrases (1-2 words) find more. Mix: the name of the trade or business type alone; owners or managers of this kind of "
    "business (when the users run a business, at least two phrases must be the Russian word for owners or managers plus the "
    "business type); masters or specialists of the trade; for consumer niches, the word the users call themselves or their "
    "hobby. Name the users and their trade, never their clients, customers or the activity the clients buy. Do not add the word "
    "for chat, no product or software words, no city names, no English. "
    'Output JSON {"phrases": ["...", ...]}.')
CHECK_SYSTEM = (
    "You pick public Telegram group chats that carry the voice of a market niche's users. A niche is who x task x product. You "
    "get the niche and a numbered list of chats (title | @username | members, and the chat's own description when known). For "
    "each chat decide fit: yes = its members are "
    "the niche's users talking among themselves about their work or task: owners, practitioners or specialists of this trade, "
    "people who do the task, or the users of a product or tool for it; no = anything else: chats of the other side of the market "
    "(clients, customers, guests, tenants, patients when the niche serves the business), job and vacancy chats, advertising, PR, "
    "barter or sales chats, a single company's customer chat, local neighbourhood or city chats, chats of another trade or task. "
    'Output JSON: {"chats": [{"k": <number>, "fit": "yes" or "no", "why": "<5-12 words>"}]} with every number.')


def settings(ws: Workspace, section: str) -> dict:
    """One block of config/tg_voice.yaml over the defaults; the file is optional."""
    cfg = ws.load_config(CONFIG, {}) or {}
    return {**DEFAULTS[section], **(cfg.get(section) or {})}


def niche_settings(ws: Workspace) -> dict[str, dict]:
    """`niches` block: niche id -> {phrases, keep, drop}."""
    return (ws.load_config(CONFIG, {}) or {}).get("niches") or {}


def config_status(ws: Workspace) -> str:
    return str((ws.load_config(CONFIG, {}) or {}).get("status") or "draft")


def target_niches(ws: Workspace, only: str = "") -> list[str]:
    """Shortlisted niches (with the tier `ru`) with geo both or ru, optionally restricted to a comma-separated list."""
    geo = {n["id"]: n.get("geo", "global") for n in niches.load_niches(ws)}
    ids = [i for i in niches.shortlist_ids(ws, ru=True) if geo.get(i) in GEO]
    wanted = {x.strip() for x in only.split(",") if x.strip()}
    return [i for i in ids if i in wanted] if wanted else ids


def uname(x) -> str:
    return str(x or "").strip().lstrip("@").lower()


def niche_text(niche: dict) -> str:
    return (f"Niche: {niche.get('name') or niche.get('id', '')}\nWho: {niche.get('who', '')}\nTask: {niche.get('task', '')}\n"
            f"Product: {niche.get('product', '')}")


def llm_phrases(ws: Workspace, niche: dict, n: int) -> list[str] | None:
    """Chat search phrases from the LLM; None when the model gave no answer."""
    content, _, _ = llm.chat_json(ws, [{"role": "system", "content": PHRASE_SYSTEM},
                                       {"role": "user", "content": f"{niche_text(niche)}\n\nPhrases wanted: {n}"}],
                                  max_tokens=600, temperature=0.0)
    if not content:
        return None
    out = [" ".join(str(p).split()) for p in (content.get("phrases") or []) if str(p).strip()]
    return [p for p in dict.fromkeys(out) if len(p) >= 3][:n]


def chat_check(ws: Workspace, niche: dict, cands: list[dict]) -> dict[str, tuple[str, str]] | None:
    """The LLM chat check: username (lower case) -> (fit, why); None when the model gave no answer."""
    lines = [f"{k}: {c['title']} | @{c['username']} | {c['members']} members" + (" | forum" if c.get("forum") else "")
             + (f" | description: {' '.join(str(c['about']).split())[:240]}" if c.get("about") else "") for k, c in enumerate(cands, 1)]
    content, _, _ = llm.chat_json(ws, [{"role": "system", "content": CHECK_SYSTEM},
                                       {"role": "user", "content": f"{niche_text(niche)}\n\nChats:\n" + "\n".join(lines)}],
                                  max_tokens=3000, temperature=0.0)
    if not content:
        return None
    out: dict[str, tuple[str, str]] = {}
    for it in content.get("chats") or []:
        try:
            k = int(it.get("k"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= k <= len(cands):
            out[uname(cands[k - 1]["username"])] = ("yes" if str(it.get("fit")).lower() == "yes" else "no", str(it.get("why") or "")[:120])
    return out


def brand_terms(rows: list[dict]) -> list[str]:
    """The brand names of a niche's Russian brand queries (`b`, else the query), in order, without repeats."""
    out = [str(r.get("brand") or r["q"]).strip() for r in rows if r["intent"] == "brand"]
    return list(dict.fromkeys(b for b in out if b))


def make_gateway(ws: Workspace, cfg: dict):
    """The Telegram client (tests replace it with a fake)."""
    return telegram.Gateway(ws, pace=float(cfg["pace_s"]), max_flood_wait=int(cfg["max_flood_wait"]))


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--niches", default="", help="comma-separated niche ids (default: the shortlisted niches with geo both or ru)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = settings(ws, "fetch")
    per = {k: v or {} for k, v in niche_settings(ws).items()}
    only = getattr(args, "niches", "") or ""
    ids = target_niches(ws, only)
    if not ids:
        print("  no shortlisted niches with geo both or ru")
        return
    by_id = {n["id"]: n for n in niches.load_niches(ws)}
    rows = niches.keyword_rows(ws, "ru")
    use_llm = bool(keys.get("LLM_API_KEY"))
    if not use_llm:
        print("  LLM_API_KEY missing: only the hand phrases of config/tg_voice.yaml are searched and every chat counts (by = none)")
    since = window_start(ws.today, int(cfg["window_months"])).isoformat()
    gw = make_gateway(ws, cfg)
    docs_out, chats_out, fetch_out, stopped = [], [], [], ""
    print(f"  {len(ids)} niches; messages since {since}; terms: {', '.join(cfg['terms'])}" + (" + brands" if cfg["brands"] else ""))
    try:
        for nid in ids:
            n, ncfg = by_id[nid], per.get(nid, {})
            keep, drop = {uname(x) for x in ncfg.get("keep") or []}, {uname(x) for x in ncfg.get("drop") or []}
            frow = {"niche_id": nid, "phrases": "", "candidates": 0, "relevant": 0, "picked": 0, "messages": 0,
                    "by": "llm" if use_llm else "none", "status": "ok"}
            crows: list[dict] = []
            ndocs: list[dict] = []
            try:
                phrases = [str(p) for p in ncfg.get("phrases") or []]
                if use_llm and int(cfg["phrases_llm"]) > 0:
                    got = llm_phrases(ws, n, int(cfg["phrases_llm"]))
                    if got is None:
                        print(f"  !! {nid}: the LLM gave no chat phrases; hand phrases only")
                    phrases += got or []
                phrases = list(dict.fromkeys(p for p in phrases if p.strip()))
                frow["phrases"] = " | ".join(phrases)
                if not phrases:
                    fetch_out.append({**frow, "status": "no phrases"})
                    continue
                cands: dict[str, dict] = {}
                for q in phrases:
                    for c in gw.search_chats(q):
                        u = uname(c["username"])
                        if c.get("broadcast") or not c.get("megagroup") or u in cands:
                            continue
                        if int(c.get("members") or 0) >= int(cfg["min_members"]) or u in keep:
                            cands[u] = {**c, "phrase": q}
                ordered = sorted(cands.values(), key=lambda c: -int(c.get("members") or 0))
                shown = ordered[:int(cfg["check_candidates"])]
                shown += [c for c in ordered[int(cfg["check_candidates"]):] if uname(c["username"]) in keep]
                fit = {uname(c["username"]): ("yes", "") for c in shown}
                if use_llm and shown:
                    fit = chat_check(ws, n, shown)
                    if fit is None:
                        print(f"  !! {nid}: the LLM chat check gave no answer; re-run to retry")
                        fetch_out.append({**frow, "candidates": len(shown), "status": "check failed"})
                        continue
                for c in shown:
                    u = uname(c["username"])
                    f_, why = fit.get(u, ("no", "no answer"))
                    by = frow["by"]
                    if u in keep or u in drop:
                        f_, by = ("yes" if u in keep else "no"), "config"
                    crows.append({"niche_id": nid, "phrase": c["phrase"], "chat_id": c["id"], "username": c["username"], "title": c["title"],
                                  "members": c["members"], "fit": f_, "why": why, "by": by, "confirm": "", "confirm_why": "", "picked": 0,
                                  "messages": 0, "status": ""})
                # Second check: a title alone does not tell a trade's chat from one business's customer chat, so the largest
                # chats that passed are checked again with their own description (one call per chat, cached).
                if use_llm and cfg["confirm"]:
                    first = [r for r in crows if r["fit"] == "yes" and r["by"] != "config"][:2 * int(cfg["chats"])]
                    for r in first:
                        try:
                            r["about"] = gw.chat_about(r["username"]).get("about", "")
                        except telegram.ChatUnavailable as e:
                            r["about"], r["status"] = "", f"unavailable: {e}"[:120]
                    if first:
                        fit2 = chat_check(ws, n, first)
                        if fit2 is None:
                            print(f"  !! {nid}: the LLM confirm check gave no answer; re-run to retry")
                            fetch_out.append({**frow, "candidates": len(crows), "status": "check failed"})
                            continue
                        for r in first:
                            r["confirm"], r["confirm_why"] = fit2.get(uname(r["username"]), ("no", "no answer"))
                        for r in crows:
                            if r["fit"] == "yes" and r["by"] != "config" and r["confirm"] != "yes":
                                r["fit"] = "no"   # not confirmed, or beyond the confirmed window: not read
                relevant = [r for r in crows if r["fit"] == "yes"]
                terms = list(dict.fromkeys([*cfg["terms"], *(brand_terms([r for r in rows if r["niche_id"] == nid]) if cfg["brands"] else [])]))
                seen: set[tuple] = set()
                for ch in relevant[:int(cfg["chats"])]:
                    ch["picked"], ch["status"] = 1, "ok"
                    for term in terms:
                        try:
                            msgs = gw.search_messages(ch["username"], term, since, int(cfg["max_per_term"]))
                        except telegram.ChatUnavailable as e:
                            ch["status"] = f"unavailable: {e}"[:120]
                            break
                        for m in msgs:
                            key = (ch["chat_id"], m["id"])
                            if key in seen:
                                continue
                            seen.add(key)
                            ch["messages"] += 1
                            ndocs.append({"niche_id": nid, "chat_id": ch["chat_id"], "chat": ch["title"], "username": ch["username"],
                                          "members": ch["members"], "term": term, "id": m["id"], "date": m["date"],
                                          "reply": m.get("reply", 0), "fwd": m.get("fwd", 0), "text": m["text"][:1500]})
            except telegram.FloodStop as e:
                if not stopped:
                    stopped = str(e)
                    print(f"  !! {nid}: {e}; the remaining niches are read from the cache only")
                    gw.offline = True
                fetch_out.append({**frow, "status": "flood"})
                continue
            frow.update({"candidates": len(crows), "relevant": len(relevant), "picked": sum(r["picked"] for r in crows), "messages": len(ndocs)})
            if not frow["picked"]:
                frow["status"] = "no chats"
            fetch_out.append(frow)
            chats_out += crows
            docs_out += ndocs
            print(f"  {nid:36} phrases {len(phrases)} cand {frow['candidates']:>2} rel {frow['relevant']:>2} picked {frow['picked']} "
                  f"messages {frow['messages']:>4} {frow['status']} [live calls {gw.live}]", flush=True)
    finally:
        gw.close()
    # Earlier rows survive for the niches a FloodWait stopped and, in a run with --niches, for the other niches.
    old_fetch = read_rows(ws.out(FETCH))
    old_niches = {r.get("niche_id") for r in old_fetch}
    flood = {r["niche_id"] for r in fetch_out if r["status"] == "flood"}
    keep_old = (flood & old_niches) | (old_niches - set(ids) if only else set())
    write_merged(ws.out(DOCS), docs_out, keep_old)
    write_merged(ws.out(CHATS), chats_out, keep_old, CHAT_COLS)
    write_merged(ws.out(FETCH), [r for r in fetch_out if r["niche_id"] not in keep_old], keep_old, FETCH_COLS)
    st: dict[str, int] = {}
    for r in fetch_out:
        st[r["status"]] = st.get(r["status"], 0) + 1
    print(f"-> {DOCS}: {len(docs_out)} messages from {sum(r['picked'] for r in chats_out)} chats; niches {st}; {gw.live} live calls"
          + (f"; stopped: {stopped}" if stopped else ""))
