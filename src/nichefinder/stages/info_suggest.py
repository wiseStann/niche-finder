"""Topic ideas for the info cohort: YouTube autocomplete for the seed areas in config/info_topics.yaml.

Each seed is expanded into "seed" and "seed <letter>" for every letter of the alphabet of `lang`; YouTube autocomplete
returns up to 10 phrases for each. A phrase that comes back for many expansions is what people actually type into
YouTube search. The output is a human checkpoint, like the shortlist: pick the phrases that name a concrete task,
group them into topics (who x task x product) and add them to config/info_topics.yaml.

Input: config/info_topics.yaml (`_settings.seeds`, `lang`, `region`). Output: data/out/info_suggest.csv (seed, phrase,
hits = expansions that returned it, best_pos = best position in a suggestion list, in_topics = already a topic phrase).
Cache: data/cache/suggest/. Cost: free, no key; about 0.4 s per new request, about 30 requests per seed.
"""
from __future__ import annotations

import argparse
import csv

from nichefinder import info
from nichefinder.sources import suggest
from nichefinder.workspace import Workspace

SUMMARY = "Topic ideas for the info cohort from YouTube autocomplete (seed areas)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

ALPHABET = {
    "ru": "абвгдежзийклмнопрстуфхцчшщэюя",
    "en": "abcdefghijklmnopqrstuvwxyz",
}


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--seed", action="append", default=[], help="seed phrase (repeatable); overrides _settings.seeds")
    p.add_argument("--top", type=int, default=15, help="phrases per seed to print")


def expand(ws: Workspace, seed: str, lang: str, region: str) -> dict[str, dict]:
    """phrase -> {hits, best_pos} for one seed."""
    found: dict[str, dict] = {}
    letters = ALPHABET.get(lang, ALPHABET["en"])
    for q in [seed] + [f"{seed} {ch}" for ch in letters]:
        res = suggest.youtube(ws, q, hl=lang, gl=region.lower())
        if "_error" in res:
            print(f"  ! {q}: {res['_error']}", flush=True)
            continue
        for pos, phrase in enumerate(res.get("suggestions") or [], 1):
            phrase = " ".join(str(phrase).lower().split())
            if not phrase or phrase == seed.lower():
                continue
            d = found.setdefault(phrase, {"hits": 0, "best_pos": pos})
            d["hits"] += 1
            d["best_pos"] = min(d["best_pos"], pos)
    return found


def run(ws: Workspace, args: argparse.Namespace) -> None:
    settings, topics = info.load(ws)
    seeds = list(getattr(args, "seed", None) or settings.get("seeds") or [])
    if not seeds:
        print("  no seeds: add broad areas to _settings.seeds in config/info_topics.yaml (or pass --seed)")
        return
    lang, region = str(settings["lang"]), str(settings["region"])
    used = {" ".join(p.lower().split()) for t in topics for p in info.phrases(t)}
    rows = []
    for seed in seeds:
        found = expand(ws, str(seed), lang, region)
        ranked = sorted(found.items(), key=lambda kv: (-kv[1]["hits"], kv[1]["best_pos"], kv[0]))
        for phrase, d in ranked:
            rows.append({"seed": seed, "phrase": phrase, "hits": d["hits"], "best_pos": d["best_pos"],
                         "words": len(phrase.split()), "in_topics": int(phrase in used)})
        top = getattr(args, "top", 15)
        print(f"  {seed}: {len(found)} phrases; top: " + "; ".join(p for p, _ in ranked[:top]), flush=True)
    out = ws.out("info_suggest.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["seed", "phrase", "hits", "best_pos", "words", "in_topics"])
        w.writeheader()
        w.writerows(rows)
    print("->", out, len(rows))
