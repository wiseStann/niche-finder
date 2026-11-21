"""Paid info market per info topic: do people pay for information on the subject? Stepik courses and Litres books.

info_youtube measures attention, and views are not buyers (methodology 10). This stage looks at the paid side of
each topic in config/info_topics.yaml, in two Russian stores with open JSON and no key:

- Stepik (stepik.org, online courses). The catalog search (/api/search-results, 20 courses a page, at most 200
  results) ranks by popularity more than by relevance: under "english" the first page is Python courses and the
  English ones are spread over all ten pages. So all `stepik.pages` pages are read, and only courses whose title
  passes the topic filter are looked up in /api/courses (language, learners_count, is_paid, price,
  became_published_at) and /api/course-review-summaries (review count).
- Litres (litres.ru, ebooks incl. PDF: /foundation/api/search?types=text_book, relevance order, `litres.limit` books
  a page, `litres.pages` pages). A book carries its price, free flag, rating count, first sale date and publisher.
  The rating count is the sales proxy (a reader rates a book they took). The search covers fiction too, and a topic
  word is often a novel's title ("Pravo ..." romance fantasy under law, love novels under relationships), but only
  the single-book endpoint /foundation/api/arts/<id> names the genres. So each book that would count (relevant,
  paid, at least `litres.min_ratings` ratings) is looked up once, and a book whose main genre matches
  `litres.fiction_genres` is dropped (lr_fiction counts them).

Relevance: search hits are loose. A course or book counts only when its title (Litres: title + subtitle) matches the
topic's `must` regex (a per-topic override in config/info_paid.yaml `topics` wins: `must` was written for YouTube
descriptions and a stem such as "funkci" is fine there but pulls in every Python course here), or, without `must`,
contains every word of one of its phrases (stems); `must_not` drops a hit whose title or description matches; with
`_settings.lang` only items in that language count. Check data/out/info_paid_items.csv before trusting a number.
Both stores search the phrases without the `phrase_strip` words ("for beginners", "from scratch"): Litres matches
every word, so "piano for beginners" finds no book while "piano" finds the piano books.

Per topic (data/out/info_paid.csv):
  Stepik  sp_hits (search hits read), sp_courses (relevant), sp_paid, sp_paid_learners, sp_paid_reviews,
          sp_price_median (RUB), sp_paid_new (paid courses published within `new_months`), sp_top (most learners)
  Litres  lr_total (the store's hit count for the first phrase, unfiltered), lr_hits (books read), lr_books
          (relevant), lr_fiction (dropped as fiction), and over the books that sold, i.e. relevant paid non-fiction
          books with at least `litres.min_ratings` ratings: lr_paid, lr_ratings, lr_price_median (RUB), lr_new (first
          on sale within `new_months`), lr_selfpub (no publisher: Litres self-publishing, the route open to a single
          author), lr_top (most rated three)
  paid_flag  I:paid-market  sp_paid_learners >= flags.paid_market.stepik_learners or lr_ratings >= .litres_ratings
             I:no-paid      both sources read, no relevant paid Stepik course, lr_paid < flags.no_paid.litres_books and
                            lr_ratings < flags.no_paid.litres_ratings
Thresholds: config/info_paid.yaml, `status: draft` until the owner fixes them. info_score shows the columns and the
flag; neither changes the info score or the verdict.

Cache: data/cache/stepik/ and data/cache/litres/. Search pages and course facts are keyed by the run month
(ws.today:%Y-%m): a re-run in the same month is free, the next month reads fresh counts; Litres genres are keyed by
book only. Cost: free; per phrase about 10 Stepik and 2 Litres searches, a few Stepik lookups and one Litres lookup
per counted book, 0.3 s apart in each of --workers threads (topics in parallel; the first run of 61 topics took 18
minutes with 4 workers, a cached re-run 15 s). Caveats: Stepik is mostly IT, school and exam courses, so craft and
lifestyle topics read empty there although the market sells elsewhere (GetCourse schools,
Telegram, marketplaces: no open catalog); samples are capped (200 Stepik hits, `litres.pages` x `litres.limit` books
per phrase), so broad subjects hit the cap; Stepik learners include people who took only a free part; a Litres
rating count is lifetime, not a yearly rate.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import statistics
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from nichefinder import http, info
from nichefinder.workspace import Workspace

SUMMARY = "Paid info market per topic: Stepik courses and Litres books (evidence, no effect on the score)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

CONFIG = "info_paid.yaml"
STEPIK = "https://stepik.org/api"
LITRES = "https://api.litres.ru/foundation/api"
SLEEP = 0.3
# Litres genre names of fiction, matched against the book's main genre ("magicheskie akademii" is romance fantasy)
FICTION = (r"роман|фэнтези|фантастик|попаданц|детектив|триллер|проза|приключени|боевик|мистика|ужас|эротическ|литрпг"
           r"|поэзи|стих|сказк|драматург|пьес|русская классика|зарубежная классика|литература \d+ века|школьной литератур"
           r"|рассказ|новелл|фанфик|юмористическ|комикс|манга|young adult|антиутоп|киберпанк|современная русская литература"
           r"|современная зарубежная литература|историческая литература|магическ|волшебник|вампир|оборотн|древневосточн")
DEFAULTS = {
    "new_months": 24,
    "phrase_strip": r"\b(?:для начинающих|для новичков|с нуля)\b",
    "stepik": {"pages": 10},
    "litres": {"pages": 2, "limit": 100, "min_ratings": 5, "fiction_genres": FICTION},
    "flags": {"paid_market": {"stepik_learners": 5000, "litres_ratings": 3000},
              "no_paid": {"litres_books": 3, "litres_ratings": 100}},
}
COLS = ["topic_id", "phrases", "paid_flag", "sp_status", "sp_hits", "sp_courses", "sp_paid", "sp_paid_learners",
        "sp_paid_reviews", "sp_price_median", "sp_paid_new", "sp_top", "lr_status", "lr_total", "lr_hits", "lr_books",
        "lr_fiction", "lr_paid", "lr_ratings", "lr_price_median", "lr_new", "lr_selfpub", "lr_top"]
ITEM_COLS = ["topic_id", "source", "id", "title", "paid", "price", "buyers", "reviews", "published", "selfpub", "note",
             "url"]


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--topics", default="", help="comma-separated topic ids (default: all topics)")
    p.add_argument("--sources", default="stepik,litres", help="comma-separated: stepik, litres (default: both)")
    p.add_argument("--workers", type=int, default=4, help="topics measured in parallel (default 4)")
    p.add_argument("--dry", action="store_true", help="list the topics and phrases; no requests")


def settings(ws: Workspace) -> dict:
    """config/info_paid.yaml over DEFAULTS."""
    cfg = ws.load_config(CONFIG, {}) or {}
    out = {"new_months": cfg.get("new_months", DEFAULTS["new_months"]), "status": cfg.get("status", "draft"),
           "topics": cfg.get("topics") or {}, "phrase_strip": cfg.get("phrase_strip", DEFAULTS["phrase_strip"])}
    for k in ("stepik", "litres"):
        out[k] = {**DEFAULTS[k], **(cfg.get(k) or {})}
    fl = cfg.get("flags") or {}
    out["flags"] = {k: {**DEFAULTS["flags"][k], **(fl.get(k) or {})} for k in DEFAULTS["flags"]}
    return out


# ---- relevance ---------------------------------------------------------------------------------------------------

def stem(word: str) -> str:
    return word if len(word) <= 4 else word[:max(4, len(word) - 3)]


def paid_phrases(topic: dict, strip: str) -> list[str]:
    """The topic's phrases without the `phrase_strip` words: Litres matches every word, and "piano for beginners"
    finds no book at all while "piano" finds the piano books."""
    out: list[str] = []
    for p in info.phrases(topic):
        q = " ".join((re.sub(strip, " ", p, flags=re.I) if strip else p).split()) or p
        if q not in out:
            out.append(q)
    return out


def matcher(topic: dict) -> re.Pattern:
    """The topic's `must`, or: every word (stem) of one of its phrases, in any order."""
    if topic.get("must"):
        return re.compile(str(topic["must"]), re.I)
    alts = []
    for p in info.phrases(topic):
        words = [w for w in re.findall(r"\w+", p.lower()) if len(w) >= 3] or re.findall(r"\w+", p.lower())
        if words:
            alts.append("".join(f"(?=.*{re.escape(stem(w))})" for w in words))
    return re.compile("|".join(alts) or r"(?!)", re.I | re.S)


