"""Offline tests for the trend metrics of S4 (Wordstat dynamics)."""
from __future__ import annotations

from nichefinder.stages import s4_wordstat_dynamics as s4


def months(values: list[int], start_year: int = 2023) -> list[tuple[str, int]]:
    return [(f"{start_year + i // 12}-{i % 12 + 1:02d}", x) for i, x in enumerate(values)]


def test_seasonal_flat_series_is_flat():
    """Yearly peaks above 3x the median are capped the same way in both years, so a flat seasonal series stays flat.
    With the old rule (only the last 12 months capped, at 3x the previous median) this series read as DOWN, -36 %."""
    year = [100] * 10 + [600, 900]
    m = s4.series_metrics(months(year * 3))
    assert m["yoy"] == 0 and m["verdict"] == "FLAT"


def test_recent_spike_is_capped():
    """A one-month spike in the last 12 months counts at most 3x the median of the 12 months before it."""
    base = [1000] * 24
    m = s4.series_metrics(months(base + [1000] * 11 + [20000]))
    assert m["yoy"] == round((11 * 1000 + 3000) / 12000 - 1, 3) and m["spike"] == 1
