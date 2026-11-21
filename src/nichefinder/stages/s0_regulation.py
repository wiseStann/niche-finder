"""S0: new US / Russian regulations that create a recurring compliance task for small businesses or prosumers.

A discovery report for a human: a rule that obliges many small firms to file, report, register, label or certify
something creates demand before anyone searches for it. Nothing here is scored or written to niches.yaml; a candidate
becomes a niche only when the owner writes it (who x task x product) into niches.yaml and queries/.

Sources (no keys):
- US: Federal Register API, https://www.federalregister.gov/api/v1/documents.json, document types from
  config/regulation.yaml (`us.types`, default final and proposed rules), published within `window_months` before
  ws.today; fields title, abstract, action, dates, agencies, effective_on, significant, html_url. 1,000 per page,
  about 5 requests a year of history.
- RU (when nf.yaml markets include ru): the open-data API of regulation.gov.ru (the federal portal of draft
  regulations), https://regulation.gov.ru/api/npalist?limit=500&offset=N&sort=desc (XML, newest first; limit is capped
  at 500), walked until the publish date is older than the window: about 18 requests a year. Fields: title, kind,
  department, procedure, regulatoryImpact (degree from the regulatory impact assessment, ORV), problem, circlePersons
  (who is affected), socialRelations, objectives, transitionPeriod, planDate (planned adoption). It answers foreign IPs
  directly, so no proxy is used. Most drafts carry only a title there, so each selected draft also gets its passport
  from /api/public/PublicProjects/Print/<id> (economic activities, keywords, the mandatory-requirements flag, affected
  persons, problem, planned entry into force; one request per selected draft). publication.pravo.gov.ru (adopted acts)
  also answers (/api/Documents), but it gives titles only ("on amendments to resolution No. N"), too little for a
  classifier, so it is not read.

Prefilter (config/regulation.yaml): routine titles are dropped (airworthiness directives, safety zones, state air plans;
internal acts of the state apparatus); a document needs a compliance term, and its priority is the number of distinct
term hits plus a bonus for significant US rules and for the ORV impact degree and business addressees of RU drafts.
The top --max-docs by priority (split between the markets) go to the LLM (nichefinder.llm.chat_json, `batch`
documents per call, `workers` calls in parallel), which returns per document: creates_task (yes/no), recurring
(yes/no), who must comply, the task, the deadline, a product idea as who x task x product, a confidence and a reason.
Documents are batched by market and publication month, so a later run re-asks only the months whose selection changed.

Outputs: data/out/regulation_prefilter.csv (every document that passed the prefilter, `selected` = sent to the LLM;
written before any LLM call, also by --dry), data/out/regulation_candidates.csv (every selected document;
creates_task says which are candidates) and reports/S0-regulation.md (candidates grouped by market and confidence,
with deadline and link).
LLM failures: one probe call goes first; if it fails (HTTP 402 = empty LLM balance, a wrong key, the endpoint down),
the stage stops with a message and writes neither the candidates nor the report. If calls start failing later, it
stops after `workers` failures in a row, writes what was answered and marks the report INCOMPLETE. A re-run reads the
fetches, passports and answered batches from the cache.
Columns: market, doc_id, doc_type, published, agency, title, url, priority (prefilter), flag (US: significant; RU: ORV
impact degree and "mandatory requirements" when the passport says so), effective (US: effective date; RU: planned
adoption or entry into force), creates_task, recurring, who, task, deadline, idea_who, idea_task, idea_product,
confidence, why (all from the LLM; empty creates_task = the LLM gave no answer).
Cache: data/cache/federalregister (keyed by the query URL, which carries the fixed date window), data/cache/regulation_ru
(list pages and passports keyed by the run month: offsets shift as drafts are added), LLM answers in
data/cache/llm_regulation.
Cost: LLM only, about 300 documents in ~40 calls, ~0.3 M tokens per uncached run; --dry shows the selection, no calls.
Caveats: the US abstract and the RU draft passport are short, so who and deadline are the LLM's reading of a summary,
not of the rule text; 2025-2026 US rules often remove obligations (creates_task no). Drafts may never be adopted.
Check the source before acting on a candidate.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from nichefinder import http, llm
from nichefinder.workspace import Workspace

SUMMARY = "New US / Russian regulations that create a compliance task for small businesses (discovery report, LLM)"
KEYS: tuple[str, ...] = ("LLM_API_KEY",)
NEEDS: tuple[str, ...] = ()

FR_API = "https://www.federalregister.gov/api/v1/documents.json"
FR_FIELDS = ["title", "abstract", "action", "dates", "agencies", "effective_on", "html_url", "significant",
             "document_number", "publication_date", "type"]
RU_API = "https://regulation.gov.ru/api/npalist"
RU_PRINT = "https://regulation.gov.ru/api/public/PublicProjects/Print/"
RU_PAGE = 500
# fields of a draft's passport (the Print endpoint) passed to the LLM, by the start of their label; contact details of
# the officials in the passport are never read
PASSPORT = {
    "Виды экономической деятельности": "Economic activities",
    "Ключевые слова": "Keywords",
    "Обязательные требования (КНД)": "Sets mandatory requirements",
    "Круг лиц": "Affected",
    "Краткое описание проблемы": "Problem",
    "Общая характеристика": "Relations",
    "Цели": "Objectives",
    "Переходный период": "Transition period",
    "Планируемый срок вступления": "Planned entry into force",
}
YES_RU = "да"
PRE_COLS = ["market", "doc_id", "doc_type", "published", "agency", "title", "url", "priority", "flag", "effective", "selected"]
COLS = ["market", "doc_id", "doc_type", "published", "agency", "title", "url", "priority", "flag", "effective",
        "creates_task", "recurring", "who", "task", "deadline", "idea_who", "idea_task", "idea_product", "confidence", "why"]

PROMPT = """You screen government regulations for product opportunities for a solo founder.
For each document decide whether it creates a NEW or CHANGED obligation that small businesses, sole proprietors,
self-employed people, landlords, creators or other prosumers must carry out themselves: file, report, keep records,
register, label, certify, disclose, train staff, inspect, submit data, renew, notify. A recurring task (monthly,
yearly, per transaction, per hire) is the strongest signal.
Answer creates_task "no" when the document removes or relaxes an obligation, only concerns government bodies,
only large corporations or a few dozen firms in one industry, only sets prices, fees, quotas or tariffs, or has no
concrete obligation yet.
Return JSON {"r": [{"i": <document index>, "creates_task": "yes"|"no", "recurring": "yes"|"no",
"who": "<who must comply, concrete and short>", "task": "<what they must now do, one sentence>",
"deadline": "<compliance or effective date as YYYY-MM-DD, or a short phrase, or empty>",
"idea_who": "<buyer>", "idea_task": "<the job the rule creates>", "idea_product": "<a product a solo founder could sell:
SaaS, mobile app, template pack, guide, plugin or done-for-you service>",
"confidence": "high"|"medium"|"low", "why": "<one short sentence>"}]}
one item per document. Write in English, also for Russian documents. Leave the idea fields empty when creates_task is
"no". confidence is high only when the text names the obligation and who carries it."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-docs", type=int, default=None, help="documents to classify (default: max_docs in config/regulation.yaml)")
    parser.add_argument("--markets", default="", help="comma-separated us,ru (default: from nf.yaml markets)")
    parser.add_argument("--workers", type=int, default=None, help="parallel LLM calls (default: workers in the config)")
    parser.add_argument("--dry", action="store_true", help="fetch and prefilter only; list the selection, no LLM calls")