def relevant(title: str, desc: str, must: re.Pattern, must_not: re.Pattern | None) -> bool:
    return bool(must.search(title)) and not (must_not and must_not.search(title + "\n" + desc))


# ---- small helpers -----------------------------------------------------------------------------------------------

def months_back(today: dt.date, months: int) -> dt.date:
    """First day of the month `months` before the run month."""
    y, m = today.year, today.month - int(months)
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, 1)


def day(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def median(vals: list[float]):
    return round(statistics.median(vals)) if vals else ""


def cached(ws: Workspace, ns: str, key: str, fetch):
    """JSON from data/cache/<ns>/, else fetch() stored slim (not the whole API answer)."""
    path = http.cache_file(ws.cache(ns), key)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    tmp = path.with_name(f"{path.name}.{threading.get_ident()}.part")     # topics run in threads: write, then rename
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return data


def get(url: str):
    data = http.request(url, headers={"Accept": "application/json"}, tries=5).json()   # resets seen on 2026-11-21
    time.sleep(SLEEP)
    return data


# ---- Stepik ------------------------------------------------------------------------------------------------------

def stepik_search(ws: Workspace, q: str, pages: int) -> list[dict]:
    """Catalog search hits [{id, title}], pages 1..`pages` (a page past the end answers 404)."""
    month = f"{ws.today:%Y-%m}"
    hits: list[dict] = []
    for page in range(1, max(1, pages) + 1):
        def fetch(page=page):
            try:
                d = get(f"{STEPIK}/search-results?" + urllib.parse.urlencode({"query": q, "type": "course",
                                                                              "page": page}))
            except http.HttpError as e:
                if e.status == 404 and page > 1:
                    return {"next": False, "hits": []}
                raise
            return {"next": bool((d.get("meta") or {}).get("has_next")),
                    "hits": [{"id": x.get("target_id") or x.get("course"), "title": x.get("course_title") or ""}
                             for x in d.get("search-results") or [] if x.get("target_type", "course") == "course"]}
        d = cached(ws, "stepik", f"search|{q}|{page}|{month}", fetch)
        hits += d["hits"]
        if not d["next"]:
            break
    return hits


def stepik_courses(ws: Workspace, ids: list[int]) -> dict[int, dict]:
    """Course facts for the ids, with the review count."""
    month = f"{ws.today:%Y-%m}"
    out: dict[int, dict] = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 20):
        chunk = ids[i:i + 20]

        def fetch(chunk=chunk):
            d = get(f"{STEPIK}/courses?" + "&".join(f"ids[]={x}" for x in chunk))
            courses = [{"id": c["id"], "title": c.get("title") or "", "summary": c.get("summary") or "",
                        "language": c.get("language") or "", "learners": c.get("learners_count") or 0,
                        "paid": bool(c.get("is_paid")), "price": c.get("price"), "currency": c.get("currency_code"),
                        "published": c.get("became_published_at") or c.get("create_date") or "",
                        "public": c.get("is_public", True), "review_summary": c.get("review_summary"),
                        "url": c.get("canonical_url") or f"https://stepik.org/course/{c['id']}/"}
                       for c in d.get("courses") or []]
            rs = [c["review_summary"] for c in courses if c["review_summary"]]
            reviews = {}
            if rs:
                r = get(f"{STEPIK}/course-review-summaries?" + "&".join(f"ids[]={x}" for x in rs))
                reviews = {s["course"]: s.get("count") or 0 for s in r.get("course-review-summaries") or []}
            for c in courses:
                c["reviews"] = reviews.get(c["id"], 0)
            return courses
        for c in cached(ws, "stepik", f"courses|{month}|{','.join(map(str, chunk))}", fetch):
            out[int(c["id"])] = c
    return out


