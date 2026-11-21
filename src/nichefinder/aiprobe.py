"""AI substitute probe: would a free chatbot answer replace the paid product?

All calls go through llm.chat_json (cached in data/cache/llm/, so re-runs are free). Per niche or topic:
  1. requests: the model writes N_REQUESTS different messages a buyer from the audience would type into a free
     chatbot, as the buyer (the person or business that has the job, not someone building the product). The niche
     fields describe a market, not a buyer's words: "I'm <who>, I need <task>" read as a founder's question.
  2. answer, per request: the model plays a free general-purpose chatbot and answers in one reply, showing a short
     example of whatever it can do right in the chat. It is told the abilities of today's free chatbots (photos,
     files, image generation and editing, web search; no background work, reminders, shared records, payments,
     audio or video), because the API model is text-only and would otherwise answer "I cannot see your photo" for
     jobs that free ChatGPT or Gemini do (solving a photographed problem, trying a haircut on a selfie).
  3. judge, per request: a separate call rates, with a rubric per product type, how much of the paid product's job
     the answer and a follow-up chat deliver for free, and lists what the answer recommends.
The rating is the median over the requests (median_low on an even count); `votes` keeps all of them, so a split
such as 1/2/2 shows a borderline case.

Judge fields (can_do and missing come first in the JSON, so the rating follows from them):
  can_do   the parts of the job a free chatbot can do itself, in this reply or a follow-up (short English phrases)
  missing  what the chat cannot give (short English phrases)
  covers   0 = the chat only advises, the job needs a product; 1 = partial (a one-off or simpler version, or the
           content without what people actually pay for); 2 = the chat delivers the outcome the product sells
  reason   one English sentence
  brands   products and services the answer recommends, in order of first mention
  diy      none | chatbot | generic_tool: the answer itself suggests doing the job in an AI chat, or with a generic
           tool (spreadsheet, notes, calendar), instead of a dedicated product

The same model writes, answers and judges, so the rating is a screening signal for a human call (G3 platform risk,
the info flag I:ai-answers), never a verdict on its own.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

from nichefinder import llm
from nichefinder.workspace import Workspace

N_REQUESTS = 3
LANG_NAMES = {"en": "English", "ru": "Russian"}

REQUEST_SYSTEM = ("You write realistic messages that people type into free AI chatbots. "
                  "Output only a JSON object {\"requests\": [\"...\", ...]}.")

ANSWER_SYSTEM = ("You are a helpful general-purpose AI assistant, like the free versions of ChatGPT, Gemini, DeepSeek or "
                 "Alice. Like them, you can read photos and files the user attaches (text, handwriting, formulas, "
                 "objects, plants, animals), generate images, edit the user's own photos and search the web; you "
                 "cannot run in the background, send reminders, keep records shared with other people, take payments "
                 "or produce audio or video. When a request involves a photo or a file, assume the user attaches it "
                 "and do with it what you can; never say you cannot see or edit images, because here you can. "
                 "Answer the user's request as well as you can in a single reply, in the language of the request. "
                 "Recommend specific products or services when that genuinely helps. If part of the job is something "
                 "you can do right here in the chat (write, plan, calculate, generate, solve, identify from a photo), "
                 "say so and show a short example of it. "
                 "Output a JSON object {\"answer\": \"<your full reply, markdown allowed>\"}.")

JUDGE_SYSTEM = ("You are a rigorous market analyst. A buyer typed a request into a free general-purpose AI chatbot. "
                "You get the niche, the paid product sold in it, the request and the chatbot's answer. Decide how much "
                "of what the buyer would pay for this answer, and a follow-up chat with the same chatbot, deliver for "
                "free. Judge the job, not only this reply: free chatbots today accept photos, files and voice (they "
                "read text, handwriting and formulas from a photo and recognise objects, plants and animals), generate "
                "images and edit photos of people and things, browse the web and keep the chat history, but they do "
                "not run in the background, "
                "produce audio or video files, send reminders or "
                "notifications, keep shared records for several users or customers, take payments or connect to other "
                "systems. The chatbot in the transcript is a text-only stand-in for these products and may understate "
                "them (for example, say it cannot see or edit a photo): judge by what free chatbots can do. Advice "
                "about how to do the job is not the job done. Count only what this audience actually "
                "pays for; conveniences every app has (a nicer interface, a saved history, a dedicated app) do not "
                "lower the rating.\n\n")

SOFTWARE_RUBRIC = (
    "The product is software that people pay for. Rate covers:\n"
    "2 = the chat itself delivers the outcome the product sells, and most of this audience would not need to pay "
    "(the job is to produce a text, a plan, an answer, a calculation, a solution or an identification, and the chat "
    "does it); also 2 when the answer's own best recommendation is to do the job in a free chatbot and that works;\n"
    "1 = the chat does a part of the job itself well enough that some of this audience would use it instead of "
    "paying (a one-off, manual or simpler version), but the core of what most people pay for in this niche still "
    "needs a product, such as keeping records over time, automation and reminders, integrations and payments, "
    "several users, live or local data, device features or compliance;\n"
    "0 = the chat can only advise, or what it can do itself is not what people pay for here: recommending products, "
    "comparing vendors, buying checklists, generic tips and templates nobody would use instead of the product are "
    "advice.\n")

INFO_RUBRIC = (
    "The product is a paid micro info product (a guide, a checklist, a template, a mini-course) sold through short "
    "video and a Telegram channel. Rate covers:\n"
    "2 = the answer, with a follow-up or two, gives what the product sells: the knowledge, the steps, the checklist "
    "or the template; a buyer gets an equivalent for free;\n"
    "1 = the chat gives much of the content, but the product's value rests largely on what a chat lacks: video "
    "demonstration of a physical technique, a tested sequence from a trusted author, ready-made designed or "
    "printable materials, accountability, a community;\n"
    "0 = the product's value is mostly what a chat cannot give; the text answer barely helps with the job.\n")

JUDGE_FIELDS = (
    "\nReturn strict JSON with fields, in this order: can_do (list of up to 5 short English phrases: the parts of the "
    "buyer's job a free chatbot can do itself, in this reply or a follow-up chat; empty list if none); missing (list "
    "of up to 5 short English phrases: what the buyer still needs that the chat cannot give); covers (0, 1 or 2, "
    "following from can_do and missing); reason (one English sentence); brands (list of the specific "
    "products, apps, services or websites the answer recommends, in order of first mention, names only, no generic "
    "categories); diy (one of: none, chatbot = the answer suggests doing the job with an AI chatbot, generic_tool = "
    "it suggests a generic tool such as a spreadsheet, notes or a calendar instead of a dedicated product).")

DIY = ("none", "chatbot", "generic_tool")
MAX_ANSWER_CHARS = 6000


def _add_usage(total: dict, use: dict | None, cached: bool) -> None:
    if use and not cached:
        total["in"] = total.get("in", 0) + int(use.get("prompt_tokens", 0) or 0)
        total["out"] = total.get("out", 0) + int(use.get("completion_tokens", 0) or 0)


def normalize(judged: dict) -> dict:
    """Clamp and clean the judge's JSON."""
    try:
        covers = int(judged.get("covers"))
    except (TypeError, ValueError):
        covers = None
    if covers is not None and not 0 <= covers <= 2:
        covers = None
    brands, seen = [], set()
    for b in judged.get("brands") or []:
        name = re.sub(r"\s+", " ", str(b)).strip()[:60]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            brands.append(name)

    def phrases(key: str) -> list[str]:
        return [re.sub(r"\s+", " ", str(m)).strip()[:80] for m in (judged.get(key) or []) if str(m).strip()][:5]

    diy = judged.get("diy") if judged.get("diy") in DIY else "none"
    return {"covers": covers, "can_do": phrases("can_do"), "missing": phrases("missing"),
            "reason": str(judged.get("reason") or "").strip()[:300], "brands": brands[:15], "diy": diy}


