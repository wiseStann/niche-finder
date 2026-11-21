"""Render docs/idea-sources.yaml -> docs/idea-sources.md and validate the registry schema.

The generated page starts with the hand-written docs/idea-sources-intro.md (when present),
followed by the queue of planned sources, a summary table and a per-group reference.

Run from anywhere:  python scripts/render_idea_sources.py
Edit only the YAML (and the intro); never the generated Markdown.
"""
import os
import re
import sys
from collections import Counter, defaultdict

import yaml

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "docs", "idea-sources.yaml")
INTRO = os.path.join(ROOT, "docs", "idea-sources-intro.md")
OUT = os.path.join(ROOT, "docs", "idea-sources.md")
STAGES_DIR = os.path.join(ROOT, "src", "nichefinder", "stages")

REQUIRED = ["id", "name", "group", "geo", "url", "role", "signals", "stages", "feeds", "freshness", "status", "adapter", "priority", "access", "caveats", "plan"]
ACCESS_REQUIRED = ["method", "endpoint", "auth", "cost", "limits", "probe"]
GEO = {"global", "ru", "both"}
ROLE = {"discovery", "evaluation", "voice", "trend"}
FRESH = {"realtime", "daily", "weekly", "monthly", "quarterly", "static"}
STATUS = {"in_pipeline", "planned", "manual", "blocked", "paid"}
PRIORITY = {"P1", "P2", "P3", "none"}
STATUS_ICON = {"in_pipeline": "✅", "planned": "🛠", "manual": "✋", "blocked": "⛔", "paid": "💰"}
GROUP_ORDER = ["launch", "funding", "community", "crowdfunding", "hiring", "vc_portfolio", "patents", "m_and_a", "store", "search",
               "ru_registry", "gov_stats", "web", "ads", "oss", "regulation", "info_market"]

with open(SRC, encoding="utf-8") as f:
    doc = yaml.safe_load(f)
groups, sources = doc["groups"], doc["sources"]


def adapters(s):
    """adapter field -> list of stage module names (str, list or null)."""
    ad = s.get("adapter")
    if not ad:
        return []
    return [ad] if isinstance(ad, str) else list(ad)


def adapter_text(s):
    ad = adapters(s)
    return ", ".join(f"`{a}`" for a in ad) if ad else "not implemented"


errors = []
warnings = []
ids = Counter(s["id"] for s in sources)
for i, s in enumerate(sources):
    sid = s.get("id", f"#{i}")
    for k in REQUIRED:
        if k not in s:
            errors.append(f"{sid}: missing field {k}")
    if s.get("group") not in groups:
        errors.append(f"{sid}: group={s.get('group')} is not in groups")
    if s.get("group") not in GROUP_ORDER:
        errors.append(f"{sid}: group={s.get('group')} is not in GROUP_ORDER")
    if s.get("geo") not in GEO:
        errors.append(f"{sid}: geo={s.get('geo')}")
    if not s.get("role") or not set(s.get("role")) <= ROLE:
        errors.append(f"{sid}: role={s.get('role')}")
    if s.get("freshness") not in FRESH:
        errors.append(f"{sid}: freshness={s.get('freshness')}")
    if s.get("status") not in STATUS:
        errors.append(f"{sid}: status={s.get('status')}")
    if s.get("priority") not in PRIORITY:
        errors.append(f"{sid}: priority={s.get('priority')}")
    if ids[sid] > 1:
        errors.append(f"{sid}: duplicate id")
    if not s.get("access"):
        errors.append(f"{sid}: empty access")
    for j, a in enumerate(s.get("access") or []):
        for k in ACCESS_REQUIRED:
            if k not in a:
                errors.append(f"{sid}: access[{j}] missing field {k}")
        pr = a.get("probe") or {}
        if "date" not in pr or "http" not in pr:
            errors.append(f"{sid}: access[{j}].probe without date/http")
    if s.get("status") == "in_pipeline" and not adapters(s):
        errors.append(f"{sid}: status in_pipeline but no adapter")
    if s.get("status") == "planned" and adapters(s):
        errors.append(f"{sid}: status planned but an adapter is set")
    # an adapter is a stage module name; missing modules are only a warning (stages may be added later)
    for a in adapters(s):
        if not re.fullmatch(r"[a-z0-9_]+", a):
            errors.append(f"{sid}: adapter {a} is not a stage module name")
        elif os.path.isdir(STAGES_DIR) and not os.path.exists(os.path.join(STAGES_DIR, a + ".py")):
            warnings.append(f"{sid}: stage module {a}.py not found in src/nichefinder/stages/")
if errors:
    print("SCHEMA ERRORS:")
    for e in errors:
        print("  ", e)
    sys.exit(1)
for w in warnings:
    print("warning:", w)

by_group = defaultdict(list)
for s in sources:
    by_group[s["group"]].append(s)