def stepik_metrics(courses: list[dict], since: dt.date) -> dict:
    paid = [c for c in courses if c["paid"]]
    prices = [p for c in paid if c.get("currency") in (None, "RUB") and (p := num(c.get("price")))]
    top = max(paid, key=lambda c: c["learners"], default=None)
    return {"sp_courses": len(courses), "sp_paid": len(paid),
            "sp_paid_learners": sum(c["learners"] for c in paid),
            "sp_paid_reviews": sum(c.get("reviews") or 0 for c in paid),
            "sp_price_median": median(prices),
            "sp_paid_new": sum(1 for c in paid if (d := day(c["published"])) and d >= since),
            "sp_top": (f"{top['title'][:70]} ({top['learners']} learners, {num(top.get('price')) or 0:.0f} RUB)"
                       if top else "")}


# ---- Litres ------------------------------------------------------------------------------------------------------

def litres_book(x: dict) -> dict:
    i = x.get("instance") or {}
    pr = i.get("prices") or {}
    rt = i.get("rating") or {}
    price = num(pr.get("full_price")) or num(pr.get("final_price")) or 0.0
    return {"id": i.get("id"), "title": i.get("title") or "", "subtitle": i.get("subtitle") or "",
            "language": i.get("language_code") or "", "price": price, "currency": pr.get("currency") or "RUB",
            "paid": not i.get("is_free") and price > 0, "ratings": rt.get("rated_total_count") or 0,
            "published": i.get("available_from") or i.get("date_written_at") or "",
            "selfpub": not any(p.get("role") == "publisher" for p in i.get("persons") or []),
            "url": "https://www.litres.ru" + (i.get("url") or "")}


