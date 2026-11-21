"""AI substitute probe for info topics: does a free chatbot answer replace the paid micro product?

Per topic in config/info_topics.yaml (nichefinder/aiprobe.py): the LLM writes three messages a buyer from the topic's
audience would type into a free chatbot, in the cohort language (`_settings.lang`), answers each as a free chatbot,
and a separate judge call rates how much of the micro product (`product`) each answer gives away: covers 0-2
(INFO_RUBRIC), with what a chat cannot give (video demonstration, designed materials, a trusted author,
accountability, a community). The topic gets the median rating; `votes` keeps all three.

info_score shows the rating and raises the informational flag I:ai-answers at covers >= flags.ai_answers in
config/score_info.yaml (default 2). The flag never changes the score or the verdict: a topic the chatbot answers can
still sell, but the product has to offer what the chat lacks. The same model writes, answers and judges.

Seven LLM calls per topic in --workers parallel threads, cached in data/cache/llm/; --dry lists the topics, no calls.
Output: data/out/info_ai.csv, data/out/info_ai_answers.jsonl. Keys: LLM_API_KEY.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from nichefinder import aiprobe, info
from nichefinder.workspace import Workspace

SUMMARY = "AI substitute probe for info topics: does a free chatbot answer replace the micro product"
KEYS: tuple[str, ...] = ("LLM_API_KEY",)
NEEDS: tuple[str, ...] = ()

COLS = ["topic_id", "covers", "votes", "diy", "can_do", "missing", "reason", "brands"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--topics", default="", help="comma-separated topic ids (default: all topics)")
    parser.add_argument("--workers", type=int, default=6, help="parallel topics (default 6)")
    parser.add_argument("--dry", action="store_true", help="list the topics to probe; no LLM calls")


def context(topic: dict) -> str:
    return (f"Topic: {topic['id']} (search phrases: {', '.join(info.phrases(topic))})\n"
            f"Who has the job: {topic.get('who', '')}\nThe job: {topic.get('task', '')}\n"
            f"Paid micro product: {topic.get('product', '')}")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    settings, topics = info.load(ws)
    topics = [t for t in topics if t.get("id")]
    if not topics:
        print("  no topics in config/info_topics.yaml: nothing to probe")
        return
    wanted = {x.strip() for x in args.topics.split(",") if x.strip()}
    if wanted:
        topics = [t for t in topics if t["id"] in wanted]
    print(f"topics to probe: {len(topics)} ({1 + 2 * aiprobe.N_REQUESTS} LLM calls each, cached)")
    if args.dry:
        for t in topics:
            print(f"  {t['id']}")
        return

    def one(t: dict):
        return t, aiprobe.probe(ws, context(t), aiprobe.INFO_RUBRIC, settings["lang"])

    rows, answers, usage = [], [], Counter()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for t, res in pool.map(one, topics):
            if res is None:
                print(f"  {t['id']:36} LLM calls failed")
                continue
            usage.update(res.pop("usage", {}))
            rows.append({"topic_id": t["id"], "covers": "" if res["covers"] is None else res["covers"],
                         "votes": aiprobe.votes_text(res["votes"]), "diy": res["diy"],
                         "can_do": "; ".join(res["can_do"]), "missing": "; ".join(res["missing"]),
                         "reason": res["reason"], "brands": " | ".join(res["brands"])})
            answers.append({"topic_id": t["id"], **res})
            print(f"  {t['id']:36} covers {rows[-1]['covers']} ({rows[-1]['votes']})  {rows[-1]['missing'][:70]}")
    with open(ws.out("info_ai.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("info_ai_answers.jsonl"), "w", encoding="utf-8") as fh:
        for a in answers:
            fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    if usage:
        print(f"tokens (uncached): in {usage['in']:,}, out {usage['out']:,}")
    print("->", ws.out("info_ai.csv"), "(info_score shows it; flag I:ai-answers)")
