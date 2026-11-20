"""The topic universe of the info cohort from demand data: what Russian search asks to learn or fix, ranked by volume.

Seeded topics reflect the researcher's guesses. This stage starts from intent words that name no topic at all
("online courses", "learning", "how", "what to do if", "how to get rid of"...: config/info_discover.yaml `stems`) and
lets the data say which subjects carry the demand:

1. Wordstat top requests for every stem (up to 2,000 phrases each, last 30 days, broad match).
2. Phrases with at least `min_count` impressions are sorted by an LLM, in order of volume and in batches, into
   kind L (learn a skill or subject), F (fix a lasting personal problem or improve body, mind, money, relationships,
   career, home), M (wants a ready-made material: template, plan, pattern, worksheet) or O (everything a micro info
   product cannot sell to: navigation, brands, news, currency rates, spelling look-ups, device troubleshooting,
   one-off household fixes, medical symptoms, games and series, goods, local services, free state procedures).
   L/F/M phrases get a topic (the subject in 1-3 Russian words) and an area. Batches run in sequence and each one
   sees the topics named so far, so one subject keeps one label.
3. Topic demand = the sum of its phrases' impressions without nested phrases: a phrase whose words contain all
   words of another phrase of the same topic is already inside that phrase's broad-match count. Overlap between
   different head phrases stays, so the demand is an upper estimate that ranks topics, not a market size.

Output: data/out/info_discover_phrases.csv (phrase, count, stems, kind, topic, area), data/out/info_discover.csv
(topic ranking), reports/info_discover.md. With --write-topics N the top N topics replace the topics of
config/info_topics.yaml (the previous list is kept in config/info_topics.previous.yaml). The YouTube phrase is the
topic itself (the subject in 1-3 words, the cohort's phrase rule); `must` is built from the stems of the topic's words
plus the model's stems with generic ones removed (the model alone proposed "lesson", "beginner", "master class" and
2-letter stems such as "bo" for guitar); who / task / product are the model's hypotheses, to be checked by a human.

Keys: YANDEX_API_KEY (Wordstat, about 100 requests per hour; one per stem), LLM_API_KEY. Cache: data/cache/wordstat/,
data/cache/llm/; a re-run with the same stems, threshold and model costs nothing.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import yaml

from nichefinder import info, llm
from nichefinder.sources import wordstat
from nichefinder.workspace import Workspace

SUMMARY = "Topic universe of the info cohort from Wordstat demand (intent stems -> LLM topics -> ranking)"
KEYS: tuple[str, ...] = ("YANDEX_API_KEY", "LLM_API_KEY")
NEEDS: tuple[str, ...] = ()

CONFIG = "info_discover.yaml"
DEFAULTS = {"stems": [], "num_phrases": 2000, "min_count": 3000, "batch": 250, "top_n": 60, "report_n": 150}
AREAS = {
    "fin": "money, saving, investing, debts", "biz": "business, freelancing, career, sales, marketing",
    "it": "IT and digital skills, programming, design, AI tools", "lang": "foreign languages",
    "school": "school subjects and exams", "health": "fitness, weight, sleep, healthy habits (not treatment)",
    "food": "cooking and nutrition", "beauty": "beauty, style, hair, nails, makeup",
    "psy": "psychology, emotions, self-development", "rel": "relationships, dating, sex, family",
    "kids": "parenting and child development", "home": "home, cleaning, repair, garden",
    "craft": "crafts, art, music, hobbies", "auto": "driving and cars", "pets": "pets",
    "law": "law, documents, taxes", "travel": "travel and relocation", "other": "anything else",
}
KINDS = {"L": "learn", "F": "fix", "M": "material"}
# Intent and format words are never a subject (on the first run the model made "learning" and "master class" topics).
INTENT_WORDS = {"обучение", "курсы", "курс", "онлайн курсы", "уроки", "урок", "мастер класс", "мастер классы", "гайд",
                "марафон", "для начинающих", "с нуля", "научиться", "как", "тренинг", "вебинар"}

CLASSIFY = """You sort Russian search queries for a researcher who sells micro info products (a guide, checklist,
template, workbook or mini course for 300-3000 RUB) through short videos and a Telegram channel.

