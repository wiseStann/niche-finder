"""Optional external tools: Node.js (Google Play helpers) and the trendspy package (Google Trends)."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

from nichefinder.workspace import Workspace

NODE_DIR = Path(__file__).parent / "node"          # bundled .mjs helpers
GPLAY_PACKAGE = "google-play-scraper@10.1.4"


class ToolMissing(Exception):
    pass


def node_modules(ws: Workspace) -> Path | None:
    """Where google-play-scraper is installed: $NF_NODE_MODULES, <workspace>/node_modules, or the repo's node_modules."""
    candidates = [os.environ.get("NF_NODE_MODULES"), ws.root / "node_modules", Path(__file__).parents[2] / "node_modules"]
    for c in candidates:
        if c and (Path(c) / "google-play-scraper").is_dir():
            return Path(c)
    return None


def check(name: str, ws: Workspace) -> str | None:
    """None when the tool is ready, otherwise a one-line fix."""
    if name == "node":
        if not shutil.which("node"):
            return "Node.js 18+ is required for Google Play stages: https://nodejs.org"
        if not node_modules(ws):
            return f"google-play-scraper is not installed: run `nf setup node` (npm install {GPLAY_PACKAGE})"
        return None
    if name == "trendspy":
        if importlib.util.find_spec("trendspy") is None:
            return "trendspy is not installed: pip install 'niche-finder[trends]'"
        return None
    if name == "curl":
        return None if shutil.which("curl") else "curl is required for some sources: install it and put it on PATH"
    return f"unknown tool {name}"


def require(name: str, ws: Workspace) -> None:
    problem = check(name, ws)
    if problem:
        raise ToolMissing(problem)


def run_node(ws: Workspace, script: str, *args: str) -> None:
    """Run a bundled Node helper: node <package>/node/<script> <node_modules> <args...> (cwd = workspace)."""
    require("node", ws)
    cmd = ["node", str(NODE_DIR / script), str(node_modules(ws)), *map(str, args)]
    subprocess.run(cmd, cwd=ws.root, check=True)


def setup_node(ws: Workspace) -> None:
    if not shutil.which("npm"):
        raise ToolMissing("npm not found: install Node.js 18+ from https://nodejs.org")
    subprocess.run(["npm", "install", "--no-save", "--prefix", str(ws.root), GPLAY_PACKAGE], check=True, shell=os.name == "nt")
