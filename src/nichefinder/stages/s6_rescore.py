"""Second pass of s6_score, after off-search demand (S8) and buyer voice (S10) exist.

s8_offsearch and s10_reddit_report show each niche's score and verdict, so `nf run all` scores once after S5
and again here, when the score can use S8 outputs. Same code, same outputs as s6_score.
"""
from __future__ import annotations

from nichefinder.stages.s6_score import KEYS, NEEDS, run  # noqa: F401

SUMMARY = "Re-score with S8–S10 outputs (second pass of s6_score)"
