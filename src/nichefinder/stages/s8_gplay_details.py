"""Google Play app cards for the relevant apps: installs, ratings, release date, price and in-app purchases.

Takes data/out/gplay_match.csv and fetches each app's page (google-play-scraper) through a Node helper.
Output: data/out/gplay_apps.csv. Cache: data/cache/gplay_app/<country>_<appId>.json (errors are not cached).
Cost: free, no key; about 0.7 s per new app.

Sharding: `--shard 1/3` processes every third row so several processes can fetch in parallel (each run writes
a partial gplay_apps.csv); a final run without --shard assembles the full CSV from the cache.
"""
from __future__ import annotations

import argparse
import os

from nichefinder import tools
from nichefinder.workspace import Workspace

SUMMARY = "Google Play app cards: installs, ratings, release date, price"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("node",)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--shard", default="", help="k/N: process only rows k, k+N, ... (e.g. 0/3, 1/3, 2/3)")


def run(ws: Workspace, args: argparse.Namespace) -> None:
    os.environ["NF_CACHE_DIR"] = str(ws.cache_root)
    extra = [args.shard] if args.shard else []
    tools.run_node(ws, "gplay_details.mjs", *extra)
