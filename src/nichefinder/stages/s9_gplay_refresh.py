"""Fresh Google Play installs and ratings for the apps of a base snapshot (supply over time).

Reads data/snapshots/<base>/gplay.csv (written by `s9_snapshot freeze`) and fetches every app again.
Output: data/snapshots/<date>/gplay.csv. Cache: data/cache/gplay_app_<date>/ (separate from the S8 app cache,
so old cards are not reused). Cost: free, no key. The same app in several niches is fetched once.
Afterwards run `s9_snapshot refresh` for the App Store side and `s9_snapshot diff`.
"""
from __future__ import annotations

import argparse
import os

from nichefinder import tools
from nichefinder.workspace import Workspace

SUMMARY = "Refresh Google Play installs/ratings for a snapshot's apps"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("node",)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", default="", help="snapshot date (default: the run date)")
    parser.add_argument("--base", default="", help="base snapshot to refresh (default: the earliest)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    date = args.date or ws.today.isoformat()
    extra = [date] + ([args.base] if args.base else [])
    os.environ["NF_CACHE_DIR"] = str(ws.cache_root)
    tools.run_node(ws, "gplay_refresh.mjs", *extra)