def litres_search(ws: Workspace, q: str, pages: int, limit: int) -> tuple[int | None, list[dict]]:
    """(store hit count, books) for the first `pages` pages of `limit` books."""
    month = f"{ws.today:%Y-%m}"
    total, books = None, []
    for page in range(max(1, pages)):
        def fetch(page=page):
            d = get(f"{LITRES}/search?" + urllib.parse.urlencode({"q": q, "types": "text_book", "limit": limit,
                                                                  "offset": page * limit}))
            p = d.get("payload") or {}
            extra = p.get("extra") or {}
            return {"total": (extra.get("counters") or {}).get("text_book"),
                    "next": (extra.get("pagination") or {}).get("next_offset") is not None,
                    "books": [litres_book(x) for x in p.get("data") or [] if x.get("type") == "text_book"]}
        d = cached(ws, "litres", f"search|{q}|{limit}|{page}|{month}", fetch)
        total = d["total"] if total is None else total
        books += d["books"]
        if not d["next"] or len(d["books"]) < limit:
            break
    return total, books


def litres_genre(ws: Workspace, book_id) -> str:
    """The book's main genre (else its first genre), '' when it has none. Cached per book, not per month."""
    def fetch():
        try:
            a = (get(f"{LITRES}/arts/{int(book_id)}").get("payload") or {}).get("data") or {}
        except http.HttpError as e:
            if e.status != 404:            # a book withdrawn since the search: genre unknown, the book counts
                raise
            a = {}
        gs = a.get("genres") or []
        main = next((g for g in gs if g.get("is_main")), gs[0] if gs else {})
        return {"genre": main.get("name") or ""}
    return cached(ws, "litres", f"art|{book_id}", fetch)["genre"]


