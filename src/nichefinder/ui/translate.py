"""Russian translation of the generated reports for `nf ui`: an LLM, cached per fragment.

The stages write their reports in English and the console shows them in Russian. A report is cut into fragments that
keep the Markdown structure (a heading, a paragraph, a list item, a quote, a table cell); each fragment is translated
once and stored in data/cache/ui_ru/, so after a re-run only the text that changed is paid for. A fragment that is
already Russian, a number, an identifier or an acronym is not sent. Code spans, URLs, link targets, HTML tags and
entities travel as placeholders that must come back untouched, and a translation whose digits differ from the source
is rejected: the fragment is retried alone, then stays English and is not asked again. The files on disk stay
English and nothing here feeds a stage.

The HTML leaderboard (s7_html) is translated the same way: the text of its page, the text fields of its rows and the
passports it embeds (re-rendered from the translated passport files); the few words inside its script come from
ru.LEADERBOARD_JS.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from nichefinder import keys, llm
from nichefinder.ui import ru
from nichefinder.workspace import Workspace

VERSION = "4"        # in every cache key: bump it when the prompt or the checks change
KEEP = "\x00"        # cached marker: the translation failed its checks, show the source
BATCH_CHARS = 3500
BATCH_ITEMS = 40
PARALLEL = 8
CALLS = threading.BoundedSemaphore(12)   # LLM calls in flight across all jobs

SYSTEM = """You translate fragments of a market-research report (niche screening for a software or info product) \
from English into Russian.
Input: JSON {"items": [...]}. Output: JSON {"t": [...]} with exactly one translation per item, in the same order.
Rules:
- Keep exactly as in the source: every number, percent, currency amount, date and range; placeholders like ⟦0⟧; \
codes and flags such as P1:platform-partial, G2:top1, S5:manual, E:churn; niche ids, stage and file names; brand, \
product, company, app, site and channel names; Markdown markers (**, _); the values of geo (global, both, ru) and of \
side (b2c, b2b-smb, b2b-mid, prosumer).
- Translate everything else into natural, concise Russian, as an analyst would write it. Short table headers and \
labels stay short.
- Text inside quotation marks is translated as well, e.g. "too expensive for what it does" -> "слишком дорого за то, \
что он делает", and stays in quotation marks; only a quote that is already Russian stays as it is.
- Verdict words: UP - рост, DOWN - спад, FLAT - ровно, PASS - пройден, FAIL - не пройден, NA - нет данных.
- Terms: niche - ниша, score - балл, gate - гейт, verdict - вердикт, green/yellow/red - зелёный/жёлтый/красный, \
shortlist - шорт-лист, passport - паспорт, leaderboard - лидерборд, demand - спрос, supply - предложение, \
players - игроки, buyer voice - голос покупателя, path-to-goal - путь к цели, ticket (price tier) - чек, \
founder fit - соответствие основателю, tier - тир, control niche - контрольная ниша, evidence - справочно, \
payers - платящие клиенты, churn - отток.
- Do not add, drop, explain or merge anything. A fragment already in Russian comes back unchanged. Never put a line \
break or the character | into a translation."""

# Niche names (niches.yaml) are asked apart: next to report text the model takes them for product names.
NICHE_NOTE = """
Every item is the name of a market niche (who does what task with which kind of product), not the name of a product: \
translate it into a short Russian niche name. Keep brand names in it (Mint, Shopify, TCG) and tags in square brackets \
such as [control red] as they are."""

PROTECT = re.compile(r"`[^`\n]+`|https?://[^\s)|>\]]+|\]\([^)\s]*\)|<[^<>\n]+>|&[#\w]+;")
PLACEHOLDER = re.compile(r"⟦(\d+)⟧")
CYR = re.compile("[\u0400-\u04FF]")
LAT = re.compile("[A-Za-z]")
WORD = re.compile("[A-Za-z]{2,}")
QUOTED = re.compile(r'"[^"]*"|“[^”]*”|«[^»]*»')
PIPE = re.compile(r"(?<!\\)\|")
THOUSANDS = re.compile("(?<=\\d)[,\u00a0\u202f\u2009 ](?=\\d{3}(?!\\d))")


def wanted(text: str) -> bool:
    """Does this fragment need a translation? Russian text, numbers, identifiers and acronyms do not."""
    s = text.strip()
    if s in ru.GLOSSARY:
        return True
    t = PROTECT.sub(" ", s)

    def english(x: str) -> bool:
        return bool(WORD.search(x)) and len(LAT.findall(x)) > len(CYR.findall(x))
    if not (english(t) or english(QUOTED.sub(" ", t))):   # English text around long Russian quotes counts too
        return False
    if " " not in t.strip():
        core = t.strip().strip(".,;:!?()[]*_\"'«»")
        if re.search(r"[_:@#]|\w\.\w", core) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", core):
            return False   # travel-esim-apps, P1:platform-partial, s5_serp, saily.com
        if core.isupper() and len(core) <= 5:
            return False   # CPC, HHI, NA
    return True


def _protect(text: str) -> tuple[str, list[str]]:
    keep: list[str] = []

    def sub(m: re.Match) -> str:
        keep.append(m.group(0))
        return f"⟦{len(keep) - 1}⟧"
    return PROTECT.sub(sub, text), keep


def _restore(text: str, keep: list[str]) -> str:
    return PLACEHOLDER.sub(lambda m: keep[int(m[1])], text)


BOLD_VERDICT = re.compile(r"\*\*(UP|DOWN|FLAT|PASS|FAIL)\*\*")
CONTROL_TAG = re.compile(r"\[(?:control|контрол\w*):?\s+(red|green|yellow|platform|красн\w*|зел\w*|жёлт\w*|желт\w*|платф\w*)\]",
                         re.I)


def polish(out: str) -> str:
    """Fixed wording applied to every cached translation when it is read, so a change here needs no new calls:
    bold verdict words and top-N positions the model left in English, and one form of the control-niche tag."""
    out = BOLD_VERDICT.sub(lambda m: f"**{ru.VERDICT_WORDS[m[1]]}**", out)
    out = re.sub(r"\btop-(\d+)\b", r"топ-\1", out)   # the path-to-goal positions (s6_ceiling)
    return CONTROL_TAG.sub(lambda m: f"[контроль: {ru.CONTROL_TAGS[m[1][:3].lower()]}]", out)


def _finish(out: str, keep: list[str]) -> str:
    return _restore(" ".join(out.split()), keep)


def _digits(s: str) -> list[str]:
    return sorted(re.findall(r"\d+", THOUSANDS.sub("", PLACEHOLDER.sub("", s))))


def english_quote(text: str) -> bool:
    """A quotation of four or more English words: the model sometimes leaves buyer quotes untranslated."""
    return any(len(WORD.findall(q)) >= 4 and not CYR.search(q) for q in QUOTED.findall(text))


def checked(src: str, out: object, n_keep: int, strict: bool = False) -> bool:
    """A translation keeps every placeholder once, the digits of the source and its table pipes; strict also wants
    no English quote left where the source had one."""
    if not isinstance(out, str) or not out.strip():
        return False
    if strict and english_quote(src) and english_quote(out):
        return False
    found = PLACEHOLDER.findall(out)
    if sorted(found) != sorted(str(i) for i in range(n_keep)):
        return False
    if len(PIPE.findall(out)) != len(PIPE.findall(src)):
        return False
    return _digits(src) == _digits(out)


class Translator:
    def __init__(self, ws: Workspace):
        self.ws = ws
        self.dir = ws.cache("ui_ru")
        self.model = llm.config(ws)["model"]
        self.names: set[str] = set()   # niche names from niches.yaml: translated as names (NICHE_NOTE)

    def _path(self, text: str):
        kind = "niche|" if text in self.names else ""
        h = hashlib.sha1(f"{VERSION}|{kind}{self.model}|{text}".encode()).hexdigest()
        return self.dir / h[:2] / f"{h}.txt"

    def lookup(self, text: str) -> str | None:
        """The Russian text; the source when it needs none or failed; None when it is not translated yet."""
        s = text.strip()
        if s in ru.GLOSSARY:
            return ru.GLOSSARY[s]
        if not wanted(s):
            return text
        try:
            out = self._path(s).read_text(encoding="utf-8")
        except OSError:
            return None
        return text if out == KEEP else polish(out)

    def get(self, text: str) -> str:
        out = self.lookup(text)
        return text if out is None else out

    def missing(self, texts) -> list[str]:
        seen: set[str] = set()
        out = []
        for t in texts:
            s = (t or "").strip()
            if s and s not in seen and self.lookup(s) is None:
                seen.add(s)
                out.append(s)
        return out

    def _store(self, text: str, out: str) -> None:
        p = self._path(text)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out, encoding="utf-8")

    def _call(self, items: list[str], niche: bool = False) -> list | None:
        msgs = [{"role": "system", "content": SYSTEM + (NICHE_NOTE if niche else "")},
                {"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False)}]
        with CALLS:
            content, _, _ = llm.chat_json(self.ws, msgs, max_tokens=8000, temperature=0.1, tries=2,
                                          cache_namespace="ui_ru_llm")
        t = content.get("t") if isinstance(content, dict) else None
        return t if isinstance(t, list) and len(t) == len(items) else None

    def _batch(self, batch: list[str]) -> None:
        prot = [_protect(t) for t in batch]
        outs = self._call([p for p, _ in prot], niche=all(t in self.names for t in batch))
        if outs is None:
            if len(batch) > 1:   # a truncated or malformed answer: smaller requests
                half = len(batch) // 2
                self._batch(batch[:half])
                self._batch(batch[half:])
            return   # one fragment and no answer: asked again on the next open
        # In a batch the check is strict; a fragment asked alone (the retry) may keep an English quote, which is still
        # better than showing it all in English, but wrong digits or placeholders leave the source.
        for src, (p, keep), out in zip(batch, prot, outs):
            if checked(p, out, len(keep), strict=len(batch) > 1):
                self._store(src, _finish(out, keep))
            elif len(batch) == 1:
                self._store(src, KEEP)
            else:
                self._batch([src])

    def translate(self, texts, progress: Callable[[int], None] | None = None) -> list[str]:
        """Translate what is not cached yet; returns the errors of failed calls (their fragments stay English)."""
        todo = self.missing(texts)
        if not todo:
            return []
        keys.require("LLM_API_KEY", purpose="the Russian translation of reports")
        batches: list[list[str]] = []
        for group in ([t for t in todo if t in self.names], [t for t in todo if t not in self.names]):
            cur: list[str] = []
            size = 0
            for t in group:
                if cur and (size + len(t) > BATCH_CHARS or len(cur) >= BATCH_ITEMS):
                    batches.append(cur)
                    cur, size = [], 0
                cur.append(t)
                size += len(t)
            if cur:
                batches.append(cur)
        errors: list[str] = []

        def work(batch: list[str]) -> None:
            try:
                self._batch(batch)
            except Exception as e:  # noqa: BLE001 - one batch failing leaves its fragments English
                errors.append(f"{type(e).__name__}: {e}"[:200])
            if progress:
                progress(len(batch))
        with ThreadPoolExecutor(PARALLEL) as pool:
            list(pool.map(work, batches))
        return errors


class Jobs:
    """Background translations, one per text set (a report, the leaderboard, the niche names of a profile)."""

    RETRY_AFTER = 60   # seconds before a finished job with fragments left may run again

    def __init__(self, tr: Translator):
        self.tr = tr
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}

    def ensure(self, key: str, texts) -> dict:
        """{"status": "running", "done", "total"} while translating, else {"status": "ready", "error"}."""
        with self.lock:
            j = self.jobs.get(key)
            if j and j["status"] == "running":
                return dict(j)
            todo = self.tr.missing(texts)
            if not todo or (j and time.time() - j["ended"] < self.RETRY_AFTER):
                return {"status": "ready", "error": (j or {}).get("error", "") if todo else ""}
            j = {"status": "running", "done": 0, "total": len(todo), "error": "", "ended": 0.0}
            self.jobs[key] = j
        threading.Thread(target=self._run, args=(j, todo), daemon=True).start()
        return dict(j)

    def _run(self, j: dict, todo: list[str]) -> None:
        def step(n: int) -> None:
            with self.lock:
                j["done"] += n
        try:
            errors = self.tr.translate(todo, step)
            j["error"] = errors[0] if errors else ""
        except Exception as e:  # noqa: BLE001 - a missing key or a dead network: the text stays English
            j["error"] = ru.why(str(e)) or type(e).__name__
        finally:
            with self.lock:
                j["status"] = "ready"
                j["ended"] = time.time()


def text_key(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:16]


# ---- Markdown -------------------------------------------------------------------------------------------------

FENCE = re.compile(r"^\s*```")
HR = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
HEAD = re.compile(r"^(\s*#{1,6}\s+)(.*)$")
ITEM = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$")
QUOTE = re.compile(r"^(\s*>\s?)(.*)$")
SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _block_start(line: str) -> bool:
    return bool(FENCE.match(line) or HR.match(line) or HEAD.match(line) or ITEM.match(line) or QUOTE.match(line)
                or line.lstrip().startswith("|"))


def split(md: str) -> tuple[list[list], list[str]]:
    """Cut Markdown into a skeleton (lines of literal pieces and fragment indices) and the fragments to translate.
    join(skeleton, fragments, get) rebuilds it; lines of one paragraph, quote or list item become one line."""
    lines = md.replace("\r\n", "\n").split("\n")
    units: list[str] = []
    rows: list[list] = []

    def piece(text: str) -> list:
        s = text.strip()
        if wanted(s):
            units.append(s)
            return [len(units) - 1]
        return [s]

    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if FENCE.match(ln):
            rows.append([ln])
            i += 1
            while i < n and not FENCE.match(lines[i]):
                rows.append([lines[i]])
                i += 1
            if i < n:
                rows.append([lines[i]])
                i += 1
            continue
        if not ln.strip() or HR.match(ln) or SEP.match(ln):
            rows.append([ln])
            i += 1
            continue
        if ln.lstrip().startswith("|"):
            lead, body = ln[:len(ln) - len(ln.lstrip())], ln.strip()
            closed = len(body) > 1 and body.endswith("|") and not body.endswith("\\|")
            cells = PIPE.split(body[1:-1] if closed else body[1:])
            row: list = [lead, "|"]
            for k, c in enumerate(cells):
                row += [" ", *piece(c), " "]
                if k < len(cells) - 1 or closed:
                    row.append("|")
            rows.append(row)
            i += 1
            continue
        m = HEAD.match(ln)
        if m:
            rows.append([m[1], *piece(m[2])])
            i += 1
            continue
        m = QUOTE.match(ln)
        if m:
            prefix, text = m[1], m[2]
            i += 1
            while i < n and QUOTE.match(lines[i]) and QUOTE.match(lines[i])[2].strip():
                text += " " + QUOTE.match(lines[i])[2].strip()
                i += 1
            rows.append([prefix, *piece(text)])
            continue
        m = ITEM.match(ln)
        if m:
            prefix, text = m[1], m[2]
            i += 1
            while i < n and lines[i].startswith("  ") and lines[i].strip() and not _block_start(lines[i]):
                text += " " + lines[i].strip()
                i += 1
            rows.append([prefix, *piece(text)])
            continue
        lead, text = ln[:len(ln) - len(ln.lstrip())], ln.strip()
        i += 1
        while i < n and lines[i].strip() and not _block_start(lines[i]):
            text += " " + lines[i].strip()
            i += 1
        rows.append([lead, *piece(text)])
    return rows, units


def join(rows: list[list], units: list[str], get: Callable[[str], str]) -> str:
    return "\n".join("".join(get(units[p]) if isinstance(p, int) else p for p in row) for row in rows)


# ---- the HTML leaderboard -------------------------------------------------------------------------------------

BOARD_FIELDS = ("name", "who", "note", "ptgt", "poslow", "rvt", "qvt", "yvt", "tvt", "kp", "gt", "yt", "rv", "qv", "yv",
                "tv")
SIDES_CONST = re.compile(r"const SIDES=(\[[^\]]*\])")
TEXT_NODE = re.compile(r">([^<>]*[A-Za-z]{2,}[^<>]*)<")
RAW = re.compile(r"<(style|script)\b.*?(?:</\1>|$)", re.S | re.I)
DATA_START, DATA_END = "const DATA=", ";\nconst SIDES="


def board_parts(page: str) -> tuple[str, list[dict], str] | None:
    """(page before the data, the rows, page after the data), or None for a page of an unknown shape."""
    a = page.find(DATA_START)
    b = page.find(DATA_END, a)
    if a < 0 or b < 0:
        return None
    try:
        rows = json.loads(page[a + len(DATA_START):b])
    except ValueError:
        return None
    return page[:a + len(DATA_START)], rows if isinstance(rows, list) else [], page[b:]


def _html_texts(html: str) -> list[str]:
    out = []
    pos = 0
    for m in list(RAW.finditer(html)) + [None]:
        seg = html[pos:m.start() if m else len(html)]
        out += [t.group(1).strip() for t in TEXT_NODE.finditer(seg) if wanted(t.group(1))]
        if m:
            pos = m.end()
    return out


def _html_apply(html: str, get: Callable[[str], str]) -> str:
    def node(m: re.Match) -> str:
        t = m.group(1)
        if not wanted(t):
            return m.group(0)
        lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
        return ">" + lead + get(t.strip()) + trail + "<"
    out, pos = [], 0
    for m in RAW.finditer(html):
        out += [TEXT_NODE.sub(node, html[pos:m.start()]), m.group(0)]
        pos = m.end()
    out.append(TEXT_NODE.sub(node, html[pos:]))
    return "".join(out)


def board_texts(head: str, rows: list[dict], passports: dict[str, tuple[list, list[str]]]) -> list[str]:
    texts = _html_texts(head)
    for r in rows:
        texts += [str(r[f]) for f in BOARD_FIELDS if isinstance(r.get(f), str) and r[f]]
    for _, units in passports.values():
        texts += units
    return texts


def board_page(head: str, rows: list[dict], tail: str, passports: dict[str, tuple[list, list[str]]],
               get: Callable[[str], str], md_to_html: Callable[[str], str]) -> str:
    out_rows = []
    for r in rows:
        r = dict(r)
        for f in BOARD_FIELDS:
            if isinstance(r.get(f), str) and r[f]:
                r[f] = get(r[f])
        if r.get("id") in passports:
            skel, units = passports[r["id"]]
            r["md"] = md_to_html(join(skel, units, get))
        r["side"] = ru.BOARD_SIDES.get(r.get("side"), r.get("side"))   # the filter chips use the same labels
        out_rows.append(r)
    head = _html_apply(head, get).replace('<html lang="en">', '<html lang="ru">')
    for en, ru_text in ru.LEADERBOARD_JS:
        tail = tail.replace(en, ru_text)
    tail = SIDES_CONST.sub(lambda m: "const SIDES=" + json.dumps(
        [ru.BOARD_SIDES.get(s, s) for s in json.loads(m[1])], ensure_ascii=False), tail, count=1)
    return head + json.dumps(out_rows, ensure_ascii=False).replace("</", "<\\/") + tail


def progress_page(done: int, total: int) -> str:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta http-equiv="refresh" content="2">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Перевожу лидерборд…</title>
<style>:root{{color-scheme:light dark}}body{{font:15px/1.5 system-ui,sans-serif;margin:0;padding:48px 20px}}
main{{max-width:560px;margin:0 auto}}.bar{{height:8px;border-radius:9px;background:#8883;overflow:hidden;margin:16px 0}}
.bar i{{display:block;height:100%;background:#3c8c7c;width:{100 * done / max(1, total):.0f}%}}a{{color:inherit}}</style>
</head><body><main><h1>Перевожу лидерборд на русский</h1><div class="bar"><i></i></div>
<p>Готово {done} из {total} фрагментов. Страница обновится сама; переведённое сохраняется, так что следующее
открытие будет мгновенным.</p><p><a href="?lang=en">Открыть английский оригинал</a></p></main></body></html>"""