def _clean(s, limit: int = 0) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:limit] if limit else s


def _any(patterns) -> re.Pattern | None:
    pats = [p for p in (patterns or []) if p]
    return re.compile("|".join(f"(?:{p})" for p in pats), re.I) if pats else None


def term_hits(text: str, terms: list[re.Pattern]) -> int:
    """Number of distinct compliance terms present in the text."""
    return sum(1 for t in terms if t.search(text))


# ---- US: Federal Register --------------------------------------------------------

def fetch_us(ws: Workspace, types: list[str], since: str, until: str) -> list[dict]:
    docs: list[dict] = []
    for typ in types:
        params = [("per_page", "1000"), ("order", "newest"), ("conditions[type][]", typ),
                  ("conditions[publication_date][gte]", since), ("conditions[publication_date][lte]", until)]
        params += [("fields[]", f) for f in FR_FIELDS]
        url: str | None = FR_API + "?" + urllib.parse.urlencode(params)
        n, pages = 0, 0
        while url and pages < 30:
            d = http.get_json(url, cache=ws.cache("federalregister"), timeout=120, sleep=1.0, user_agent=http.BOT_UA)
            for x in d.get("results") or []:
                docs.append(x)
                n += 1
            url = d.get("next_page_url")
            pages += 1
        print(f"  Federal Register {typ}: {n} documents {since} .. {until}")
    return docs


