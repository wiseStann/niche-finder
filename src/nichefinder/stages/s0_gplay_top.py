"""S0: Google Play top charts for every non-game category.

Runs the bundled Node helper gplay_top.mjs (google-play-scraper): per category, the US top-grossing chart and the
RU top-grossing and top-free charts, up to 200 apps each. Writes data/raw/gplay_top.csv with columns country,
collection, category, rank, title, appId, developer, score, priceText, summary. Responses are cached under
data/cache/gplay/ (one JSON file per country, collection and category).

Google Play payments have been blocked in Russia since 2022: RU top-grossing reflects users with foreign cards,
RU top-free reflects usage. Needs Node.js 18+ and `nf setup node`. About 87 requests, 1.5 s apart. No keys.
"""
from __future__ import annotations

import argparse

from nichefinder import tools
from nichefinder.workspace import Workspace

SUMMARY = "Google Play top charts per category (US/RU)"
KEYS: tuple[str, ...] = ()
NEEDS: tuple[str, ...] = ("node",)


def run(ws: Workspace, args: argparse.Namespace) -> None:
    tools.run_node(ws, "gplay_top.mjs")
