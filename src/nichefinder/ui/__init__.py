"""`nf ui`: a local web console for the pipeline.

One page (index.html next to this file) served on 127.0.0.1. The owner picks the markets, niche sides and tiers of a run
(a run profile, see profiles.py) and the stages, starts the run and watches each stage go from pending to running, done,
skipped or failed, with its live output; then opens the profile's scores and reports. Standard library only.

A run is a child process `python -m nichefinder [-p profile] run <targets>` with $NF_EVENTS set, so the CLI prints
`@@nf {...}` progress lines (cli._event) between the stages' own output. The server turns both into events with a
sequence number and streams them to the page as Server-Sent Events; a reloaded page replays the current run. One run at
a time. Every run is written to logs/ui/<run id>.jsonl (events) and <run id>.json (summary), and the last duration of
each stage to logs/ui/stage_times.json, which gives the time-left estimate.

Safety: the server listens on 127.0.0.1 only, answers only requests whose Host header is that address (against DNS
rebinding), and requires the token embedded in the page, generated at each start, on every request that changes
something, so another web page open in the same browser cannot start a paid run.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from nichefinder import __version__, keys, niches, profiles
from nichefinder.cli import _readiness
from nichefinder.stages import BY_NAME, GROUPS, STAGES
from nichefinder.workspace import PROFILE_NAME, Workspace, WorkspaceError

PAGE = Path(__file__).with_name("index.html")
EVENT_PREFIX = "@@nf "
MAX_LINE = 4000
GROUP_TITLES = {
    "s0": "Universe of products", "s1": "Niches", "s2": "Queries", "s3": "Search demand", "exp": "Paid experiments",
    "s4": "Trend depth", "s5": "Supply depth", "s9": "Supply over time", "s6": "Score and passports",
    "s8": "Demand outside search", "s10": "Buyer voice", "s7": "Leaderboard", "info": "Info products (own score)",
    "ru": "Russian B2B module",
}
# Presets of the stage picker: names of stages (the page adds `nf run all`, which is every stage with in_all).
RESCORE = ["s6_score", "s6_ru", "s6_ceiling", "s6_passports", "s7_html"]
TYPES = {".html": "text/html; charset=utf-8", ".md": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8",
         ".txt": "text/plain; charset=utf-8", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml"}


class Busy(Exception):
    pass


def targets_for(names: list[str]) -> list[str]:
    """The shortest `nf run` targets for a set of stages: `all`, whole groups, then single stages."""
    chosen = set(names)
    if chosen == {s.name for s in STAGES if s.in_all}:
        return ["all"]
    out: list[str] = []
    for g in GROUPS:
        members = [s.name for s in STAGES if s.group == g]
        if len(members) > 1 and set(members) <= chosen:
            out.append(g)
        else:
            out += [n for n in members if n in chosen]
    return out


class Runner:
    """The current (or last) run: its child process, its events and its log file."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.logdir = ws.root / "logs" / "ui"
        self.logdir.mkdir(parents=True, exist_ok=True)
        self.cond = threading.Condition()
        self.start_lock = threading.Lock()
        self.seq = int(time.time() * 1000)   # ids stay increasing across server restarts (EventSource Last-Event-ID)
        self.events: list[tuple[int, str]] = []   # (seq, JSON) of the current or last run, serialized when emitted
        self.proc: subprocess.Popen | None = None
        self.meta: dict[str, Any] | None = None
        self.current: str | None = None
        self.stopping = False
        self.logfile = None
        self.times_path = self.logdir / "stage_times.json"
        try:
            self.times: dict[str, float] = json.loads(self.times_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.times = {}

    def busy(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ---- events ----------------------------------------------------------

    def _emit(self, ev: dict) -> None:
        """Append one event (the caller holds self.cond) and wake the streams. Serialized now, so that a stream never
        reads a dict that another thread is changing."""
        self.seq += 1
        ev["seq"] = self.seq
        ev.setdefault("t", round(time.time(), 2))
        data = json.dumps(ev, ensure_ascii=False, default=str)
        self.events.append((self.seq, data))
        if self.logfile:
            self.logfile.write(data + "\n")
        self.cond.notify_all()

    def since(self, seq: int, timeout: float) -> list[tuple[int, str]]:
        """(seq, JSON) of the events after `seq`, waiting up to `timeout` seconds for the first one. A sequence number
        of an earlier run returns the whole current run."""
        with self.cond:
            def ready():
                return bool(self.events) and self.events[-1][0] > seq
            self.cond.wait_for(ready, timeout)
            if not self.events:
                return []
            i = max(0, min(len(self.events), seq - self.events[0][0] + 1))
            return self.events[i:i + 3000]

    # ---- runs ------------------------------------------------------------

    def start(self, spec: dict, stages: list[str], keep_going: bool, stage_args: str) -> dict:
        if not self.start_lock.acquire(blocking=False):
            raise Busy("a run is starting")
        try:
            if self.busy():
                raise Busy("a run is in progress")
            unknown = [n for n in stages if n not in BY_NAME]
            if unknown or not stages:
                raise ValueError(f"unknown stages: {', '.join(unknown)}" if unknown else "pick at least one stage")
            prof = profiles.create(self.ws, spec)   # ValueError for an empty pick; seeds a new profile (can take seconds)
            order = {s.name: i for i, s in enumerate(STAGES)}
            stages = sorted(set(stages), key=order.get)
            targets = targets_for(stages)
            extra = shlex.split(stage_args) if stage_args.strip() and len(stages) == 1 else []
            cmd = [sys.executable, "-m", "nichefinder", "-w", str(self.ws.root)]
            cmd += ["-p", prof.profile] if prof.profile else []
            cmd += ["run", *targets] + (["-k"] if keep_going else []) + (["--", *extra] if extra else [])
            env = dict(os.environ, NF_EVENTS="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            env.pop("NF_PROFILE", None)
            env.pop("NF_WORKSPACE", None)
            popen_kw: dict[str, Any] = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                                        else {"start_new_session": True})
            run_id = time.strftime("%Y%m%d-%H%M%S")
            meta = {"id": run_id, "profile": prof.profile or "", "spec": prof.profile_spec, "stages": stages,
                    "targets": targets, "keep_going": keep_going, "args": extra, "started": round(time.time(), 2),
                    "status": "running", "command": "nf " + " ".join(cmd[5:])}
            proc = subprocess.Popen(cmd, cwd=self.ws.root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
                                    **popen_kw)
            with self.cond:
                if self.logfile:
                    self.logfile.close()
                self.logfile = open(self.logdir / f"{run_id}.jsonl", "w", encoding="utf-8")
                self.proc, self.meta, self.events, self.current, self.stopping = proc, meta, [], None, False
                self._emit({"type": "run", "run": dict(meta)})
            self._save_meta()
            threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
            return meta
        finally:
            self.start_lock.release()

    def _pump(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if line.startswith(EVENT_PREFIX):
                try:
                    ev = json.loads(line[len(EVENT_PREFIX):])
                except ValueError:
                    ev = None
                if isinstance(ev, dict):
                    self._stage_event(ev)
                    continue
            with self.cond:
                self._emit({"type": "log", "stage": self.current, "line": line[:MAX_LINE]})
        code = proc.wait()
        with self.cond:
            status = "stopped" if self.stopping else ("ok" if code == 0 else "failed")
            if self.current:
                self._emit({"type": "stage", "stage": self.current, "status": "stopped" if self.stopping else "failed",
                            "why": "stopped from the console" if self.stopping else f"the run ended with code {code}"})
                self.current = None
            assert self.meta is not None
            self.meta.update(status=status, code=code, ended=round(time.time(), 2))
            # history and timings are on disk before the page hears `end` and asks for them
            self._save_meta()
            try:
                self.times_path.write_text(json.dumps(self.times, indent=1, sort_keys=True), encoding="utf-8")
            except OSError:
                pass
            self._emit({"type": "end", "status": status, "code": code, "run": dict(self.meta)})
            if self.logfile:
                self.logfile.close()
                self.logfile = None

    def _stage_event(self, ev: dict) -> None:
        kind, stage = ev.get("ev"), ev.get("stage")
        with self.cond:
            if kind == "plan":
                self._emit({"type": "plan", "stages": ev.get("stages", []), "profile": ev.get("profile", ""),
                            "markets": ev.get("markets", [])})
            elif kind == "start":
                self.current = stage
                self._emit({"type": "stage", "stage": stage, "status": "running"})
            elif kind in ("done", "skip", "fail"):
                status = {"done": "done", "skip": "skipped", "fail": "failed"}[kind]
                if kind == "done" and ev.get("secs") is not None:
                    self.times[stage] = ev["secs"]
                self._emit({"type": "stage", "stage": stage, "status": status, "secs": ev.get("secs"),
                            "why": ev.get("why", "")})
                if self.current == stage:
                    self.current = None
            elif kind == "end":
                self._emit({"type": "summary", "ran": ev.get("ran"), "skipped": ev.get("skipped"),
                            "failed": ev.get("failed", [])})

    def stop(self) -> bool:
        with self.cond:
            proc = self.proc
            if proc is None or proc.poll() is not None:
                return False
            self.stopping = True
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return True

    def _save_meta(self) -> None:
        if self.meta:
            try:
                (self.logdir / f"{self.meta['id']}.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=1),
                                                                     encoding="utf-8")
            except OSError:
                pass

    def history(self, limit: int = 30) -> list[dict]:
        out = []
        for p in sorted(self.logdir.glob("*.json"), reverse=True):
            if p.name == self.times_path.name:
                continue
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if len(out) >= limit:
                break
        return out


class App:
    def __init__(self, ws: Workspace):
        self.ws = Workspace(ws.root)   # the full run; profiles are opened per request
        self.runner = Runner(self.ws)
        self.token = secrets.token_urlsafe(24)
        self.closing = False

    # ---- read ------------------------------------------------------------

    def state(self) -> dict:
        stages = []
        for s in STAGES:
            try:
                mod = s.module()
                info = {"summary": getattr(mod, "SUMMARY", ""), "keys": list(getattr(mod, "KEYS", ())),
                        "needs": list(getattr(mod, "NEEDS", ())), "args": hasattr(mod, "add_arguments")}
            except ImportError as e:
                info = {"summary": f"not available: {e}", "keys": [], "needs": [], "args": False}
            stages.append({"name": s.name, "group": s.group, "market": s.market, "in_all": s.in_all, **info})
        all_niches = niches.load_niches(self.ws, scoped=False)
        with self.runner.cond:
            run = dict(self.runner.meta) if self.runner.meta else None
        return {
            "version": __version__, "workspace": str(self.ws.root), "markets": self.ws.markets, "now": time.time(),
            "universe": profiles.universe(self.ws), "b2c_sides": list(niches.B2C_SIDES),
            "groups": [{"key": g, "title": GROUP_TITLES.get(g, g)} for g in GROUPS],
            "stages": stages, "rescore": RESCORE,
            "keys": {name: keys.have(*g["keys"]) for name, g in keys.GROUPS.items()},
            "niches": [{k: n.get(k, "") for k in ("id", "name", "side", "tier", "geo")} for n in all_niches],
            "profiles": [{"name": p["name"], "spec": p["spec"]} for p in profiles.list_profiles(self.ws)],
            "stage_times": self.runner.times, "running": self.runner.busy(), "run": run,
            "history": self.runner.history(),
        }

    def preview(self, spec: dict) -> dict:
        """What a run with these parameters would cover: the profile, the niches in scope, stage readiness, warnings."""
        try:
            norm = profiles.normalize(self.ws, spec)
        except ValueError as e:
            return {"error": str(e)}
        name = profiles.auto_name(self.ws, norm) if norm else ""
        ws = Workspace(self.ws.root, profile=name or None, profile_spec=norm)
        scoped = niches.load_niches(ws)
        try:
            short = niches.shortlist_ids(ws)
        except SystemExit:
            short = []
        def count(key: str, default: str) -> dict[str, int]:
            out: dict[str, int] = {}
            for n in scoped:
                v = str(n.get(key) or default)
                out[v] = out.get(v, 0) + 1
            return dict(sorted(out.items()))

        warnings = []
        if norm.get("tier") and "C" not in norm["tier"]:
            warnings.append("Control niches (tier C) are out: they show whether the score behaves (methodology §3).")
        if norm.get("markets"):
            warnings.append("Other markets than nf.yaml: run S3 again in this profile before scoring, since S6 reads "
                            "the demand that S3 measured for the markets.")
        if "us" not in ws.markets:
            warnings.append("The S6 score reads US demand: without the us market every niche gets the same demand "
                            "points. Read the Russian leaderboard (S6 RU in Results) instead.")
        if name and not (self.ws.root / "profiles" / name).is_dir():
            warnings.append("New profile: its outputs start as a copy of the full run's data/out/ for these niches.")
        ready = {}
        for s in STAGES:
            try:
                ready[s.name] = _readiness(s, ws)
            except ImportError as e:
                ready[s.name] = f"not available: {e}"
        return {"spec": norm, "profile": name, "exists": bool(name) and (self.ws.root / "profiles" / name).is_dir(),
                "niches": len(scoped), "shortlisted": len(short), "by_side": count("side", ""),
                "by_tier": count("tier", ""), "by_geo": count("geo", "global"), "ready": ready, "warnings": warnings,
                "outputs": str(ws.profile_root)}

    def _profile_ws(self, profile: str) -> Workspace:
        if profile in ("", "-"):
            return self.ws
        if not PROFILE_NAME.match(profile):
            raise WorkspaceError(f"bad profile {profile!r}")
        return Workspace(self.ws.root, profile=profile)

    def results(self, profile: str) -> dict:
        ws = self._profile_ws(profile)
        names = {n["id"]: n.get("name", n["id"]) for n in niches.load_niches(ws, scoped=False) if "id" in n}
        path = ws.profile_root / "data" / "out" / "score_final.csv"
        rows = []
        if path.is_file():
            with open(path, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    rows.append({k: r.get(k, "") for k in ("niche_id", "side", "tier", "geo", "score", "verdict",
                                                           "gates_failed", "flags", "verdict_note")}
                                | {"name": names.get(r.get("niche_id", ""), r.get("niche_id", ""))})
        rows.sort(key=lambda r: -float(r["score"] or 0))
        rows_ru = []
        path_ru = ws.profile_root / "data" / "out" / "score_ru.csv"
        if path_ru.is_file():
            with open(path_ru, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    rows_ru.append({"niche_id": r.get("niche_id", ""), "name": names.get(r.get("niche_id", ""), r.get("niche_id", "")),
                                    "side": r.get("side", ""), "tier": "", "geo": r.get("geo", ""),
                                    "score": r.get("score_ru", ""), "verdict": r.get("verdict", ""),
                                    "gates_failed": r.get("gates", ""), "flags": r.get("conc_src", ""),
                                    "verdict_note": r.get("note", ""), "demand": r.get("demand_ru", "")})
            rows_ru.sort(key=lambda r: -float(r["score"] or 0))
        reports_dir = ws.profile_root / "reports"
        reports = []
        if reports_dir.is_dir():
            for p in sorted(reports_dir.iterdir()):
                if p.is_file() and p.suffix in (".md", ".html"):
                    reports.append({"name": p.name, "mtime": p.stat().st_mtime, "size": p.stat().st_size})
        passports = len(list((reports_dir / "passports").glob("*.md"))) if (reports_dir / "passports").is_dir() else 0
        return {"profile": ws.profile or "", "markets": ws.markets, "rows": rows, "rows_ru": rows_ru,
                "scored": path.stat().st_mtime if path.is_file() else None,
                "scored_ru": path_ru.stat().st_mtime if path_ru.is_file() else None,
                "reports": reports, "passports": passports}

    def report_file(self, profile: str, rel: str) -> Path | None:
        base = (self._profile_ws(profile).profile_root / "reports").resolve()
        p = (base / rel).resolve()
        return p if p.is_file() and p.is_relative_to(base) else None

    def stage_help(self, name: str) -> str:
        if name not in BY_NAME:
            raise KeyError(name)
        mod = BY_NAME[name].module()
        parser = argparse.ArgumentParser(prog=f"nf run {name} --", description=getattr(mod, "SUMMARY", ""))
        if hasattr(mod, "add_arguments"):
            mod.add_arguments(parser)
        doc = (mod.__doc__ or "").strip()
        return parser.format_help() + ("\n\n" + doc if doc else "")

    def run_log(self, run_id: str) -> str:
        if not run_id.replace("-", "").isdigit():
            raise KeyError(run_id)
        path = self.runner.logdir / f"{run_id}.jsonl"
        if not path.is_file():
            raise KeyError(run_id)
        lines = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("type") == "log":
                lines.append(ev.get("line", ""))
            elif ev.get("type") == "stage" and ev.get("status") != "running":
                lines.append(f"-- {ev.get('stage')}: {ev.get('status')} {ev.get('why') or ''}".rstrip())
            elif ev.get("type") == "end":
                lines.append(f"-- run {ev.get('status')} (exit code {ev.get('code')})")
        return "\n".join(lines)


class Handler(BaseHTTPRequestHandler):
    server_version = f"nf-ui/{__version__}"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:   # noqa: A002 - quiet console
        pass

    # ---- plumbing --------------------------------------------------------

    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "").lower() in self.server.allowed_hosts  # type: ignore[attr-defined]

    def _send(self, code: int, body: bytes | str, ctype: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str), "application/json; charset=utf-8")

    def do_GET(self) -> None:   # noqa: N802
        if not self._host_ok():
            return self._send(403, "forbidden host")
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                page = PAGE.read_text(encoding="utf-8").replace("__NF_TOKEN__", self.app.token)
                return self._send(200, page, "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self._json(self.app.state())
            if u.path == "/api/events":
                return self._events(q)
            if u.path == "/api/results":
                return self._json(self.app.results(q.get("profile", "")))
            if u.path == "/api/help":
                return self._send(200, self.app.stage_help(q.get("stage", "")))
            if u.path == "/api/runlog":
                return self._send(200, self.app.run_log(q.get("id", "")))
            if u.path.startswith("/r/"):
                _, _, profile, rel = u.path.split("/", 3) if u.path.count("/") >= 3 else ("", "", "", "")
                f = self.app.report_file(unquote(profile), unquote(rel)) if rel else None
                if f is None:
                    return self._send(404, "not found")
                return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
            return self._send(404, "not found")
        except (KeyError, WorkspaceError) as e:
            return self._send(404, f"not found: {e}")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return None

    def do_POST(self) -> None:   # noqa: N802
        if not self._host_ok():
            return self._send(403, "forbidden host")
        if not secrets.compare_digest(self.headers.get("X-NF-Token", ""), self.app.token):
            return self._send(403, "bad token: reload the page")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send(400, "bad json")
        path = urlparse(self.path).path
        try:
            if path == "/api/preview":
                return self._json(self.app.preview(body.get("spec") or {}))
            if path == "/api/run":
                meta = self.app.runner.start(body.get("spec") or {}, list(body.get("stages") or []),
                                             bool(body.get("keep_going")), str(body.get("args") or ""))
                return self._json(meta)
            if path == "/api/stop":
                return self._json({"stopped": self.app.runner.stop()})
            return self._send(404, "not found")
        except Busy as e:
            return self._json({"error": str(e)}, 409)
        except (ValueError, WorkspaceError) as e:
            return self._json({"error": str(e)}, 400)
        except OSError as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _events(self, q: dict) -> None:
        try:
            seq = int(self.headers.get("Last-Event-ID") or q.get("since") or 0)
        except ValueError:
            seq = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while not self.app.closing:
                batch = self.app.runner.since(seq, timeout=15)
                if not batch:
                    self.wfile.write(b": ping\n\n")
                else:
                    chunk = "".join(f"id: {n}\ndata: {data}\n\n" for n, data in batch)
                    seq = batch[-1][0]
                    self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except OSError:
            return


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"   # on Windows SO_REUSEADDR lets a second server take a busy port


def make_server(ws: Workspace, port: int = 8765, tries: int = 10) -> Server:
    """A server on the first free port from `port`, not yet serving (tests use port 0)."""
    last: OSError | None = None
    for p in ([port] if port == 0 else range(port, port + tries)):
        try:
            httpd = Server(("127.0.0.1", p), Handler)
        except OSError as e:
            last = e
            continue
        real = httpd.server_address[1]
        httpd.app = App(ws)  # type: ignore[attr-defined]
        httpd.allowed_hosts = {f"127.0.0.1:{real}", f"localhost:{real}"}  # type: ignore[attr-defined]
        return httpd
    raise SystemExit(f"no free port in {port}-{port + tries - 1}: {last}")


def serve(ws: Workspace, port: int = 8765, open_browser: bool = True) -> None:
    httpd = make_server(ws, port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"nf ui: {url}\nworkspace: {ws.root}\nCtrl+C stops the console (and a run in progress).", flush=True)
    if open_browser:
        threading.Timer(0.6, webbrowser.open, (url,)).start()
    app: App = httpd.app  # type: ignore[attr-defined]
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.closing = True
        if app.runner.stop():
            print("stopped the run in progress")
        with app.runner.cond:
            app.runner.cond.notify_all()
        httpd.server_close()