def buyer_requests(ws: Workspace, context: str, lang: str, usage: dict, n: int = N_REQUESTS) -> list[str]:
    user = (f"{context}\n\nWrite {n} different messages that a typical buyer from this audience would type into a free "
            "AI chatbot (ChatGPT, DeepSeek, Alice) when they need this job done. Write as the buyer: the person or "
            "business that has the job, never someone building, selling or marketing a product. Vary them: one short "
            "and casual, one with a sentence about their situation, one asking directly for help or a recommendation. "
            f"Language: {LANG_NAMES.get(lang, lang)}.")
    r, cached, use = llm.chat_json(ws, [{"role": "system", "content": REQUEST_SYSTEM}, {"role": "user", "content": user}],
                                   max_tokens=600, temperature=0.7)
    _add_usage(usage, use, cached)
    return [str(x).strip() for x in (r or {}).get("requests") or [] if str(x).strip()][:n]


def answer_and_judge(ws: Workspace, question: str, context: str, rubric: str, usage: dict) -> dict | None:
    """One request: answer it as a free chatbot, then judge the answer against `rubric`. None when a call fails."""
    a, cached, use = llm.chat_json(ws, [{"role": "system", "content": ANSWER_SYSTEM},
                                        {"role": "user", "content": question}], max_tokens=2500, temperature=0.3)
    _add_usage(usage, use, cached)
    answer = str((a or {}).get("answer") or "").strip()
    if not answer:
        return None
    user = (f"{context}\n\nThe buyer asked the chatbot:\n{question}\n\n"
            f"The chatbot answered:\n<<<\n{answer[:MAX_ANSWER_CHARS]}\n>>>")
    j, cached, use = llm.chat_json(ws, [{"role": "system", "content": JUDGE_SYSTEM + rubric + JUDGE_FIELDS},
                                        {"role": "user", "content": user}], max_tokens=800)
    _add_usage(usage, use, cached)
    if not j:
        return None
    return {"question": question, "answer": answer, **normalize(j)}


