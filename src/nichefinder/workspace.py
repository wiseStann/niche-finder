"""Workspace: one research project on disk.

A workspace is a folder with an `nf.yaml` file. Layout:

    nf.yaml          settings (markets, revenue goal, LLM, verdict thresholds, as-of date)
    .env             your API keys (never commit it)
    niches.yaml      the niches you want to measure
    queries/*.yaml   search queries per niche
    config/*.yaml    source maps, relevance exclusions, overrides, scoring weights
    data/raw/        source dumps (S0)
    data/cache/      every external response, so re-runs are free and offline
    data/out/        stage outputs (CSV/JSON)
    data/snapshots/  frozen supply snapshots (S9)
    reports/         generated Markdown and HTML

Stages never hardcode paths or dates: they ask the workspace.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

import yaml

from nichefinder import keys

MARKER = "nf.yaml"


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, root: Path, settings: dict[str, Any] | None = None):
        self.root = Path(root).resolve()
        self.settings: dict[str, Any] = settings if settings is not None else self._read_settings()
        keys.load_dotenv(self.root / ".env")

    # ---- discovery -------------------------------------------------------

    @classmethod
    def find(cls, start: str | os.PathLike | None = None) -> "Workspace":
        """Workspace from an explicit path, $NF_WORKSPACE, or the nearest parent of the current directory with nf.yaml."""
        candidates = [Path(start)] if start else ([Path(os.environ["NF_WORKSPACE"])] if os.environ.get("NF_WORKSPACE") else [])
        if not candidates:
            here = Path.cwd().resolve()
            candidates = [here, *here.parents]
        for c in candidates:
            if (c / MARKER).is_file():
                return cls(c)
        where = candidates[0] if len(candidates) == 1 else Path.cwd()
        raise WorkspaceError(f"no {MARKER} found at {where} or its parents. Create a workspace with `nf init <folder>`.")

    def _read_settings(self) -> dict[str, Any]:
        path = self.root / MARKER
        if not path.is_file():
            raise WorkspaceError(f"{path} not found")
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # ---- settings --------------------------------------------------------

    def setting(self, dotted: str, default: Any = None) -> Any:
        """Read a nested setting: ws.setting("goal.net_month_low", 60000)."""
        cur: Any = self.settings
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @property
    def markets(self) -> list[str]:
        """Demand pools to measure: us, ww (worldwide), ru."""
        return list(self.setting("markets", ["us"]))

    @property
    def today(self) -> dt.date:
        """The run date. Set `as_of: YYYY-MM-DD` in nf.yaml to reproduce a past run from cache."""
        v = self.setting("as_of")
        if v:
            return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))
        return dt.date.today()

    # ---- paths -----------------------------------------------------------

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    @property
    def niches_file(self) -> Path:
        return self.root / "niches.yaml"

    @property
    def queries_dir(self) -> Path:
        return self.root / "queries"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def cache_root(self) -> Path:
        v = os.environ.get("NF_CACHE_DIR") or self.setting("cache_dir")
        return Path(v).expanduser().resolve() if v else self.data_dir / "cache"

    def config(self, name: str) -> Path:
        """Path to config/<name> (may not exist)."""
        return self.config_dir / name

    def load_config(self, name: str, default: Any = None) -> Any:
        """Parsed config/<name>.yaml, or `default` when the file is missing. Raises when missing and no default."""
        path = self.config(name)
        if not path.is_file():
            if default is None:
                raise WorkspaceError(f"missing config file: {path}")
            return default
        return yaml.safe_load(path.read_text(encoding="utf-8")) or default

    def raw(self, name: str = "") -> Path:
        return self._ensure(self.data_dir / "raw", name)

    def out(self, name: str = "") -> Path:
        return self._ensure(self.data_dir / "out", name)

    def snapshots(self, name: str = "") -> Path:
        return self._ensure(self.data_dir / "snapshots", name)

    def report(self, name: str = "") -> Path:
        return self._ensure(self.root / "reports", name)

    def cache(self, namespace: str) -> Path:
        """Cache directory for one source, created on demand: data/cache/<namespace>/."""
        d = self.cache_root / namespace
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _ensure(base: Path, name: str) -> Path:
        base.mkdir(parents=True, exist_ok=True)
        if not name:
            return base
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
