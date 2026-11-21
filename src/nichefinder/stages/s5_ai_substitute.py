"""AI substitute probe for software niches: does a free chatbot answer replace the product?

Per niche (nichefinder/aiprobe.py): the LLM writes three messages a buyer from the niche's audience would type into a
free chatbot (from niches.yaml `who`, `task`, `product`; English, Russian for niches without English queries), answers
each as a free chatbot, and a separate judge call rates each answer: covers 0-2 (2 = the chat delivers the outcome the
product sells, 1 = a real but partial or one-off part of the job, 0 = advice only), what the chat can and cannot do,
the brands it recommends and whether it suggests doing the job in a chat or a generic tool. The niche gets the median
rating; `votes` keeps all three, so 1/2/2 marks a borderline case.

It is evidence for the manual G3 `platform_risk` in config/overrides.yaml, never a gate: `check` marks the niches
where the probe rates the chatbot above the manual call (covers 2: review G3; covers 1 against 0: consider P1), for
a human to look at. One direction only: the probe tests general chatbots, so it cannot refute a platform risk that
comes from an OS feature or a vendor's own service. The same model writes, answers and judges, so read the answers (ai_substitute_answers.jsonl) before
changing a manual call.

Niches: the shortlist (default), --all for every niche, --niches a,b for a list. Seven LLM calls per niche, run in
--workers parallel threads and cached in data/cache/llm/, so a re-run is free; --dry lists the niches, no calls.
Output: data/out/ai_substitute.csv, data/out/ai_substitute_answers.jsonl, reports/S5-ai-substitute.md.
Keys: LLM_API_KEY (LLM_BASE_URL, LLM_MODEL as in llm.py).
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from nichefinder import aiprobe, llm, niches as nf_niches
from nichefinder.workspace import Workspace

SUMMARY = "AI substitute probe: does a free chatbot answer replace the product (evidence for G3, not a gate)"
KEYS: tuple[str, ...] = ("LLM_API_KEY",)
NEEDS: tuple[str, ...] = ()

COLS = ["niche_id", "name", "side", "covers", "votes", "platform_risk", "check", "diy", "n_brands", "brands",
        "listed_named", "listed_total", "can_do", "missing", "reason"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="probe every niche, not only the shortlist")
    parser.add_argument("--niches", default="", help="comma-separated niche ids (overrides the shortlist and --all)")
    parser.add_argument("--workers", type=int, default=6, help="parallel niches (default 6)")
    parser.add_argument("--dry", action="store_true", help="list the niches to probe; no LLM calls")


def context(niche: dict) -> str:
    return (f"Niche: {niche.get('name', niche['id'])}\nWho has the job: {niche.get('who', '')}\n"
            f"The job: {niche.get('task', '')}\nPaid product sold in this niche: {niche.get('product', '')}")


def check(covers: int | None, platform_risk) -> str:
    """Where the probe rates the chatbot above the manual G3 call; empty otherwise or when either is missing.
    One direction only: the probe tests general chatbots, so a low rating cannot contradict a platform risk that
    comes from an OS feature or a vendor's own service."""
    try:
        pr = int(platform_risk)
    except (TypeError, ValueError):
        return ""
    if covers is None or covers <= pr:
        return ""
    if covers == 2:
        return "review G3: a free chatbot delivers the outcome; consider platform risk 2"
    return "consider P1: a free chatbot does part of the job for some buyers; consider platform risk 1"


def pick(ws: Workspace, args: argparse.Namespace, all_niches: list[dict]) -> list[dict]:
    by_id = {n["id"]: n for n in all_niches}
    if args.niches:
        ids = [x.strip() for x in args.niches.split(",") if x.strip()]
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise SystemExit(f"unknown niche id(s): {', '.join(unknown)}")
    elif args.all:
        ids = list(by_id)
    else:
        ids = [i for i in nf_niches.shortlist_ids(ws) if i in by_id]
    return [by_id[i] for i in ids]


def row(niche: dict, res: dict | None, platform_risk) -> dict:
    base = {"niche_id": niche["id"], "name": niche.get("name", ""), "side": niche.get("side", ""),
            "platform_risk": platform_risk, "listed_total": len(niche.get("competitors") or [])}
    if res is None:
        return {**base, "covers": "", "votes": "", "check": "", "diy": "", "n_brands": 0, "brands": "",
                "listed_named": 0, "can_do": "", "missing": "", "reason": "LLM calls failed"}
    named = aiprobe.listed_named(res["brands"], niche.get("competitors") or [])
    return {**base, "covers": "" if res["covers"] is None else res["covers"], "votes": aiprobe.votes_text(res["votes"]),
            "check": check(res["covers"], platform_risk), "diy": res["diy"], "n_brands": len(res["brands"]),
            "brands": " | ".join(res["brands"]), "listed_named": len(named), "can_do": "; ".join(res["can_do"]),
            "missing": "; ".join(res["missing"]), "reason": res["reason"]}


