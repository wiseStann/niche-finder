"""LLM product check: which apps found by store search are products of a niche (who x task x product).

Store search relevance is loose. A top search position or a shared word is enough, so the candidates of a niche include
games ("cookie" -> CookieRun), apps for the other side of a market (the Wildberries shopper app for seller analytics) and
giants where the task is a side feature (Instagram for transcription). Measured by ratings, such apps dominate the
concentration of a niche and the voice of its reviews. The LLM gets the niche and a numbered list of apps (name,
developer, store genre) and answers per app whether these users would choose it, or weigh it against the niche's
products, for the task.

Used by s5_appstore (the `relevant` flag of appstore_apps.csv, so every consumer of that flag sees only the niche's
products), s8_gplay_filter (which Google Play apps make the relevant set; Google Play search has no genre, so an app
carries its store description in `about`) and s10_ru_reviews_fetch (which apps' reviews are read). LLM settings as in llm.py; answers are cached in
data/cache/llm/, so a re-run with the same candidates is free. One call per BATCH apps.
"""
from __future__ import annotations

from nichefinder import llm
from nichefinder.workspace import Workspace

BATCH = 60
ABOUT_CHARS = 150
SYSTEM = (
    "You check which apps belong to a market niche. A niche is who x task x product. You get the niche and a numbered list of "
    "apps that app store search returned for its queries (name | developer | store genre). For each app decide fit: "
    "yes = a product these users would choose or compare for this task: built for it, or a direct substitute they weigh against it; "
    "no = anything else: games and simulators; apps for the other side of a market (shoppers, guests, tenants, couriers, drivers, "
    "car owners or club members when the niche serves the business, the host or the seller); big general apps where the task is "
    "only a side feature (social networks, messengers, browsers, marketplaces, voice assistants, search engines, e-book readers); "
    "apps that only share a word with the niche. Judge by who the users are as much as by the task. "
    'Output JSON: {"apps": [{"k": <number>, "fit": "yes" or "no", "why": "<5-12 words>"}]} with every number.')


def _line(k: int, a: dict) -> str:
    s = f"{k}: {a['app']} | {a.get('developer') or '-'} | {a.get('genre') or '-'}"
    if a.get("about"):   # optional store description (Google Play search results have no genre)
        s += " | " + " ".join(str(a["about"]).split())[:ABOUT_CHARS]
    return s


def _batch(ws: Workspace, niche: dict, apps: list[dict]) -> list[tuple[str, str]]:
    lines = [_line(k, a) for k, a in enumerate(apps, 1)]
    # the header changes only when descriptions are present, so App Store requests keep their cache keys
    head = "Apps (name | developer | store genre | store description):" if any(a.get("about") for a in apps) else "Apps:"
    user = (f"Niche: {niche.get('name') or niche.get('id', '')}\nWho: {niche.get('who', '')}\nTask: {niche.get('task', '')}\n"
            f"Product: {niche.get('product', '')}\n\n{head}\n" + "\n".join(lines))
    content, _, _ = llm.chat_json(ws, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                                  max_tokens=4000, temperature=0.0)
    got: dict[int, tuple[str, str]] = {}
    for it in (content or {}).get("apps") or []:
        try:
            k = int(it.get("k"))
        except (TypeError, ValueError, AttributeError):
            continue
        fit = str(it.get("fit") or "").strip().lower()
        got[k] = ("yes" if fit == "yes" else "no", str(it.get("why") or "").strip()[:160])
    return [got.get(k, ("", "no answer from the model")) for k in range(1, len(apps) + 1)]


def check(ws: Workspace, niche: dict, apps: list[dict]) -> list[tuple[str, str]]:
    """(fit, why) per app, in order. `niche` is a niches.yaml entry (name, who, task, product); `apps` are dicts with
    `app`, `developer`, `genre` and optionally `about` (a store description). fit is "yes", "no", or "" when the model gave no answer for the app."""
    out: list[tuple[str, str]] = []
    for i in range(0, len(apps), BATCH):
        out += _batch(ws, niche, apps[i:i + BATCH])
    return out
