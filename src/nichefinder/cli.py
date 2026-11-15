"""`nf` command line.

    nf init my-research            create a workspace from the bundled example (165 niches)
    nf doctor                      keys, tools and workspace status
    nf validate                    check niches.yaml and queries/*.yaml
    nf list                        stages with readiness
    nf run all                     the whole pipeline (stages with missing keys/tools are skipped)
    nf run s3                      one group
    nf run s5_capterra -- --help   one stage with its own flags
    nf setup node                  install the Google Play scraper for Node-based stages
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import traceback
from pathlib import Path

from nichefinder import __version__, keys, niches, tools
from nichefinder.stages import GROUPS, STAGES, resolve
from nichefinder.workspace import Workspace, WorkspaceError

EXAMPLES = Path(__file__).parent / "examples"


def _ws(args) -> Workspace:
    return Workspace.find(args.workspace)


def cmd_init(args) -> None:
    src = EXAMPLES / args.example
    if not src.is_dir():
        raise SystemExit(f"unknown example {args.example}; available: {', '.join(p.name for p in EXAMPLES.iterdir() if p.is_dir())}")
    dst = Path(args.folder).resolve()
    if dst.exists() and any(dst.iterdir()) and not args.force:
        raise SystemExit(f"{dst} is not empty (use --force to copy over it)")
    shutil.copytree(src, dst, dirs_exist_ok=True)
    if (dst / ".env.example").is_file() and not (dst / ".env").exists():
        shutil.copy(dst / ".env.example", dst / ".env")
    print(f"workspace created: {dst}\n"
          f"next: add your keys to {dst / '.env'}, then `cd {dst}` and run `nf doctor`.")


def cmd_doctor(args) -> None:
    ws = _ws(args)
    print(f"niche-finder {__version__}\nworkspace: {ws.root}\nmarkets: {', '.join(ws.markets)}\ncache: {ws.cache_root}\n")
    print("keys:")
    for name, g in keys.GROUPS.items():
        ok = keys.have(*g["keys"])
        print(f"  {'ok ' if ok else '-- '} {name:<11} {', '.join(g['keys'])}" + ("" if ok else f"  — {g['where']}"))
    print("\ntools:")
    for t in ("trendspy", "node", "curl"):
        problem = tools.check(t, ws)
        print(f"  {'ok ' if not problem else '-- '} {t:<11} {problem or ''}")
    errors, warns, stats = niches.validate(ws)
    print(f"\nniches: {stats['niches']} ({len(errors)} errors, {len(warns)} warnings — details: nf validate)")


def cmd_validate(args) -> None:
    ws = _ws(args)
    errors, warns, stats = niches.validate(ws)
    print(f"niches: {stats.pop('niches')}, with queries: {stats.pop('with_queries')}")
    print("queries:", ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    if warns:
        print(f"\nWARNINGS ({len(warns)}):")
        for w in warns:
            print("  ", w)
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print("  ", e)
        raise SystemExit(1)
    print("\nOK")


def _readiness(stage, ws: Workspace) -> str | None:
    mod = stage.module()
    missing = [k for k in getattr(mod, "KEYS", ()) if not keys.have(k)]
    if missing:
        return f"needs {', '.join(missing)}"
    for t in getattr(mod, "NEEDS", ()):
        problem = tools.check(t, ws)
        if problem:
            return problem
    if stage.market != "global" and stage.market not in ws.markets:
        return f"market {stage.market} is off in nf.yaml"
    return None


def cmd_list(args) -> None:
    try:
        ws = _ws(args)
    except WorkspaceError:
        ws = None
    for group in GROUPS:
        print(f"\n{group}")
        for s in (x for x in STAGES if x.group == group):
            try:
                summary = getattr(s.module(), "SUMMARY", "")
                status = _readiness(s, ws) if ws else None
            except ImportError as e:
                summary, status = "", f"not available: {e}"
            flag = "--" if status else "ok"
            manual = " (manual)" if not s.in_all else ""
            print(f"  {flag} {s.name:<22} {summary}{manual}" + (f"  [{status}]" if status else ""))


def cmd_run(args) -> None:
    ws = _ws(args)
    stages = resolve(args.targets)
    single = len(stages) == 1
    failed, skipped = [], []
    for s in stages:
        mod = s.module()
        if s.market != "global" and s.market not in ws.markets and not single:
            skipped.append((s.name, f"market {s.market} is off"))
            continue
        problem = _readiness(s, ws)
        if problem and not (single and problem.startswith("market")):
            print(f"\n== {s.name}: skipped — {problem}")
            skipped.append((s.name, problem))
            continue
        parser = argparse.ArgumentParser(prog=f"nf run {s.name} --", description=getattr(mod, "SUMMARY", ""))
        if hasattr(mod, "add_arguments"):
            mod.add_arguments(parser)
        stage_args = parser.parse_args(args.stage_args if single else [])
        print(f"\n== {s.name}: {getattr(mod, 'SUMMARY', '')}", flush=True)
        t0 = time.time()
        try:
            mod.run(ws, stage_args)
        except (keys.MissingKey, tools.ToolMissing) as e:
            print(f"   skipped — {e}")
            skipped.append((s.name, str(e)))
            continue
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            failed.append(s.name)
            if not args.keep_going:
                break
            continue
        print(f"   done in {time.time() - t0:.0f}s")
    if len(stages) > 1:
        print(f"\nfinished: {len(stages) - len(failed) - len(skipped)} ran, {len(skipped)} skipped, {len(failed)} failed")
        for name, why in skipped:
            print(f"  skipped {name}: {why}")
    if failed:
        print(f"  failed: {', '.join(failed)}")
        raise SystemExit(1)


def cmd_setup(args) -> None:
    ws = _ws(args)
    if args.what == "node":
        tools.setup_node(ws)
        print("google-play-scraper installed into", ws.root / "node_modules")


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    stage_args: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, stage_args = argv[:i], argv[i + 1:]

    ap = argparse.ArgumentParser(prog="nf", description="niche-finder: niche-first market research pipeline")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-w", "--workspace", help="workspace folder (default: nearest folder with nf.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a workspace")
    p.add_argument("folder")
    p.add_argument("--example", default="default")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    sub.add_parser("doctor", help="keys, tools and workspace status").set_defaults(fn=cmd_doctor)
    sub.add_parser("validate", help="check niches and queries").set_defaults(fn=cmd_validate)
    sub.add_parser("list", help="list stages").set_defaults(fn=cmd_list)

    p = sub.add_parser("run", help="run stages: names, groups (s0…s10, ru) or all")
    p.add_argument("targets", nargs="+")
    p.add_argument("-k", "--keep-going", action="store_true", help="continue after a failed stage")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("setup", help="install optional tools")
    p.add_argument("what", choices=["node"])
    p.set_defaults(fn=cmd_setup)

    args = ap.parse_args(argv)
    args.stage_args = stage_args
    try:
        args.fn(args)
    except WorkspaceError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