def litres_metrics(sold: list[dict], since: dt.date) -> dict:
    """Metrics over the books that sold (relevant, paid, non-fiction, enough ratings)."""
    top = sorted(sold, key=lambda b: -b["ratings"])[:3]
    return {"lr_paid": len(sold), "lr_ratings": sum(b["ratings"] for b in sold),
            "lr_price_median": median([b["price"] for b in sold if b["currency"] == "RUB"]),
            "lr_new": sum(1 for b in sold if (d := day(b["published"])) and d >= since),
            "lr_selfpub": sum(1 for b in sold if b["selfpub"]),
            "lr_top": " | ".join(f"{b['title'][:60]} ({b['ratings']} ratings, {b['price']:.0f} RUB)" for b in top)}


# ---- flag and run ------------------------------------------------------------------------------------------------

def paid_flag(row: dict, flags: dict) -> str:
    """I:paid-market, I:no-paid or '' (a source that failed or was not read cannot support I:no-paid)."""
    pm, npd = flags["paid_market"], flags["no_paid"]
    sp_l, lr_r = num(row.get("sp_paid_learners")), num(row.get("lr_ratings"))
    if (sp_l is not None and sp_l >= pm["stepik_learners"]) or (lr_r is not None and lr_r >= pm["litres_ratings"]):
        return "I:paid-market"
    if (row.get("sp_status") == "ok" and row.get("lr_status") == "ok" and num(row.get("sp_paid")) == 0
            and (num(row.get("lr_paid")) or 0) < npd["litres_books"]
            and (num(row.get("lr_ratings")) or 0) < npd["litres_ratings"]):
        return "I:no-paid"
    return ""


def measure(ws: Workspace, topic: dict, cfg: dict, lang: str, sources: set[str], since: dt.date):
    """(row, items) for one topic."""
    topic = {**topic, **(cfg["topics"].get(topic["id"]) or {})}
    topic["q"] = paid_phrases(topic, cfg["phrase_strip"])
    must = matcher(topic)
    must_not = re.compile(str(topic["must_not"]), re.I) if topic.get("must_not") else None
    row: dict = {"topic_id": topic["id"], "phrases": "; ".join(info.phrases(topic))}
    items: list[dict] = []
    base = {"topic_id": topic["id"]}
    if "stepik" in sources:
        try:
            hits: dict[int, str] = {}
            for q in info.phrases(topic):
                for h in stepik_search(ws, q, int(cfg["stepik"]["pages"])):
                    if h["id"]:
                        hits.setdefault(int(h["id"]), h["title"])
            found = stepik_courses(ws, [i for i, t in hits.items() if must.search(t)])
            courses = [c for c in found.values() if c.get("public", True) and (not lang or c["language"] == lang)
                       and relevant(c["title"], c["summary"], must, must_not)]
            row.update({"sp_status": "ok", "sp_hits": len(hits), **stepik_metrics(courses, since)})
            items += [{**base, "source": "stepik", "id": c["id"], "title": c["title"], "paid": int(c["paid"]),
                       "price": c.get("price") or "", "buyers": c["learners"], "reviews": c.get("reviews", 0),
                       "published": str(c["published"])[:10], "url": c["url"]}
                      for c in sorted(courses, key=lambda c: -c["learners"])]
        except (http.HttpError, OSError, ValueError, KeyError) as e:
            row["sp_status"] = f"error: {str(e)[:80]}"
    if "litres" in sources:
        try:
            lc = cfg["litres"]
            total, books = None, {}
            for q in info.phrases(topic):
                t, bs = litres_search(ws, q, int(lc["pages"]), int(lc["limit"]))
                total = t if total is None else total
                for b in bs:
                    books.setdefault(b["id"], b)
            kept = [b for b in books.values() if (not lang or b["language"] in ("", lang))
                    and relevant(f"{b['title']}. {b['subtitle']}", "", must, must_not)]
            fiction = re.compile(str(lc["fiction_genres"]), re.I)
            sold, dropped = [], []
            for b in kept:
                if b["paid"] and b["ratings"] >= int(lc["min_ratings"]):
                    b["genre"] = litres_genre(ws, b["id"])
                    b["fiction"] = bool(b["genre"] and fiction.search(b["genre"]))
                    (dropped if b["fiction"] else sold).append(b)
            row.update({"lr_status": "ok", "lr_total": total if total is not None else "", "lr_hits": len(books),
                        "lr_books": len(kept), "lr_fiction": len(dropped), **litres_metrics(sold, since)})
            items += [{**base, "source": "litres", "id": b["id"],
                       "title": b["title"] + (f". {b['subtitle']}" if b["subtitle"] else ""), "paid": int(b["paid"]),
                       "price": f"{b['price']:.0f}", "buyers": b["ratings"], "published": str(b["published"])[:10],
                       "selfpub": int(b["selfpub"]), "note": ("fiction: " if b["fiction"] else "") + b["genre"],
                       "url": b["url"]}
                      for b in sorted(sold + dropped, key=lambda b: -b["ratings"])]
        except (http.HttpError, OSError, ValueError, KeyError) as e:
            row["lr_status"] = f"error: {str(e)[:80]}"
    row["paid_flag"] = paid_flag(row, cfg["flags"])
    return row, items


