"""Every registered stage imports and follows the stage contract."""
from __future__ import annotations

import argparse
import re

import pytest

from nichefinder.stages import STAGES

CYRILLIC = re.compile("[\\u0400-\\u04FF]")


@pytest.mark.parametrize("stage", STAGES, ids=lambda s: s.name)
def test_stage_contract(stage):
    mod = stage.module()
    assert isinstance(getattr(mod, "SUMMARY", None), str) and mod.SUMMARY
    assert callable(getattr(mod, "run", None))
    assert isinstance(getattr(mod, "KEYS", ()), tuple)
    assert set(getattr(mod, "NEEDS", ())) <= {"node", "trendspy", "curl"}
    if hasattr(mod, "add_arguments"):
        mod.add_arguments(argparse.ArgumentParser())


@pytest.mark.parametrize("stage", STAGES, ids=lambda s: s.name)
def test_stage_source_is_english(stage):
    """Only data may contain Cyrillic (Russian search phrases, registry class names): prose must be English.
    Lines with Cyrillic must be string literals inside data structures, never comments or docstrings."""
    src = open(stage.module().__file__, encoding="utf-8").read()
    for i, line in enumerate(src.splitlines(), 1):
        if CYRILLIC.search(line) and line.lstrip().startswith("#"):
            pytest.fail(f"{stage.name}:{i} Cyrillic in a comment: {line.strip()[:80]}")