For each numbered query choose a kind:
L - wants to learn a skill or a subject;
F - wants to solve a lasting personal problem or improve body, mind, money, relationships, career or home;
M - wants a ready-made material: a template, plan, pattern, worksheet, lesson plan, menu, schedule;
O - anything else: navigation, brands and sites, news, currency rates and prices, spelling and grammar look-ups,
translations and dictionary look-ups ("how is X in English"), device or software troubleshooting, one-off look-ups
that a free answer settles (one recipe, one conversion, how one thing works), one-off household fixes (a smell, pests,
a stain), medical symptoms and treatment, games, films, series and anime, shopping for goods, local services,
procedures the state answers for free, adult content, school pages and homework of a grade ("lesson 2", "2nd grade
lessons", "topic of the lesson"), pedagogy terms ("teaching methods"), and every query that names no subject
("how to improve", "how to raise", "how to learn", "how to do"): a query without a subject is always O.

For L, F and M also give:
topic - the subject in Russian, 1-3 lower-case words, as people name it (for example: english language -> "английский
язык", crochet -> "вязание крючком", anxiety -> "тревожность", weight loss -> "похудение"). The topic is never an
intent or format word (обучение, курсы, уроки, мастер класс, гайд, марафон, для начинающих, с нуля) and never a
catch-all for vague queries. Lesson plans and worksheets that teachers look for are M with the topic "материалы для
учителей". Reuse a known topic whenever the subject is the same; name a new topic only for a different subject.
area - one code: {areas}.

Known topics so far: {known}

Return JSON {{"r": [[index, kind, topic, area], ...]}} with one item per query; for kind O return [index, "O"]."""

PROPOSE = """For each Russian topic below (demand from Russian search, with example queries) propose, for a researcher
who sells micro info products through short videos and a Telegram channel:
yt - a YouTube search phrase in Russian that names the subject in 1-3 words (no how-to tails, no "курсы");
must - a lower-case regex of Russian word stems (3+ letters, alternatives with |, no lookarounds, no anchors) that the
title or description of a video on this subject would contain;
who - who searches (Russian, under 8 words); task - what they want (Russian, under 10 words);
product - one micro info product with a price in RUB (Russian, under 12 words; a hypothesis).
Topics: {topics}
Return JSON {{"t": [{{"topic": ..., "yt": ..., "must": ..., "who": ..., "task": ..., "product": ...}}, ...]}}."""


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--write-topics", type=int, nargs="?", const=-1, default=0, metavar="N",
                   help="replace the topics of config/info_topics.yaml with the top N discovered topics "
                        "(N defaults to top_n in config/info_discover.yaml)")


def settings(ws: Workspace) -> dict:
    return {**DEFAULTS, **(ws.load_config(CONFIG, {}) or {})}


def collect(ws: Workspace, cfg: dict) -> dict[str, dict]:
    """phrase -> {count, stems} from Wordstat top requests of every stem."""
    phrases: dict[str, dict] = {}
    for stem in cfg["stems"]:
        res, hit = wordstat.top_requests(ws, stem, int(cfg["num_phrases"]), log=print)
        if "_error" in res:
            print(f"  ! {stem}: {res}", flush=True)
            continue
        rows = res.get("results", [])
        for x in rows:
            p = " ".join(str(x["phrase"]).lower().split())
            d = phrases.setdefault(p, {"count": 0, "stems": []})
            d["count"] = max(d["count"], int(x.get("count", 0)))
            d["stems"].append(stem)
        print(f"  {stem:22} {len(rows):>5} phrases{' (cache)' if hit else ''}", flush=True)
    return phrases


def classify(ws: Workspace, items: list[tuple[str, int]], batch: int,
             stems: list[str] = ()) -> dict[str, tuple[str, str, str]]:
    """phrase -> (kind, topic, area), in order of volume, with the running list of known topics. A topic that is an
    intent word (a stem, or one of INTENT_WORDS) is not a subject: the phrase becomes O whatever the model said."""
    intent_words = {s.lower() for s in stems} | INTENT_WORDS
    known: dict[str, int] = {}
    out: dict[str, tuple[str, str, str]] = {}
    areas = "; ".join(f"{k} ({v})" for k, v in AREAS.items())
    for start in range(0, len(items), batch):
        chunk = items[start:start + batch]
        prompt = CLASSIFY.format(areas=areas, known=", ".join(sorted(known)) or "none yet")
        user = "\n".join(f"{i}. {p}" for i, (p, _) in enumerate(chunk))
        res, hit, _ = llm.chat_json(ws, [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                                    max_tokens=8000, cache_namespace="llm_info_discover")
        got = 0
        for r in (res or {}).get("r", []):
            try:
                idx = int(r[0])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if not 0 <= idx < len(chunk):
                continue
            phrase = chunk[idx][0]
            kind = str(r[1]).upper() if len(r) > 1 else "O"
            topic = " ".join(str(r[2]).lower().split()) if len(r) >= 3 else ""
            if kind in KINDS and len(r) >= 4 and topic and topic not in intent_words:
                area = str(r[3]) if str(r[3]) in AREAS else "other"
                out[phrase] = (kind, topic, area)
                known[topic] = known.get(topic, 0) + 1
            else:
                out[phrase] = ("O", "", "")
            got += 1
        print(f"  batch {start // batch + 1}/{(len(items) + batch - 1) // batch}: {got}/{len(chunk)} sorted, "
              f"{len(known)} topics{' (cache)' if hit else ''}", flush=True)
    return out


def demand(phrases: list[tuple[str, int]]) -> int:
    """Sum of impressions without nested phrases (broad match already counts a phrase inside its shorter parent)."""
    kept: list[frozenset] = []
    total = 0
    for p, c in sorted(phrases, key=lambda x: (len(x[0].split()), -x[1])):
        words = frozenset(p.split())
        if any(k <= words for k in kept):
            continue
        kept.append(words)
        total += c
    return total


def rank(rows: list[dict]) -> list[dict]:
    """Topic ranking from classified phrases."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r["kind"] in KINDS:
            by.setdefault(r["topic"], []).append(r)
    topics = []
    for t, rs in by.items():
        rs.sort(key=lambda r: -r["count"])
        areas: dict[str, int] = {}
        kinds: dict[str, int] = {}
        for r in rs:
            areas[r["area"]] = areas.get(r["area"], 0) + r["count"]
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + r["count"]
        total = sum(kinds.values())
        topics.append({
            "topic": t, "area": max(areas, key=areas.get), "demand": demand([(r["phrase"], r["count"]) for r in rs]),
            "head": rs[0]["count"], "n_phrases": len(rs),
            "learn": round(kinds.get("L", 0) / total, 2), "fix": round(kinds.get("F", 0) / total, 2),
            "material": round(kinds.get("M", 0) / total, 2),
            "examples": " | ".join(r["phrase"] for r in rs[:5]),
        })
    topics.sort(key=lambda x: -x["demand"])
    for i, t in enumerate(topics, 1):
        t["rank"] = i
    return topics


def propose(ws: Workspace, top: list[dict]) -> list[dict]:
    """YouTube phrase, must regex, who / task / product hypothesis for the selected topics."""
    out = []
    for start in range(0, len(top), 30):
        chunk = top[start:start + 30]
        listing = "; ".join(f"{t['topic']} ({t['examples'].split(' | ')[0]}, {t['examples'].split(' | ')[-1]})"
                            for t in chunk)
        res, _, _ = llm.chat_json(ws, [{"role": "user", "content": PROPOSE.format(topics=listing)}], max_tokens=8000,
                                  cache_namespace="llm_info_discover")
        got = {str(x.get("topic", "")).lower().strip(): x for x in (res or {}).get("t", []) if isinstance(x, dict)}
        for t in chunk:
            p = got.get(t["topic"], {})
            entry = {"id": slug(t["topic"], t["rank"]), "q": [t["topic"]]}
            must = build_must(t["topic"], str(p.get("must") or ""))
            if must:
                entry["must"] = must
            entry.update({"who": p.get("who", ""), "task": p.get("task", ""),
                          "product": (p.get("product") or "") + " (hypothesis)",
                          "demand": t["demand"], "area": t["area"], "source": "info_discover"})
            out.append(entry)
    return out


# Stems that match almost any video of a learning topic: on the first run the model's `must` regexes were full of them
# (lesson, beginner, learning, master class, online, course, from zero...), plus 2-letter stems that hide inside words.
GENERIC_STEMS = {"урок", "урока", "уроки", "начинающ", "начин", "обучен", "обуч", "мастер", "мастер.класс", "онлайн",
                 "курс", "нуля", "правил", "дет", "научит", "практик", "жизн", "техник", "пошагов", "своими", "школ",
                 "школьник", "задач", "специалист", "язык", "программ", "видео", "фото", "домашн", "собой", "материал",
                 "изучен", "основ", "простой", "легко", "быстро",
                 # short stems that hide inside unrelated words (the stem of "law" inside "correctly", "weight" inside
                 # "spring", "auto" inside "author", "code" inside "promo code", "first") and verbs that fit any how-to
                 "прав", "вес", "авто", "код", "перв", "нот", "слов", "игра", "труд", "избав", "справит", "улучш",
                 "думать", "открыт", "помощ"}
# Words of a topic label that do not name the subject; every other word of the label is the subject and stays.
TOPIC_SKIP = {"обучение", "материалы", "язык", "языки", "для", "и", "по", "с", "основы"}


def word_stem(w: str) -> str:
    """A crude Russian stem: words of 6+ letters lose their last 3 letters (5-6 letters kept), shorter words stay whole;
    words of up to 3 letters are bounded so that they do not match inside other words."""
    if len(w) <= 3:
        return rf"\b{re.escape(w)}\b"
    if len(w) <= 5:
        return re.escape(w)
    return re.escape(w[:min(6, max(5, len(w) - 3))])


def build_must(topic: str, proposed: str) -> str:
    """`must` = stems of the topic's own words (minus TOPIC_SKIP) + the model's stems minus generic stems and stems
    under 3 letters. The generic list applies to the model's stems only: a topic word is the subject itself."""
    alts: list[str] = []
    for w in topic.lower().split():
        if len(w) >= 2 and w not in TOPIC_SKIP:
            alts.append(word_stem(w))
    for a in proposed.lower().split("|"):
        a = a.strip()
        if len(a) >= 3 and a not in GENERIC_STEMS and not any(a.startswith(g) for g in GENERIC_STEMS):
            alts.append(a)
    out = "|".join(dict.fromkeys(a for a in alts if a))
    try:
        re.compile(out)
    except re.error:
        return "|".join(dict.fromkeys(word_stem(w) for w in topic.lower().split() if len(w) >= 2))
    return out


TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                     "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(topic: str, rank_: int) -> str:
    s = "".join(TRANSLIT.get(ch, ch) for ch in topic.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-")
    return s or f"topic-{rank_}"


def write_topics(ws: Workspace, entries: list[dict]) -> Path:
    path = ws.config(info.TOPICS_FILE)
    text = path.read_text(encoding="utf-8") if path.is_file() else "_settings: {}\n"
    head = text[:text.index("\ntopics:") + 1] if "\ntopics:" in text else text.rstrip("\n") + "\n"
    if "\ntopics:" in text:
        ws.config("info_topics.previous.yaml").write_text(text, encoding="utf-8")
    seen: set[str] = set()
    for e in entries:
        base, k = e["id"], 2
        while e["id"] in seen:
            e["id"] = f"{base}-{k}"
            k += 1
        seen.add(e["id"])
    body = yaml.safe_dump({"topics": entries}, allow_unicode=True, sort_keys=False, width=200)
    path.write_text(head + "# Written by info_discover --write-topics: the top topics by demand. Check `q` and `must` "
                    "against the example videos in reports/info.md.\n" + body, encoding="utf-8")
    return path


def report(ws: Workspace, cfg: dict, topics: list[dict], n_phrases: int, n_sorted: int, kinds: dict) -> Path:
    lines = ["# Info topics by demand (Wordstat)", "",
             f"Run {ws.today}. Stems (no topic words): {', '.join(cfg['stems'])}. {n_phrases} unique phrases, "
             f"{n_sorted} with at least {cfg['min_count']} impressions sorted by an LLM: "
             + ", ".join(f"{KINDS.get(k, 'other')} {v}" for k, v in sorted(kinds.items())) + ".",
             "", "Demand is the sum of a topic's phrases without nested ones (impressions per month, broad match): an "
             "upper estimate for ranking, not a market size.", "",
             "| # | topic | area | demand | head phrase | phrases | learn / fix / material | examples |",
             "|---|---|---|---|---|---|---|---|"]
    for t in topics[:cfg["report_n"]]:
        lines.append(f"| {t['rank']} | {t['topic']} | {t['area']} | {t['demand']:,} | {t['head']:,} | {t['n_phrases']} | "
                     f"{t['learn']:.0%} / {t['fix']:.0%} / {t['material']:.0%} | {t['examples']} |")
    path = ws.report("info_discover.md")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = settings(ws)
    if not cfg["stems"]:
        print("  no stems in config/info_discover.yaml: nothing to discover")
        return
    phrases = collect(ws, cfg)
    items = sorted(((p, d["count"]) for p, d in phrases.items() if d["count"] >= int(cfg["min_count"])),
                   key=lambda x: (-x[1], x[0]))
    print(f"  {len(phrases)} unique phrases, {len(items)} with >= {cfg['min_count']} impressions", flush=True)
    sorted_ = classify(ws, items, int(cfg["batch"]), cfg["stems"])
    rows = []
    kinds: dict[str, int] = {}
    for p, c in items:
        kind, topic, area = sorted_.get(p, ("O", "", ""))
        kinds[kind] = kinds.get(kind, 0) + 1
        rows.append({"phrase": p, "count": c, "stems": "; ".join(phrases[p]["stems"]), "kind": kind, "topic": topic,
                     "area": area})
    with open(ws.out("info_discover_phrases.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["phrase", "count", "stems", "kind", "topic", "area"])
        w.writeheader()
        w.writerows(rows)
    topics = rank(rows)
    cols = ["rank", "topic", "area", "demand", "head", "n_phrases", "learn", "fix", "material", "examples"]
    with open(ws.out("info_discover.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(topics)
    path = report(ws, cfg, topics, len(phrases), len(items), kinds)
    for t in topics[:25]:
        print(f"  {t['rank']:>3} {t['topic']:28} {t['area']:7} {t['demand']:>10,}  {t['examples'][:70]}")
    print(f"-> {ws.out('info_discover.csv')} ({len(topics)} topics), {path}")
    n = int(getattr(args, "write_topics", 0) or 0)
    if n < 0:
        n = int(cfg["top_n"])
    if n:
        entries = propose(ws, topics[:n])
        out = write_topics(ws, entries)
        print(f"-> {out}: {len(entries)} topics (previous list in config/info_topics.previous.yaml)")
    else:
        print("  next: nf run info_discover -- --write-topics N, then info_youtube and info_score")