def aggregate(runs: list[dict]) -> dict:
    """Median rating over the runs; the text fields come from the first run at the median; brands by how many answers
    name them, then first mention."""
    rated = [r for r in runs if r.get("covers") is not None]
    if not rated:
        return {"covers": None, "votes": [], "can_do": [], "missing": [], "reason": "", "brands": [], "diy": "none"}
    med = statistics.median_low(r["covers"] for r in rated)
    at = next(r for r in rated if r["covers"] == med)
    count, first = Counter(), {}
    for r in rated:
        for b in r.get("brands") or []:
            count[b.lower()] += 1
            first.setdefault(b.lower(), (len(first), b))
    brands = [first[k][1] for k in sorted(count, key=lambda k: (-count[k], first[k][0]))]
    diy = Counter(r.get("diy", "none") for r in rated).most_common(1)[0][0]
    return {"covers": med, "votes": [r["covers"] for r in rated], "can_do": at.get("can_do", []),
            "missing": at.get("missing", []), "reason": at.get("reason", ""), "brands": brands[:15], "diy": diy}


def probe(ws: Workspace, context: str, rubric: str, lang: str = "en") -> dict | None:
    """Buyer requests -> answer and judge each -> median. Returns the aggregate plus `runs` and `usage`;
    None when no request could be written or answered."""
    usage: dict = {}
    qs = buyer_requests(ws, context, lang, usage)
    runs = [r for r in (answer_and_judge(ws, q, context, rubric, usage) for q in qs) if r]
    if not runs:
        return None
    return {**aggregate(runs), "runs": runs, "usage": usage}


def _names(s: str) -> list[str]:
    """'Google Travel / ChatGPT (platform)' -> ['google travel', 'chatgpt']."""
    s = re.sub(r"\([^)]*\)", "", str(s)).lower()
    return [p.strip() for p in re.split(r"[/,+]", s) if len(p.strip()) >= 3]


def listed_named(brands: list[str], competitors: list[str]) -> list[str]:
    """The niche's listed competitors (niches.yaml) that the answers name; a match is a substring either way."""
    named = [n for b in brands for n in _names(b)]
    out = []
    for c in competitors or []:
        if any(cn in n or n in cn for cn in _names(c) for n in named) and c not in out:
            out.append(c)
    return out


def votes_text(votes: list[int]) -> str:
    return "/".join(str(v) for v in votes)
