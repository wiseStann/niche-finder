"""Telegram channels behind each info topic's teaching Shorts: the size of the authors' funnels and whether they sell.

The cohort's business model ends in a Telegram channel, and the open web shows how big those channels are without
a paid API: the public page t.me/<name> gives a channel's subscriber count or a group's member count, its title and
its description. info_youtube stores, per video, the Telegram links of the video and channel descriptions
(`tg_links`: t.me links and "@name" after a Telegram word) and whether those descriptions link a payment,
paid-content or sales-funnel platform (`pay`). This stage fetches the
linked pages and measures, per topic, over the YouTube channels of its teaching videos (kind T or unlabelled):

- yt_channels: YouTube channels with teaching videos in the topic's top;
- tg_linked: of them, channels that link a Telegram channel or group showing a count (a funnel you can measure).
  A link named by two or more different YouTube channels is a sponsor or a network, not one author's funnel
  (the first run: a search engine's 590k channel from paid integrations), so it is left out (`shared` 1);
- top_channel: the largest linked channel, by title, with its subscribers;
- tg_subs_median, tg_subs_p90, tg_subs_max: subscribers of those Telegram channels, one per YouTube channel (its
  largest link), so one author's three links do not count three times;
- tg_big: linked Telegram channels with at least `big_subs` subscribers (10,000 by default);
- pay_share: share of the YouTube channels whose video or channel description, or the description of a linked
  Telegram channel, links a payment, paid-content or sales-funnel platform (info_youtube measure.pay_pattern:
  GetCourse, Boosty, Tribute, Prodamus, BotHelp, SaleBot...): authors who already sell, not only collect an
  audience.

What it cannot see: the links section of a YouTube channel ("link in profile", not in the API), so a funnel that
lives only there is missed and tg_linked is a floor; private channels behind invite links show a count only while the link is valid; bots are left
out (no audience count); a channel's growth over time and its post views need a paid API (TGStat, declined). The
numbers compare topics with each other; no effect on the score.

Input: data/out/info_youtube_videos.csv. Output: data/out/info_telegram.csv (per topic),
data/out/info_telegram_channels.csv (per Telegram link). Cache: data/cache/telegram/, keyed by the run month, so a
re-run in the same month is free and the next month sees fresh counts. No key.
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import statistics

from nichefinder import http, info
from nichefinder.stages.info_youtube import MEASURE, percentile
from nichefinder.workspace import Workspace

SUMMARY = "Telegram funnels of the info topics: subscribers of the linked channels, paid links"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

SETTINGS = {"big_subs": 10000, "sleep": 0.5}
EXTRA = re.compile(r'class="tgme_page_extra">\s*([^<]*)')
TITLE = re.compile(r'<meta property="og:title" content="([^"]*)"')
DESC = re.compile(r'class="tgme_page_description[^"]*"[^>]*>(.*?)</div>', re.S)
COUNT = re.compile(r"([\d][\d\s\u00a0\u202f]*)\s+(subscribers?|members?)")
TOPIC_COLS = ["topic_id", "yt_channels", "tg_linked", "tg_share", "tg_subs_median", "tg_subs_p90", "tg_subs_max",
              "tg_big", "pay_share", "top_channel"]
CHANNEL_COLS = ["link", "kind", "count", "title", "pay", "shared", "yt_channels", "topics", "description"]


def parse_page(page: str) -> dict:
    """A t.me/<name> page -> kind (channel / group / other), count, title, description (text with link targets)."""
    extra = EXTRA.search(page)
    m = COUNT.search(html.unescape(extra.group(1))) if extra else None
    kind, count = "other", None
    if m:
        count = int(re.sub(r"\D", "", m.group(1)))
        kind = "channel" if m.group(2).startswith("subscriber") else "group"
    t = TITLE.search(page)
    d = DESC.search(page)
    desc = ""
    if d:
        hrefs = " ".join(re.findall(r'href="([^"]+)"', d.group(1)))
        desc = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", d.group(1))).split()) + (" " + hrefs if hrefs else "")
    return {"kind": kind, "count": count, "title": html.unescape(t.group(1)) if t else "", "description": desc}


def fetch(ws: Workspace, link: str, sleep: float) -> dict:
    url = f"https://t.me/{link}"
    key = f"{link}_{ws.today:%Y-%m}"
    try:
        page = http.get_text(url, cache=ws.cache("telegram"), cache_key=key, ext=".html", min_size=2000, sleep=sleep,
                             timeout=30)
    except (http.HttpError, OSError) as e:
        print(f"  !! {link}: {str(e)[:100]}")
        return {"kind": "error", "count": None, "title": "", "description": ""}
    return parse_page(page)


def top_name(link: str, pages: dict[str, dict]) -> str:
    """The channel's title (an invite link is an unreadable hash), without "|", which would break a Markdown table."""
    title = " ".join((pages.get(link, {}).get("title") or "").replace("|", "/").split())
    return title or link