def run(ws: Workspace, args: argparse.Namespace) -> None:
    tsettings, topics = info.load(ws)
    topics = [t for t in topics if t.get("id") and info.phrases(t)]
    if not topics:
        print("  no topics in config/info_topics.yaml: nothing to measure")
        return
    wanted = {x.strip() for x in (getattr(args, "topics", "") or "").split(",") if x.strip()}
    if wanted:
        topics = [t for t in topics if t["id"] in wanted]
    sources = {x.strip() for x in (getattr(args, "sources", "") or "stepik,litres").split(",") if x.strip()}
    cfg = settings(ws)
    lang = str(tsettings.get("lang") or "")
    since = months_back(ws.today, int(cfg["new_months"]))
    print(f"topics: {len(topics)}; sources: {', '.join(sorted(sources))}; new = since {since}; "
          f"thresholds {cfg['status']} (config/{CONFIG})")
    if getattr(args, "dry", False):
        for t in topics:
            print(f"  {t['id']:32} {'; '.join(info.phrases(t))}")
        return
    rows, items = [], []
    with ThreadPoolExecutor(max_workers=max(1, int(getattr(args, "workers", 4) or 1))) as pool:
        for t, (row, its) in zip(topics, pool.map(lambda t: measure(ws, t, cfg, lang, sources, since), topics)):
            rows.append(row)
            items += its
            print(f"  {t['id']:30} stepik {row.get('sp_paid', '-')} paid of {row.get('sp_courses', '-')}, "
                  f"{row.get('sp_paid_learners', '-')} learners | litres {row.get('lr_paid', '-')} sold, "
                  f"{row.get('lr_ratings', '-')} ratings, {row.get('lr_fiction', '-')} fiction  {row['paid_flag']}"
                  + "".join(f"  [{k} {row[k]}]" for k in ("sp_status", "lr_status") if str(row.get(k, "ok")) != "ok"),
                  flush=True)
    with open(ws.out("info_paid.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(ws.out("info_paid_items.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ITEM_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    n = {f: sum(1 for r in rows if r["paid_flag"] == f) for f in ("I:paid-market", "I:no-paid")}
    print(f"I:paid-market {n['I:paid-market']}, I:no-paid {n['I:no-paid']} of {len(rows)} topics")
    print("->", ws.out("info_paid.csv"), "and", ws.out("info_paid_items.csv"),
          "(info_score shows it; no effect on the score)")