st = Counter(s["status"] for s in sources)
pr = Counter(s["priority"] for s in sources)


def best_access(s):
    """The most open access method: 200 without a key > 200 with a key > anything else."""
    def rank(a):
        http = str((a.get("probe") or {}).get("http"))
        free = a.get("auth") in ("none", None, "")
        return (0 if http == "200" and free else 1 if http == "200" else 2 if http.startswith("4") else 3, )
    return sorted(s["access"], key=rank)[0]


def esc(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def http_cell(a):
    p = a.get("probe") or {}
    return f"{p.get('http')} ({p.get('date')})"


lines = []
if os.path.exists(INTRO):
    with open(INTRO, encoding="utf-8") as f:
        lines.append(f.read().rstrip() + "\n")
    lines.append("---\n")
lines.append(f"# Registry of idea sources (v{doc['version']})\n")
lines.append("Generated from [`idea-sources.yaml`](idea-sources.yaml) by `scripts/render_idea_sources.py`. Edit only the YAML.\n")
lines.append(f"**{len(sources)} sources, {sum(len(s['access']) for s in sources)} access methods:** "
             + ", ".join(f"{STATUS_ICON[k]} {k} - {st[k]}" for k in ["in_pipeline", "planned", "manual", "blocked", "paid"] if st[k]) + ".  ")
lines.append("Priorities: " + ", ".join(f"{k} - {pr[k]}" for k in ["P1", "P2", "P3", "none"] if pr[k]) + ".\n")
lines.append("Legend. **Status:** ✅ a pipeline stage exists · 🛠 no stage yet (not implemented) · ✋ by hand / browser only · ⛔ closed from the probing network · 💰 paid only. "
             "**Probe:** the HTTP code of a keyless curl probe (date). "
             "**Role:** discovery = entities for the universe, evaluation = a metric for a niche, voice = buyer voice, trend = dynamics over time.\n")

# --- implementation queue ---
lines.append("## Implementation queue (planned, by priority)\n")
lines.append("| P | Source | Group | Stage | Stage groups | What it would give |")
lines.append("|---|---|---|---|---|---|")
for s in sorted([s for s in sources if s["status"] == "planned"], key=lambda s: (s["priority"], s["group"])):
    lines.append(f"| {s['priority']} | {esc(s['name'])} | {s['group']} | {adapter_text(s)} | {', '.join(s['stages'])} | {esc(s['plan'])} |")
lines.append("")

# --- summary table ---
lines.append("## Summary table\n")
lines.append("| Source | Group | Geo | Role | Freshness | Best access | Probe | Status | P | Stage groups |")
lines.append("|---|---|---|---|---|---|---|---|---|---|")
for g in GROUP_ORDER:
    for s in by_group.get(g, []):
        a = best_access(s)
        acc = f"{a['method']} · {a['auth']} · {a['cost']}"
        lines.append(f"| **{esc(s['name'])}** (`{s['id']}`) | {g} | {s['geo']} | {', '.join(s['role'])} | {s['freshness']} | {esc(acc)} | {http_cell(a)} | {STATUS_ICON[s['status']]} {s['status']} | {s['priority']} | {', '.join(s['stages'])} |")
lines.append("")

# --- per group ---
lines.append("## Sources by group\n")
for g in GROUP_ORDER:
    if g not in by_group:
        continue
    lines.append(f"### {g} - {groups[g]}\n")
    for s in by_group[g]:
        lines.append(f"#### {STATUS_ICON[s['status']]} {s['name']} (`{s['id']}`) - {s['priority']}\n")
        lines.append(f"{s['url']} · geo {s['geo']} · role {', '.join(s['role'])} · freshness {s['freshness']} · stage groups {', '.join(s['stages'])} · stage {adapter_text(s)}\n")
        lines.append("Signals:")
        for x in s["signals"]:
            lines.append(f"- {x}")
        if s["feeds"]:
            lines.append("\nFeeds: " + "; ".join(f"`{f}`" for f in s["feeds"]))
        lines.append("\n| Method | Endpoint | Auth | Cost | Limits / format | Probe |")
        lines.append("|---|---|---|---|---|---|")
        for a in s["access"]:
            p = a.get("probe") or {}
            lines.append(f"| {a['method']} | {esc(a['endpoint'])} | {esc(a['auth'])} | {esc(a['cost'])} | {esc(a['limits'])} | {p.get('http')} {p.get('date')} - {esc(p.get('note', ''))} |")
        if s["caveats"]:
            lines.append("\nTraps:")
            for x in s["caveats"]:
                lines.append(f"- {x}")
        lines.append(f"\nPlan: {s['plan']}\n")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"{len(sources)} sources, {sum(len(s['access']) for s in sources)} access methods -> {os.path.relpath(OUT, ROOT)}")
print("statuses:", dict(st))
print("priorities:", dict(pr))