def topic_metrics(videos: list[dict], pages: dict[str, dict], pay: re.Pattern, big: int,
                  shared: set[str] = frozenset()) -> dict:
    """Per-topic metrics over the YouTube channels of the teaching videos (see the module docstring)."""
    by_channel: dict[str, dict] = {}
    for v in videos:
        c = by_channel.setdefault(v["channel_id"], {"links": [], "pay": False})
        c["links"] += [x for x in (v.get("tg_links") or "").split() if x not in c["links"] and x not in shared]
        c["pay"] = c["pay"] or v.get("pay") == "1"
    subs, top = [], ("", 0)
    paying = 0
    for c in by_channel.values():
        counted = [(pages[x]["count"], x) for x in c["links"] if pages.get(x, {}).get("count") is not None]
        if counted:
            n, link = max(counted)
            subs.append(n)
            if n > top[1]:
                top = (link, n)
        if c["pay"] or any(pay.search(pages.get(x, {}).get("description", "")) for x in c["links"]):
            paying += 1
    n_yt = len(by_channel)
    s = sorted(subs)
    return {
        "yt_channels": n_yt, "tg_linked": len(subs), "tg_share": round(len(subs) / n_yt, 3) if n_yt else "",
        "tg_subs_median": statistics.median(s) if s else "", "tg_subs_p90": percentile(s, 0.9) if s else "",
        "tg_subs_max": s[-1] if s else "", "tg_big": sum(1 for x in s if x >= big),
        "pay_share": round(paying / n_yt, 3) if n_yt else "", "top_channel": top_name(top[0], pages) + f" ({top[1]})"
        if top[0] else "",
    }


def run(ws: Workspace, args: argparse.Namespace) -> None:
    src = ws.out("info_youtube_videos.csv")
    _, topics = info.load(ws)
    if not src.is_file():
        if not topics:
            print("  no topics in config/info_topics.yaml: nothing to measure")
            return
        raise SystemExit(f"{src} not found: run `nf run info_youtube` first")
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    if rows and "tg_links" not in rows[0]:
        raise SystemExit(f"{src} has no tg_links column: re-run `nf run info_youtube` (free from its cache)")
    cfg = ws.load_config(info.SCORE_FILE, {}) or {}
    settings = {**SETTINGS, **(cfg.get("telegram") or {})}
    pay = re.compile({**MEASURE, **(cfg.get("measure") or {})}["pay_pattern"], re.I)
    teach = [r for r in rows if r.get("kind", "") in ("T", "")]
    by_topic: dict[str, list[dict]] = {}
    for r in teach:
        by_topic.setdefault(r["topic_id"], []).append(r)
    links: dict[str, set[str]] = {}
    owners: dict[str, set[str]] = {}
    for r in teach:
        for x in (r.get("tg_links") or "").split():
            links.setdefault(x, set()).add(r["topic_id"])
            owners.setdefault(x, set()).add(r["channel_id"])
    shared = {x for x, o in owners.items() if len(o) > 1}
    print(f"  {len(links)} Telegram links in the teaching videos of {len(by_topic)} topics")
    pages = {}
    for i, link in enumerate(sorted(links), 1):
        pages[link] = fetch(ws, link, float(settings["sleep"]))
        if i % 100 == 0:
            print(f"  {i}/{len(links)}", flush=True)
    out = []
    for tid, vs in by_topic.items():
        out.append({"topic_id": tid, **topic_metrics(vs, pages, pay, int(settings["big_subs"]), shared)})
    with open(ws.out("info_telegram.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TOPIC_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    with open(ws.out("info_telegram_channels.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CHANNEL_COLS, extrasaction="ignore")
        w.writeheader()
        for link in sorted(links):
            p = pages[link]
            w.writerow({"link": link, "kind": p["kind"], "count": "" if p["count"] is None else p["count"],
                        "title": p["title"], "pay": int(bool(pay.search(p["description"]))),
                        "shared": int(link in shared), "yt_channels": len(owners[link]),
                        "topics": " ".join(sorted(links[link])), "description": p["description"][:300]})
    for r in sorted(out, key=lambda r: -(r["tg_subs_median"] or 0))[:15]:
        print(f"  {r['topic_id']:28} linked {r['tg_linked']:>3}/{r['yt_channels']:<3} median {r['tg_subs_median'] or '-':>8} "
              f"big {r['tg_big']:>2} pay {r['pay_share']}")
    print("->", ws.out("info_telegram.csv"), "and", ws.out("info_telegram_channels.csv"))