def report(ws: Workspace, rows: list[dict], model: str) -> str:
    dist = Counter(r["covers"] for r in rows)
    split = sum(1 for r in rows if len(set(r["votes"].split("/"))) > 1)
    lines = ["# S5 AI substitute: does a free chatbot answer replace the product?", "",
             f"Run {ws.today}; model `{model}` writes the buyer requests, plays the free chatbot and, in a separate "
             f"call, judges; {len(rows)} niches, {aiprobe.N_REQUESTS} buyer requests each.", "",
             "covers: 2 = the chat delivers the outcome the product sells; 1 = the chat does a real part of the job "
             "(a one-off, simpler or manual version), the paid core still needs a product; 0 = the chat only advises. "
             "The niche's rating is the median over its requests; votes lists them all. Rubric and prompts: "
             "`nichefinder/aiprobe.py`.", "",
             "> Evidence for the manual G3 platform risk (`config/overrides.yaml`), not a gate and not part of the score. "
             "The same model writes, answers and judges: read the answers (`data/out/ai_substitute_answers.jsonl`) "
             "before changing a manual call.", "",
             f"Distribution: covers 2 - {dist.get(2, 0)}, 1 - {dist.get(1, 0)}, 0 - {dist.get(0, 0)}"
             + (f", not rated - {dist.get('', 0)}" if dist.get("", 0) else "") + f". Split votes: {split}."]
    for prefix, title in (("review G3", "The chatbot delivers the outcome, the manual platform risk is lower"),
                          ("consider P1", "The chatbot does part of the job, the manual platform risk is 0")):
        flagged = [r for r in rows if r["check"].startswith(prefix)]
        if flagged:
            lines += ["", f"## {title}", "",
                      "| niche | covers | votes | platform risk | reason |", "|---|---|---|---|---|"]
            lines += [f"| {r['niche_id']} | {r['covers']} | {r['votes']} | {r['platform_risk']} | {r['reason']} |"
                      for r in flagged]
    lines += ["", "The comparison runs one way: the probe tests general chatbots only, so a manual platform risk "
              "from an OS feature or a vendor's own service is outside what it can confirm or refute."]
    lines += ["", "## All niches", "",
              "| niche | covers | votes | platform risk | DIY route | listed competitors named | the chat can do | "
              "still needs a product for | brands the chatbot recommends |",
              "|---|---|---|---|---|---|---|---|---|"]
    order = sorted(rows, key=lambda r: (-(r["covers"] if r["covers"] != "" else -1), r["niche_id"]))
    for r in order:
        lines.append(f"| {r['niche_id']} | {r['covers']} | {r['votes']} | {r['platform_risk']} | {r['diy']} | "
                     f"{r['listed_named']}/{r['listed_total']} | {r['can_do'][:120]} | {r['missing'][:120]} | "
                     f"{r['brands'][:120]} |")
    return "\n".join(lines) + "\n"


def run(ws: Workspace, args: argparse.Namespace) -> None:
    all_niches, queries = nf_niches.load(ws)
    todo = pick(ws, args, all_niches)
    print(f"niches to probe: {len(todo)} ({1 + 2 * aiprobe.N_REQUESTS} LLM calls each, cached)")
    if args.dry:
        for n in todo:
            print(f"  {n['id']}")
        return
    manual = nf_niches.overrides(ws)

    def one(n: dict):
        lang = "en" if (queries.get(n["id"]) or {}).get("en") else "ru"
        return n, aiprobe.probe(ws, context(n), aiprobe.SOFTWARE_RUBRIC, lang)

    rows, answers, usage = [], [], Counter()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for n, res in pool.map(one, todo):
            pr = (manual.get(n["id"]) or {}).get("platform_risk", "")
            r = row(n, res, pr)
            rows.append(r)
            if res is not None:
                usage.update(res.pop("usage", {}))
                answers.append({"niche_id": n["id"], **res})
            print(f"  {n['id']:40} covers {r['covers'] if r['covers'] != '' else '-'} ({r['votes'] or '-'})  "
                  f"platform_risk {pr if pr != '' else '-'}  {r['diy'] or '-':12} brands {r['n_brands']}")
    with open(ws.out("ai_substitute.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("ai_substitute_answers.jsonl"), "w", encoding="utf-8") as fh:
        for a in answers:
            fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    path = ws.report("S5-ai-substitute.md")
    path.write_text(report(ws, rows, llm.config(ws)["model"]), encoding="utf-8")
    if usage:
        print(f"tokens (uncached): in {usage['in']:,}, out {usage['out']:,}")
    print("->", ws.out("ai_substitute.csv"), "and", path)