def us_row(x: dict) -> dict:
    agencies = [a.get("name") or a.get("raw_name") or "" for a in (x.get("agencies") or [])]
    return {"market": "us", "doc_id": x.get("document_number", ""),
            "doc_type": {"Rule": "final rule", "Proposed Rule": "proposed rule"}.get(x.get("type", ""), x.get("type", "")),
            "published": x.get("publication_date", ""), "agency": "; ".join(a for a in agencies if a)[:120],
            "title": _clean(x.get("title"), 300), "url": x.get("html_url", ""),
            "flag": "significant" if x.get("significant") else "", "effective": x.get("effective_on") or "",
            "_text": (f"Action: {_clean(x.get('action'))}\nDates: {_clean(x.get('dates'), 400)}\n"
                      f"Abstract: {_clean(x.get('abstract'), 1500)}")}


def us_priority(x: dict, cfg: dict) -> int:
    """0 drops the document; otherwise distinct term hits plus the significance bonus."""
    title = x.get("title") or ""
    exc = _any(cfg.get("exclude_title"))
    if exc and exc.search(title):
        return 0
    terms = [re.compile(t, re.I) for t in cfg.get("terms") or []]
    hits = term_hits(f"{title} {x.get('action') or ''} {x.get('abstract') or ''}", terms)
    if not hits:
        return 0
    return hits + (int(cfg.get("significant_bonus", 2)) if x.get("significant") else 0)


# ---- RU: regulation.gov.ru ---------------------------------------------------------

def parse_npalist(xml_text: str) -> list[dict]:
    """Projects of one npalist XML page: tag -> text (attribute ids dropped), plus `id`."""
    root = ET.fromstring(xml_text)
    out = []
    for p in root.iter("project"):
        d = {c.tag: _clean(c.text) for c in p}
        d["id"] = p.get("id", "")
        out.append(d)
    return out


def fetch_ru(ws: Workspace, since: str, until: str, stamp: str, max_pages: int = 40) -> list[dict]:
    docs: list[dict] = []
    for page in range(max_pages):
        offset = page * RU_PAGE
        text = http.get_text(f"{RU_API}?limit={RU_PAGE}&offset={offset}&sort=desc", cache=ws.cache("regulation_ru"),
                             cache_key=f"npalist_{stamp}_o{offset}", ext=".xml", hashed=False, timeout=120,
                             min_size=2_000, sleep=1.0, user_agent=http.BOT_UA)
        try:
            rows = parse_npalist(text)
        except ET.ParseError as e:
            print(f"  ! regulation.gov.ru offset {offset}: not XML ({e}): {text[:120]!r}")
            break
        if not rows:
            break
        dates = [r.get("publishDate", "")[:10] or r.get("date", "")[:10] for r in rows]
        docs += [r for r, d in zip(rows, dates) if since <= d <= until]
        if min((d for d in dates if d), default="") < since:
            break
    print(f"  regulation.gov.ru: {len(docs)} draft projects {since} .. {until}")
    return docs


def ru_row(x: dict, orv_procedure: str = "") -> dict:
    planned = x.get("planDate", "")[:10]
    parts = [f"Kind: {x.get('kind', '')}", f"Procedure: {x.get('procedure', '')}",
             f"Regulatory impact: {x.get('regulatoryImpact', '')}", f"Status: {x.get('status', '')}",
             f"Planned adoption: {planned}"]
    for key, label in (("problem", "Problem"), ("circlePersons", "Affected"), ("socialRelations", "Relations"),
                       ("objectives", "Objectives"), ("transitionPeriod", "Transition period")):
        if x.get(key) and x[key] != "-":
            parts.append(f"{label}: {_clean(x[key], 700)}")
    return {"market": "ru", "doc_id": x.get("projectId") or x.get("id", ""), "doc_type": x.get("kind", ""),
            "published": (x.get("publishDate") or x.get("date", ""))[:10], "agency": x.get("department", ""),
            "title": _clean(x.get("title"), 300), "url": f"https://regulation.gov.ru/projects/{x.get('id', '')}",
            "flag": x.get("regulatoryImpact", "") if orv_procedure and x.get("procedure") == orv_procedure else "",
            "effective": planned, "_id": x.get("id", ""),
            "_text": "\n".join(parts)}


