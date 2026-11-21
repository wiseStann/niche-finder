"""S8: paid demand on Russian freelance exchanges (Kwork buyer requests, FL.ru projects) for shortlisted niches.

A buyer who posts a job and names a budget is paying to get a niche's task done. Two kinds count as paid demand:
`build` (someone pays to build, clone, customise or integrate software that does the niche's task: an unmet need, or a
would-be competitor) and `service` (someone pays a person to do by hand the task the niche's product does or
simplifies). Most shortlisted niches are B2C apps, where freelance demand is naturally about zero; that is a valid result.

Fetch: snapshots of the public lists, read within robots.txt (no search requests):
  Kwork  kwork.ru/projects?c=<subcategory>, the first page of every subcategory. robots.txt disallows `?page=` and
         `&page=` (and /search), so deeper pages are not read: a snapshot holds the 12 newest active requests of each
         subcategory, about 3/4 of the ~330 requests that are active at a time (requests stay open for a few days). The
         page embeds `window.stateData` JSON: wantsListData.wants with id, name, description, priceLimit (the buyer's
         budget, RUB), possiblePriceLimit (the most the buyer accepts), kwork_count (offers so far), views_dirty,
         date_active (publication; date_create can be years old for a re-opened request), category_id, and the
         buyer's hire rate; exchangeStats has the exchange totals for 30 days.
  FL.ru  www.fl.ru/projects/page-N/ until the list ends (~65 pages of 30, about two months of projects). The archive
         search (/search/projects/?q=, which works and reaches back to 2005) and the RSS feeds are disallowed by
         robots.txt, and the `search=` parameter of /projects/ is ignored (an unrelated pinned project comes first), so
         the stage reads the plain list: title, a cut description, budget text, kind (order / vacancy / contest),
         number of responses, date. Vacancies are kept in the history but not counted.
History: every post read is merged into data/out/freelance_history.csv by (source, id) with first_seen / last_seen, so
repeated runs accumulate, and the metrics are computed over the whole history (its span is in the output).
Matching: niches.text_matchers(ws, with_coverage=True) for the shortlisted niches gives keyword candidates;
config/freelance.yaml `match` replaces the predicate of a niche whose coverage stems collide with common words in job
posts (for example the stem for car repair shops matches the Russian word for "price"). Then the LLM labels each
(post, candidate niche): build / service / study / topic / none; build + service count. When the check is off
(--no-llm), has no LLM_API_KEY or gets no answer (one probe call decides, so a dead endpoint costs one retry), the
keyword candidates are counted as they are; `verified` is the share of a niche's candidates that carry an LLM label.
Outputs: data/out/freelance.csv (one row per shortlisted niche), freelance_matches.csv (every labelled candidate),
freelance_history.csv (all posts read so far); reports/freelance.md.
Cache: data/cache/freelance/ (list pages, keyed by the run date, so a re-run the same day is free), data/cache/llm/.
Cost: free; ~70 Kwork + ~65 FL.ru requests per run with polite sleeps; LLM calls only for posts not labelled before.
Caveats: snapshots, not the archive, so counts depend on how often the stage runs; budgets are what buyers type (FL.ru
often "by agreement"); a keyword can miss a post that describes the task in other words. Evidence only: never changes
the S6 score or verdict.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from nichefinder import http, keys, llm, niches
from nichefinder.workspace import Workspace

SUMMARY = "Paid demand on freelance exchanges (Kwork buyer requests, FL.ru projects) per shortlisted niche"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ()

KWORK = "https://kwork.ru/projects"
FL = "https://www.fl.ru/projects/"
HIST_FIELDS = ["source", "id", "url", "first_seen", "last_seen", "date", "kind", "category", "title", "description",
               "budget", "budget_max", "currency", "offers", "views", "buyer_hired_pct"]
LABELS = ("build", "service", "study", "topic", "none")
PAID = ("build", "service")
# Russian month name stems in FL.ru dates (day, month in the genitive, time)
MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8, "сентябр": 9,
          "октябр": 10, "ноябр": 11, "декабр": 12}

SYSTEM = """You check whether a freelance job post shows paid demand for a niche product. For each candidate niche pick one label:
build - the buyer pays to build, clone, customise or integrate software that does this niche's task (an app, bot, script, plugin, CRM set-up for this task);
service - the buyer pays a person to do by hand the task that this niche's product does or simplifies;
study - a student assignment or diploma about such software;
topic - the same subject, but the work (writing, illustration, video, ads, lead generation for some business) would not be served by the product;
none - the keywords match by coincidence.
Judge by what the buyer wants done, not by the words. Answer JSON: {"labels": {"<niche id>": "<label>"}}."""


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--no-llm", action="store_true", help="count keyword candidates without the LLM check")
    p.add_argument("--source", choices=["kwork", "fl", "all"], default="all", help="which exchange to read (default all)")
    p.add_argument("--fl-pages", type=int, default=None, help="cap on FL.ru list pages (default from config, 80)")
    p.add_argument("--offline", action="store_true", help="do not fetch: re-match the history file only")


# --- Kwork -----------------------------------------------------------------------------------------------------------

def state_data(page: str) -> dict | None:
    """The `window.stateData = {...}` JSON embedded in a Kwork page."""
    i = page.find("window.stateData")
    if i < 0:
        return None
    j = page.find("=", i) + 1
    try:
        obj, _ = json.JSONDecoder().raw_decode(page[j:].lstrip())
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def kwork_subcategories(state: dict) -> dict[str, str]:
    """Subcategory id -> 'Parent / Subcategory' from stateData.categories."""
    out: dict[str, str] = {}
    for parent in (state.get("categories") or {}).values():
        for c in parent.get("cats") or []:
            cid = str(c.get("CATID") or c.get("id") or "")
            if cid:
                out[cid] = f"{parent.get('name', '')} / {c.get('name', '')}"
    return out


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def kwork_posts(state: dict, cats: dict[str, str]) -> list[dict]:
    wl = state.get("wantsListData") or {}
    out = []
    for w in wl.get("wants") or state.get("wants") or []:
        if not w.get("id"):
            continue
        user = (w.get("user") or {}).get("data") or {}
        out.append({"source": "kwork", "id": str(w["id"]), "url": f"{KWORK}/{w['id']}/view",
                    "date": str(w.get("date_active") or w.get("date_create") or "")[:10], "kind": "request",
                    "category": cats.get(str(w.get("category_id") or ""), str(w.get("category_id") or "")),
                    "title": html.unescape(w.get("name") or "").strip(),
                    "description": html.unescape(w.get("description") or "").strip()[:1500],
                    "budget": _num(w.get("priceLimit")), "budget_max": _num(w.get("possiblePriceLimit")),
                    "currency": "RUB", "offers": w.get("kwork_count"), "views": w.get("views_dirty"),
                    "buyer_hired_pct": user.get("wants_hired_percent", "")})
    return out


def fetch_kwork(ws: Workspace, sleep: float) -> tuple[list[dict], dict]:
    cache = ws.cache("freelance")

    def page(url: str, key: str) -> dict | None:
        try:
            s = http.get_text(url, cache=cache, cache_key=f"kwork_{ws.today}_{key}", ext=".html", min_size=50_000,
                              sleep=sleep, raise_for_status=False)
        except OSError as e:
            print(f"  kwork {key}: {e}")
            return None
        return state_data(s)

    first = page(KWORK, "all")
    if not first:
        print("  kwork: no stateData on the first page (layout changed or blocked)")
        return [], {}
    cats = kwork_subcategories(first)
    posts = {p["id"]: p for p in kwork_posts(first, cats)}
    for cid in cats:
        st = page(f"{KWORK}?c={cid}", f"c{cid}")
        for p in kwork_posts(st, cats) if st else []:
            posts.setdefault(p["id"], p)
    stats = first.get("exchangeStats") or {}
    print(f"  kwork: {len(cats)} subcategories, {len(posts)} active requests read"
          + (f"; exchange in {stats.get('period')} days: {stats.get('projects')} requests, {stats.get('orders')} orders, "
             f"{stats.get('value')} RUB" if stats else ""))
    return list(posts.values()), stats


# --- FL.ru -----------------------------------------------------------------------------------------------------------

def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_fl_date(s: str, today: dt.date) -> str:
    """FL.ru post date -> ISO date ('' if unknown). Forms: 'N hours M minutes ago', 'yesterday, HH:MM', 'today, HH:MM',
    'D month, HH:MM' (this year, or last year when that date is still ahead) and 'D month YYYY'."""
    t = s.strip().lower()
    if "назад" in t or "сейчас" in t:      # "N hours M minutes ago": today (a post just before midnight is off by a day)
        d = re.search(r"(\d+)\s*(?:дн|день|дня)", t)
        return (today - dt.timedelta(days=int(d.group(1)) if d else 0)).isoformat()
    if t.startswith("вчера"):
        return (today - dt.timedelta(days=1)).isoformat()
    if t.startswith("сегодня"):
        return today.isoformat()
    m = re.match(r"(\d{1,2})\s+([а-яё]+)\.?(?:\s+(\d{4}))?", t)
    if not m:
        return ""
    mon = next((n for stem, n in sorted(MONTHS.items(), key=lambda x: -len(x[0])) if m.group(2).startswith(stem)), 0)
    if not mon:
        return ""
    year = int(m.group(3)) if m.group(3) else today.year
    try:
        d = dt.date(year, mon, int(m.group(1)))
    except ValueError:
        return ""
    if not m.group(3) and d > today:
        d = d.replace(year=year - 1)
    return d.isoformat()


def parse_fl_price(s: str) -> tuple[float | None, float | None, str]:
    """Budget text -> (budget, budget_max, currency). A range gives its low end as budget and its high end as max;
    'up to X' gives X as both; 'by agreement' gives nothing. The 999 999 placeholder is dropped."""
    t = _text(s).replace(" ", " ")
    cur = "RUB" if ("₽" in t or "руб" in t) else "USD" if "$" in t else "EUR" if "€" in t else ""
    nums = [float(x.replace(" ", "")) for x in re.findall(r"\d[\d ]*", t)]
    nums = [x for x in nums if 0 < x < 999_999]
    if not nums:
        return None, None, cur
    return min(nums), max(nums), cur


def parse_fl(page: str, today: dt.date) -> list[dict]:
    out = []
    parts = re.split(r'id="project-item(\d+)"', page)
    for pid, blk in zip(parts[1::2], parts[2::2]):
        t = re.search(r'id="prj_name_\d+"[^>]*>(.*?)</a>', blk, re.S)
        if not t:
            continue
        price = re.search(r'b-post__price[^>]*>\s*<span[^>]*>(.*?)</span>', blk, re.S)
        desc = re.search(r'<div class="b-post__txt text-5 ">(.*?)</div>', blk, re.S)
        kind = re.search(r'b-post__bold b-layout__txt_inline-block[^"]*">(.*?)<', blk, re.S)
        when = re.search(r'text-gray-opacity-4 text-7 mr-16">([^<]+)<', blk)
        resp = re.search(r"(\d+)\s+ответ|Нет ответов", blk)
        views = re.search(r'title="Количество просмотров".*?<span class="text-7">([^<]*)<', blk, re.S)
        href = re.search(r'href="(/projects/' + pid + r'/[^"]+)"', blk)
        b, bmax, cur = parse_fl_price(price.group(1)) if price else (None, None, "")
        out.append({"source": "fl", "id": pid, "url": "https://www.fl.ru" + (href.group(1) if href else f"/projects/{pid}/"),
                    "date": parse_fl_date(when.group(1), today) if when else "",
                    "kind": _text(kind.group(1)) if kind else "", "category": "",
                    "title": _text(t.group(1)), "description": _text(desc.group(1))[:1500] if desc else "",
                    "budget": b, "budget_max": bmax, "currency": cur,
                    "offers": (int(resp.group(1)) if resp.group(1) else 0) if resp else "",
                    "views": _text(views.group(1)) if views else "", "buyer_hired_pct": ""})
    return out


def fetch_fl(ws: Workspace, max_pages: int, sleep: float) -> list[dict]:
    cache = ws.cache("freelance")
    posts: dict[str, dict] = {}
    read = 0
    for n in range(1, max_pages + 1):
        url = FL if n == 1 else f"{FL}page-{n}/"
        try:
            s = http.get_text(url, cache=cache, cache_key=f"fl_{ws.today}_p{n}", ext=".html", min_size=100_000,
                              sleep=sleep, raise_for_status=False)
        except OSError as e:
            print(f"  fl page {n}: {e}")
            break
        items = parse_fl(s, ws.today)
        if not items:      # past the end of the list (FL.ru answers 404)
            break
        read += 1
        for p in items:
            posts.setdefault(p["id"], p)
    dates = sorted(p["date"] for p in posts.values() if p["date"])
    print(f"  fl.ru: {read} pages, {len(posts)} projects" + (f" from {dates[0]} to {dates[-1]}" if dates else ""))
    return list(posts.values())


# --- history, matching, labelling ------------------------------------------------------------------------------------

def merge_history(ws: Workspace, posts: list[dict]) -> list[dict]:
    path = ws.out("freelance_history.csv")
    hist: dict[tuple[str, str], dict] = {}
    if path.is_file():
        for r in csv.DictReader(open(path, encoding="utf-8")):
            hist[(r["source"], r["id"])] = r
    today = ws.today.isoformat()
    for p in posts:
        k = (p["source"], p["id"])
        old = hist.get(k)
        row = {f: ("" if p.get(f) is None else p.get(f)) for f in HIST_FIELDS}
        row["first_seen"] = old["first_seen"] if old else today
        row["last_seen"] = today
        hist[k] = row
    rows = sorted(hist.values(), key=lambda r: (r["source"], r["date"], r["id"]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HIST_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


def matchers(ws: Workspace, ids: list[str], cfg: dict) -> dict[str, Callable[[str], bool]]:
    base = niches.text_matchers(ws, ids, with_coverage=True)
    out = {nid: base[nid] for nid in ids if nid in base}
    for nid, pat in (cfg.get("match") or {}).items():
        if nid in ids and pat:
            rx = re.compile(pat, re.I)
            out[nid] = lambda text, rx=rx: bool(rx.search(text))
    return out


def label_post(ws: Workspace, post: dict, cands: list[str], info: dict[str, dict]) -> dict[str, str] | None:
    """LLM labels for one post and its candidate niches; None when the model gave no answer (the post stays unlabelled)."""
    lines = [f"- {nid}: {info.get(nid, {}).get('who', '')}; {info.get(nid, {}).get('task', '')}; "
             f"{info.get(nid, {}).get('product', '')}" for nid in cands]
    user = (f"Exchange: {post['source']}\nTitle: {post['title']}\nText: {post['description'][:1200]}\n"
            f"Budget: {post.get('budget') or 'not set'}\n\nCandidate niches:\n" + "\n".join(lines))
    res, _, _ = llm.chat_json(ws, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                              max_tokens=300, tries=2)
    if not isinstance(res, dict) or not isinstance(res.get("labels"), dict):
        return None
    labels = {nid: str(res["labels"].get(nid, "")).strip().lower() for nid in cands}
    return {nid: (v if v in LABELS else "") for nid, v in labels.items()}


def _median(xs: list[float]) -> float | str:
    return round(statistics.median(xs)) if xs else ""


def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = ws.load_config("freelance.yaml", {}) or {}
    ids = niches.shortlist_ids(ws)
    sleep = float(cfg.get("sleep", 1.0))
    src = getattr(args, "source", "all") or "all"
    posts, stats = [], {}
    if not getattr(args, "offline", False):
        if src in ("kwork", "all") and (cfg.get("kwork") or {}).get("enabled", True):
            got, stats = fetch_kwork(ws, sleep)
            posts += got
        if src in ("fl", "all") and (cfg.get("fl") or {}).get("enabled", True):
            pages = getattr(args, "fl_pages", None) or int((cfg.get("fl") or {}).get("max_pages", 80))
            posts += fetch_fl(ws, pages, sleep)
    hist = merge_history(ws, posts)
    if not hist:
        print("no posts read and no history - nothing to match")
        return
    preds = matchers(ws, ids, cfg)
    info = {n["id"]: n for n in niches.load_niches(ws)}
    counted = [r for r in hist if not r["kind"].lower().startswith("вакансия")]  # FL.ru vacancies are job posts, not orders
    cands: dict[tuple[str, str], list[str]] = {}
    for r in counted:
        text = f"{r['title']}\n{r['description']}"
        hit = [nid for nid, f in preds.items() if f(text)]
        if hit:
            cands[(r["source"], r["id"])] = hit
    want_llm = cfg.get("llm", True) and not getattr(args, "no_llm", False)
    use_llm = want_llm and keys.have("LLM_API_KEY")
    llm_note = "" if use_llm else ("LLM_API_KEY not set" if want_llm else "LLM check switched off")
    by_key = {(r["source"], r["id"]): r for r in counted}
    labels: dict[tuple[str, str], dict[str, str]] = {}
    missing = 0
    if use_llm and cands:
        print(f"  labelling {len(cands)} posts with keyword candidates (cached ones are free)", flush=True)
        first = next(iter(cands))
        got = label_post(ws, by_key[first], cands[first], info)     # one probe call: a dead endpoint fails once, not per post
        if got is None:
            use_llm, llm_note = False, "the LLM gave no answer: check its key, balance and endpoint in the retry message"
        else:
            labels[first] = got
            with ThreadPoolExecutor(max_workers=int(cfg.get("llm_workers", 6))) as ex:
                futs = {k: ex.submit(label_post, ws, by_key[k], c, info) for k, c in cands.items() if k != first}
                for k, fu in futs.items():
                    try:
                        res = fu.result()
                    except Exception as e:  # noqa: BLE001 - one failed call leaves the post unlabelled
                        print(f"    {k}: {str(e)[:120]}")
                        res = None
                    if res is not None:
                        labels[k] = res
            missing = len(cands) - len(labels)
            if missing:
                print(f"  {missing} posts got no LLM answer: their candidates are counted unverified")
    if llm_note:
        print(f"  {llm_note}: keyword candidates are counted unverified")
    matches = []
    for k, c in cands.items():
        r = by_key[k]
        for nid in c:
            lab = labels.get(k, {}).get(nid, "") if use_llm else ""
            matches.append({"niche_id": nid, "source": r["source"], "id": r["id"], "date": r["date"], "label": lab,
                            "title": r["title"], "budget": r["budget"], "budget_max": r["budget_max"], "currency": r["currency"],
                            "offers": r["offers"], "category": r["category"], "url": r["url"]})
    span = {s: sorted(r["date"] for r in counted if r["source"] == s and r["date"]) for s in ("kwork", "fl")}
    seen = {s: sorted({r["first_seen"] for r in hist if r["source"] == s} | {r["last_seen"] for r in hist if r["source"] == s})
            for s in ("kwork", "fl")}
    rows = []
    for nid in ids:
        mine = [m for m in matches if m["niche_id"] == nid]
        # verified = share of the niche's candidates that carry an LLM label; an unlabelled candidate counts as a match
        row = {"niche_id": nid, "verified": round(sum(1 for m in mine if m["label"]) / len(mine), 2) if mine else "",
               "matched": 0}
        ex_all = []
        for s in ("kwork", "fl"):
            ms = [m for m in mine if m["source"] == s]
            ok = [m for m in ms if m["label"] in PAID or not m["label"]]
            rub = [float(m["budget"]) for m in ok if m["budget"] not in ("", None) and m["currency"] == "RUB"]
            offers = [float(m["offers"]) for m in ok if str(m["offers"]).strip() not in ("", "None")]
            row.update({f"{s}_candidates": len(ms), f"{s}_matched": len(ok),
                        f"{s}_build": sum(m["label"] == "build" for m in ms), f"{s}_service": sum(m["label"] == "service" for m in ms),
                        f"{s}_budget_med": _median(rub), f"{s}_budget_max": round(max(rub)) if rub else "",
                        f"{s}_offers_med": _median(offers)})
            row["matched"] += len(ok)
            ex_all += ok
        ex_all.sort(key=lambda m: -(float(m["budget"]) if m["budget"] not in ("", None) else 0))
        row["examples"] = " | ".join(f"{m['title'][:70]} ({round(float(m['budget'])) if m['budget'] not in ('', None) else '-'} "
                                     f"{m['currency'] or ''}, {m['source']})" for m in ex_all[:3])
        rows.append(row)
    for s in ("kwork", "fl"):
        for r in rows:
            r[f"{s}_posts"] = sum(1 for x in counted if x["source"] == s)
            r[f"{s}_window"] = f"{span[s][0]}..{span[s][-1]}" if span[s] else ""
            r[f"{s}_snapshots"] = len(seen[s])
    fields = ["niche_id", "matched", "verified"] + [f"{s}_{k}" for s in ("kwork", "fl") for k in
                                                    ("matched", "build", "service", "candidates", "budget_med", "budget_max",
                                                     "offers_med", "posts", "window", "snapshots")] + ["examples"]
    with open(ws.out("freelance.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    mfields = ["niche_id", "source", "id", "date", "label", "title", "budget", "budget_max", "currency", "offers", "category", "url"]
    with open(ws.out("freelance_matches.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=mfields)
        w.writeheader()
        w.writerows(sorted(matches, key=lambda m: (m["niche_id"], m["source"], m["date"])))
    if not use_llm:
        note = f"Matches are keyword candidates, NOT verified ({llm_note})."
    elif missing:
        note = f"Matches are LLM-checked (build + service count), but {missing} posts got no answer and are counted unverified."
    else:
        note = "Matches are LLM-checked: build + service count."
    write_report(ws, rows, stats, note, span)
    for r in sorted(rows, key=lambda r: -r["matched"]):
        if r["matched"] or r["kwork_candidates"] or r["fl_candidates"]:
            print(f"  {r['niche_id']:34} matched={r['matched']:3} kwork={r['kwork_matched']}/{r['kwork_candidates']} "
                  f"fl={r['fl_matched']}/{r['fl_candidates']} med_rub={r['kwork_budget_med'] or '-'}/{r['fl_budget_med'] or '-'}")
    print(f"-> freelance.csv ({len(rows)} niches, {sum(1 for r in rows if r['matched'])} with matches) | "
          f"matches {len(matches)} | history {len(hist)}")


def write_report(ws: Workspace, rows: list[dict], stats: dict, note: str, span: dict) -> None:
    lines = ["# S8: paid demand on Russian freelance exchanges", "",
             f"Run {ws.today}. Kwork requests {span['kwork'][0] if span['kwork'] else '-'}..{span['kwork'][-1] if span['kwork'] else '-'}, "
             f"FL.ru projects {span['fl'][0] if span['fl'] else '-'}..{span['fl'][-1] if span['fl'] else '-'} (history of all runs). "
             + note, ""]
    if stats:
        lines += [f"Kwork exchange in the last {stats.get('period')} days: {stats.get('projects')} requests, "
                  f"{stats.get('orders')} orders, {stats.get('value')} RUB.", ""]
    lines += ["| niche | matched | Kwork build/service | Kwork median RUB | FL build/service | FL median RUB | examples |",
              "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -r["matched"]):
        if not r["matched"]:
            continue
        lines.append(f"| {r['niche_id']} | {r['matched']} | {r['kwork_build']}/{r['kwork_service']} | {r['kwork_budget_med']} | "
                     f"{r['fl_build']}/{r['fl_service']} | {r['fl_budget_med']} | {r['examples'].replace('|', '/')} |")
    zero = [r["niche_id"] for r in rows if not r["matched"]]
    lines += ["", f"No paid demand found ({len(zero)}): " + ", ".join(zero), "",
              "Evidence only: this block never changes the S6 score or verdict."]
    ws.report("freelance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