def ru_priority(x: dict, cfg: dict) -> int:
    """0 drops the draft; otherwise the ORV impact weight, distinct term hits and the business-addressee bonus."""
    title = x.get("title", "")
    exc = _any(cfg.get("exclude_title"))
    if (exc and exc.search(title)) or x.get("procedure", "") in (cfg.get("exclude_procedures") or []):
        return 0
    score = 0
    if x.get("procedure") == cfg.get("orv_procedure"):
        score += int((cfg.get("impact_weight") or {}).get(x.get("regulatoryImpact", ""), cfg.get("orv_unrated_weight", 1)))
    terms = [re.compile(t, re.I) for t in cfg.get("terms") or []]
    score += term_hits(" ".join(x.get(k, "") for k in ("title", "problem", "circlePersons", "socialRelations")), terms)
    biz = cfg.get("business")
    if score and biz and re.search(biz, x.get("circlePersons", ""), re.I):
        score += int(cfg.get("business_bonus", 1))
    return score


def parse_passport(d: dict) -> dict[str, str]:
    """English label -> text for the PASSPORT fields of a Print answer (blocks of {description, values})."""
    out: dict[str, str] = {}
    for block in (d or {}).get("blocks") or []:
        for v in block.get("values") or []:
            label = str(v.get("description") or "").strip()
            key = next((en for ru, en in PASSPORT.items() if label.startswith(ru)), None)
            if not key or key in out:
                continue
            flat: list[str] = []
            for x in v.get("values") or []:
                flat += [str(y) for y in x] if isinstance(x, list) else ([str(x)] if x is not None else [])
            text = _clean("; ".join(flat), 700)
            if text and text != "-":
                out[key] = text[:10] if key == "Planned entry into force" else text
    return out


def enrich_ru(ws: Workspace, rows: list[dict], stamp: str) -> int:
    """Add the passport of each selected Russian draft to its LLM text; returns how many passports were read."""
    n = 0
    for r in rows:
        if not r.get("_id"):
            continue
        try:
            d = http.get_json(RU_PRINT + r["_id"], cache=ws.cache("regulation_ru"), cache_key=f"print_{stamp}_{r['_id']}",
                              hashed=False, timeout=60, sleep=0.5, user_agent=http.BOT_UA)
        except (http.HttpError, OSError, ValueError) as e:
            print(f"  ! passport {r['_id']}: {str(e)[:120]}")
            continue
        pp = parse_passport(d)
        extra = [f"{k}: {v}" for k, v in pp.items() if f"{k}: " not in r["_text"] and k != "Planned entry into force"]
        if extra:
            r["_text"] += "\n" + "\n".join(extra)
        if pp.get("Planned entry into force") and not r["effective"]:
            r["effective"] = pp["Planned entry into force"]
        if pp.get("Sets mandatory requirements", "").lower().startswith(YES_RU):
            r["flag"] = (r["flag"] + "; " if r["flag"] else "") + "mandatory requirements"
        n += 1
    return n


# ---- selection and classification ---------------------------------------------------

def select(pools: dict[str, list[dict]], max_docs: int) -> dict[str, list[dict]]:
    """Split max_docs evenly between the markets (a market with fewer candidates leaves its share to the others) and take
    the highest priorities, newest first among equals."""
    for rows in pools.values():
        rows.sort(key=lambda r: (r["priority"], r["published"]), reverse=True)
    left, out = max_docs, {m: [] for m in pools}
    active = [m for m in pools if pools[m]]
    while left > 0 and active:
        share = max(1, left // len(active))
        for m in list(active):
            taken = len(out[m])
            add = pools[m][taken:taken + share]
            out[m] += add
            left -= len(add)
            if taken + share >= len(pools[m]) or not add:
                active.remove(m)
            if left <= 0:
                break
    return out


def batches(rows: list[dict], size: int) -> list[list[dict]]:
    """Batches of at most `size` documents within one market and one publication month, in a stable order, so a
    shifted window or a new document changes only the batches of its own month."""
    by: dict[tuple, list[dict]] = {}
    for r in rows:
        by.setdefault((r["market"], r["published"][:7]), []).append(r)
    out = []
    for k in sorted(by):
        grp = sorted(by[k], key=lambda r: (r["published"], r["doc_id"]))
        out += [grp[i:i + size] for i in range(0, len(grp), size)]
    return out


def doc_block(i: int, r: dict) -> str:
    head = {"us": f"US {r['doc_type']}", "ru": f"Russian draft regulation ({r['doc_type']})"}[r["market"]]
    meta = [f"Agency: {r['agency']}", f"Published: {r['published']}"]
    if r["market"] == "us":
        meta += [f"Effective: {r['effective'] or 'n/a'}", f"Significant: {'yes' if r['flag'] else 'no'}"]
    return f"[{i}] {head} | " + " | ".join(meta) + f"\nTitle: {r['title']}\n{r['_text']}"


def classify(ws: Workspace, chunk: list[dict], tries: int = 4) -> tuple[dict[int, dict] | None, bool, dict | None]:
    """Answers by document index; None when the LLM call failed (network, HTTP 402 empty balance, malformed JSON)."""
    user = "\n\n".join(doc_block(i, r) for i, r in enumerate(chunk))
    res, hit, usage = llm.chat_json(ws, [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
                                    max_tokens=400 + 260 * len(chunk), temperature=0.0, tries=tries,
                                    cache_namespace="llm_regulation")
    if res is None:
        return None, hit, usage
    out: dict[int, dict] = {}
    for item in (res or {}).get("r") or []:
        try:
            i = int(item.get("i"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= i < len(chunk):
            out[i] = item
    return out, hit, usage


def apply(r: dict, item: dict | None, failed: bool = False) -> dict:
    yes = lambda v: "yes" if str(v).strip().lower() in ("yes", "true", "1") else "no"  # noqa: E731
    row = {k: r.get(k, "") for k in COLS}
    if item is None:
        row.update(creates_task="", why="not classified: the LLM call failed, re-run the stage" if failed
                   else "the LLM gave no answer for this document")
        return row
    row.update(creates_task=yes(item.get("creates_task")), recurring=yes(item.get("recurring")),
               who=_clean(item.get("who"), 200), task=_clean(item.get("task"), 300), deadline=_clean(item.get("deadline"), 80),
               confidence=str(item.get("confidence") or "").lower(), why=_clean(item.get("why"), 300))
    if row["creates_task"] == "yes":
        row.update(idea_who=_clean(item.get("idea_who"), 150), idea_task=_clean(item.get("idea_task"), 200),
                   idea_product=_clean(item.get("idea_product"), 250))
    else:
        row["recurring"] = "no"
    return row


# ---- report --------------------------------------------------------------------------

CONF_ORDER = {"high": 0, "medium": 1, "low": 2}


def _md(s: str) -> str:
    return str(s or "").replace("|", "/").replace("\n", " ")


def report(ws: Workspace, rows: list[dict], stats: dict) -> str:
    lines = [f"# S0 regulation: new compliance tasks for small businesses ({ws.today.isoformat()})", "",
             "Discovery list for a human, not a verdict: a rule that makes many small firms file, report, register, label",
             "or certify something creates demand before it shows in search. Nothing here is scored or added to",
             "niches.yaml; check the source document before writing a niche (who x task x product).", "",
             f"Window: {stats['since']} .. {stats['until']}. " + "; ".join(
                 f"{m.upper()}: {s['fetched']} fetched, {s['prefiltered']} passed the prefilter, {s['classified']} classified, "
                 f"{s['yes']} create a task" for m, s in stats["markets"].items()) + ".",
             f"LLM: {stats['calls']} calls ({stats['cached']} from cache), uncached tokens in {stats['tin']:,}, out {stats['tout']:,}.", ""]
    if stats.get("failed"):
        lines[2:2] = [f"**INCOMPLETE: {stats['failed']} selected documents were not classified because LLM calls failed. "
                      "Re-run the stage: answered batches come from the cache.**", ""]
    for m, label in (("us", "United States (Federal Register)"), ("ru", "Russia (regulation.gov.ru drafts)")):
        cand = [r for r in rows if r["market"] == m and r["creates_task"] == "yes"]
        if m not in stats["markets"]:
            continue
        lines += [f"## {label}: {len(cand)} candidates", ""]
        if not cand:
            lines += ["No classified document creates a task.", ""]
            continue
        for conf in ("high", "medium", "low"):
            grp = [r for r in cand if (r["confidence"] or "low") == conf]
            if not grp:
                continue
            grp.sort(key=lambda r: (r["recurring"] != "yes", r["deadline"] or "9999", r["published"]))
            lines += [f"### Confidence {conf} ({len(grp)})", "",
                      "| Deadline | Recurring | Who must comply | Task | Product idea (who x task x product) | Source |",
                      "|---|---|---|---|---|---|"]
            for r in grp:
                idea = " x ".join(x for x in (r["idea_who"], r["idea_task"], r["idea_product"]) if x)
                src = f"[{_md(r['title'][:90])}]({r['url']}) ({_md(r['agency'][:40])}, {r['doc_type']}, {r['published']})"
                lines.append(f"| {_md(r['deadline'] or r['effective'])} | {r['recurring']} | {_md(r['who'])} | {_md(r['task'])} | "
                             f"{_md(idea)} | {src} |")
            lines.append("")
    lines += ["All classified documents, with the reason for each answer: data/out/regulation_candidates.csv.", ""]
    return "\n".join(lines)


# ---- run -------------------------------------------------------------------------------

def run(ws: Workspace, args: argparse.Namespace) -> None:
    cfg = ws.load_config("regulation.yaml", {}) or {}
    if not cfg:
        print("  config/regulation.yaml not found: copy it from the package examples (nf init writes it) - nothing done")
        return
    markets = [m.strip() for m in (args.markets or "").split(",") if m.strip()] or \
        [m for m, on in (("us", bool({"us", "ww"} & set(ws.markets))), ("ru", "ru" in ws.markets)) if on]
    until = ws.today.isoformat()
    since = (ws.today - dt.timedelta(days=round(float(cfg.get("window_months", 12)) * 30.44))).isoformat()
    stamp = f"{ws.today:%Y-%m}"
    pools: dict[str, list[dict]] = {}
    stats: dict = {"since": since, "until": until, "markets": {}}
    if "us" in markets:
        ucfg = cfg.get("us") or {}
        docs = fetch_us(ws, list(ucfg.get("types") or ["RULE"]), since, until)
        pool = []
        for x in docs:
            p = us_priority(x, ucfg)
            if p:
                pool.append({**us_row(x), "priority": p})
        pools["us"] = pool
        stats["markets"]["us"] = {"fetched": len(docs), "prefiltered": len(pool)}
    if "ru" in markets:
        rcfg = cfg.get("ru") or {}
        try:
            docs = fetch_ru(ws, since, until, stamp)
        except (http.HttpError, OSError) as e:
            print(f"  ! regulation.gov.ru: {e}")
            docs = []
        pool = []
        for x in docs:
            p = ru_priority(x, rcfg)
            if p:
                pool.append({**ru_row(x, rcfg.get("orv_procedure", "")), "priority": p})
        pools["ru"] = pool
        stats["markets"]["ru"] = {"fetched": len(docs), "prefiltered": len(pool)}
    if not pools:
        print("no market to read (nf.yaml markets has neither us/ww nor ru) - nothing done")
        return
    max_docs = args.max_docs if args.max_docs is not None else int(cfg.get("max_docs", 300))
    chosen = select(pools, max_docs)
    for m in pools:
        stats["markets"][m]["classified"] = len(chosen[m])
        print(f"  {m}: {stats['markets'][m]['fetched']} fetched, {len(pools[m])} passed the prefilter, "
              f"{len(chosen[m])} selected (lowest priority taken: {min((r['priority'] for r in chosen[m]), default='-')})")
    todo = [r for m in chosen for r in chosen[m]]
    chunks = batches(todo, max(1, int(cfg.get("batch", 10))))
    if not args.dry and chosen.get("ru"):
        print(f"  reading the passports of {len(chosen['ru'])} Russian drafts", flush=True)
        print(f"  passports read: {enrich_ru(ws, chosen['ru'], stamp)}")
    picked = {id(r) for r in todo}
    pre = ws.out("regulation_prefilter.csv")
    with open(pre, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PRE_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows({**r, "selected": int(id(r) in picked)} for m in pools for r in pools[m])
    print(f"-> {pre} (every document that passed the prefilter; selected = sent to the LLM)")
    if args.dry:
        for m in chosen:
            for r in chosen[m][:15]:
                print(f"    {m} p={r['priority']:2} {r['published']} {r['title'][:100]}")
        print(f"dry run: {len(todo)} documents in {len(chunks)} LLM calls would be classified")
        return
    if not chunks:
        print("nothing selected for the LLM - nothing classified")
        return
    workers = max(1, args.workers if args.workers is not None else int(cfg.get("workers", 4)))
    print(f"classifying {len(todo)} documents in {len(chunks)} LLM calls ({workers} in parallel, cached)", flush=True)
    # one probe call first: an empty LLM balance (HTTP 402) or a wrong key fails every call, so stop before the pool
    results: dict[int, tuple] = {0: classify(ws, chunks[0], tries=2)}
    if results[0][0] is None:
        print("LLM call failed (the 'llm retry' lines above say why; HTTP 402 = the LLM account balance is empty). "
              f"Nothing classified, no report written; {pre.name} holds the fetch and prefilter. Re-run after fixing: "
              "the fetches, passports and any answered batches come from the cache.")
        return
    stop, lock, fails = threading.Event(), threading.Lock(), [0]

    def work(k: int) -> tuple[int, tuple]:
        if stop.is_set():
            return k, (None, False, None)
        got = classify(ws, chunks[k])
        with lock:
            fails[0] = fails[0] + 1 if got[0] is None else 0
            if fails[0] >= workers:          # several failures in a row: the endpoint is down or out of balance
                stop.set()
        return k, got

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (k, got) in enumerate(pool.map(work, range(1, len(chunks))), 2):
            results[k] = got
            if n % 5 == 0 or n == len(chunks):
                done = sum(1 for g in results.values() if g[0] is not None)
                print(f"  {n}/{len(chunks)} calls ({done} answered)", flush=True)
    rows: list[dict] = []
    usage, calls, cached, failed = Counter(), 0, 0, 0
    for k, chunk in enumerate(chunks):
        got, hit, use = results[k]
        calls += int(got is not None)
        cached += int(bool(hit))
        if use and not hit:
            usage["in"] += use.get("prompt_tokens", 0)
            usage["out"] += use.get("completion_tokens", 0)
        if got is None:
            failed += len(chunk)
        rows += [apply(r, (got or {}).get(i), failed=got is None) for i, r in enumerate(chunk)]
    if stop.is_set():
        print(f"stopped after {workers} failed LLM calls in a row (HTTP 402 = the LLM account balance is empty); "
              f"{failed} documents left unclassified - re-run the stage after fixing, answered batches are cached")
    for m in pools:
        stats["markets"][m]["yes"] = sum(1 for r in rows if r["market"] == m and r["creates_task"] == "yes")
    stats.update(calls=calls, cached=cached, tin=usage["in"], tout=usage["out"], failed=failed)
    rows.sort(key=lambda r: (r["market"], r["creates_task"] != "yes", CONF_ORDER.get(r["confidence"], 3), -int(r["priority"])))
    out = ws.out("regulation_candidates.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    rep = ws.report("S0-regulation.md")
    rep.write_text(report(ws, rows, stats), encoding="utf-8")
    missing = sum(1 for r in rows if r["creates_task"] == "") - failed
    print(f"LLM: {calls} answered calls ({cached} cached), uncached tokens in {usage['in']:,}, out {usage['out']:,}"
          + (f"; {missing} documents without an answer" if missing else "")
          + (f"; {failed} documents not classified (failed calls)" if failed else ""))
    for m in pools:
        print(f"  {m}: {stats['markets'][m]['yes']} of {len(chosen[m])} selected documents create a task")
    print(f"-> {out}\n-> {rep}")
