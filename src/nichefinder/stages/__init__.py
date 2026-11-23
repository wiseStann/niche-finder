"""Stage registry: every pipeline step, in the order `nf run all` executes them.

Each stage is a module in this package with:

    SUMMARY: str                       one line for `nf list`
    KEYS: tuple[str, ...] = ()         env keys the stage needs (missing → stage is skipped)
    NEEDS: tuple[str, ...] = ()        external tools: "node", "trendspy", "curl"
    def add_arguments(parser) -> None  optional stage-specific CLI flags
    def run(ws, args) -> None

Groups: s0 universe · s1 niches · s2 queries · s3 search demand · s4 trend depth · s5 supply depth ·
s8 off-search demand · s9 supply over time · s10 buyer voice (Reddit; Russian app reviews) · s6 score and passports ·
s7 HTML leaderboard · info micro info products (short video -> Telegram, own score) · ru Russian B2B module ·
exp paid one-off experiments (manual, never scored).
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType


@dataclass(frozen=True)
class Stage:
    name: str
    group: str
    market: str = "global"   # "ru" stages run only when nf.yaml markets include ru
    in_all: bool = True      # False: manual stages (snapshots) that `nf run all` skips

    def module(self) -> ModuleType:
        return importlib.import_module(f"nichefinder.stages.{self.name}")


STAGES: list[Stage] = [
    # S0 — universe of existing products
    Stage("s0_yc", "s0"),
    Stage("s0_appstore_top", "s0"),
    Stage("s0_producthunt", "s0"),
    Stage("s0_empireflippers", "s0"),
    Stage("s0_tinyseed", "s0"),
    Stage("s0_gplay_top", "s0"),
    Stage("s0_wordpress", "s0"),
    Stage("s0_shopify", "s0"),
    Stage("s0_betalist", "s0"),
    Stage("s0_productradar", "s0", market="ru"),
    Stage("s0_kickstarter", "s0"),
    Stage("s0_trustmrr", "s0"),
    Stage("s0_regulation", "s0"),      # discovery report for a human: rules with a compliance deadline, never auto-added
    Stage("s0_merge", "s0"),
    # S1 — niches
    Stage("s1_niches", "s1"),
    Stage("s1_coverage", "s1"),
    # S2 — queries
    Stage("s2_suggest", "s2"),
    Stage("s2_wordstat", "s2", market="ru"),
    # S3 — search demand quick filter
    Stage("s3_dataforseo", "s3"),
    Stage("s3_metrics", "s3"),
    Stage("s3_report", "s3"),
    Stage("s3_switch_intent", "s3"),   # evidence: "<brand> alternative" demand, not in the score
    # Experiment, own group so that `nf run s3` never pays for it: AI search volume index vs Google (never scored)
    Stage("s3_ai_volume", "exp", in_all=False),
    # S4 — trend depth
    Stage("s4_trends", "s4"),
    Stage("s4_wordstat_dynamics", "s4", market="ru"),
    # S5 — supply depth
    Stage("s5_appstore", "s5"),
    Stage("s5_appstore_metrics", "s5"),
    Stage("s5_capterra", "s5"),
    Stage("s5_shopify_metrics", "s5"),
    Stage("s5_pricing_b2b", "s5"),
    Stage("s5_pricing_b2c", "s5"),
    Stage("s5_deals", "s5"),
    Stage("s5_ai_substitute", "s5"),   # evidence for the manual G3 platform risk, not a gate
    Stage("s5_serp", "s5"),            # evidence: who owns the SERP, keyword difficulty (DataForSEO Labs, paid)
    Stage("s5_ecosystems", "s5"),      # evidence: Chrome Web Store, Atlassian Marketplace
    Stage("s5_oss", "s5"),             # evidence: free open-source substitutes (GitHub)
    Stage("s5_merge", "s5"),
    # First score pass: S8 and S10 reports show score and verdict, and s6_score reads S8 outputs — see s6_rescore
    Stage("s9_entrants", "s9"),
    Stage("s6_score", "s6"),
    # S8 — demand outside search
    Stage("s8_youtube_trends", "s8"),
    Stage("s8_subreddit_stats", "s8"),
    Stage("s8_appstore_velocity", "s8"),
    Stage("s8_gplay_search", "s8"),
    Stage("s8_gplay_filter", "s8"),
    Stage("s8_gplay_details", "s8"),
    Stage("s8_gplay_metrics", "s8"),
    Stage("s8_hh", "s8", market="ru"),
    Stage("s8_hn_mentions", "s8"),
    Stage("s8_hn_hiring", "s8"),
    # Russian SME register: group ru (so `nf run s8` never downloads 2 x 2.2 GB), placed here so s8_who_counts and the
    # passports of a full run see it
    Stage("ru_msp_counts", "ru", market="ru"),
    Stage("s8_who_counts", "s8"),      # how many target businesses exist (US Census; Russian SME register via ru_msp_counts)
    Stage("s8_freelance", "s8"),       # paid demand on freelance exchanges
    Stage("s8_vk_audience", "s8", market="ru"),   # evidence: VK community sizes around the niche's topic or trade
    Stage("s8_offsearch", "s8"),
    # S9 — supply over time
    Stage("s9_snapshot", "s9", in_all=False),
    Stage("s9_gplay_refresh", "s9", in_all=False),
    Stage("s9_wayback", "s9"),         # competitor site age and liveness (Wayback Machine)
    Stage("s5_advertisers", "s5"),     # evidence: competitors' ads (Ads Transparency); after s9_wayback, whose domains it reads
    # S10 — buyer voice (Reddit)
    Stage("s10_reddit_fetch", "s10"),
    Stage("s10_reddit_threads", "s10"),
    Stage("s10_reddit_classify", "s10"),
    Stage("s10_reddit_metrics", "s10"),
    Stage("s10_reddit_report", "s10"),
    # S10 — buyer voice in Russian: App Store RU and Google Play RU reviews of each niche's leading apps
    Stage("s10_ru_reviews_fetch", "s10", market="ru"),
    Stage("s10_ru_reviews_classify", "s10", market="ru"),
    Stage("s10_ru_reviews_report", "s10", market="ru"),
    # S10 - buyer voice in YouTube comments (Russian and English): a separate column, never changes the S6 verdict
    Stage("s10_yt_comments_fetch", "s10"),
    Stage("s10_yt_comments_classify", "s10"),
    Stage("s10_yt_comments_report", "s10"),
    # S10 - buyer voice in Telegram group chats (Russian owners and practitioners): a separate column, never the S6 verdict
    Stage("s10_tg_fetch", "s10", market="ru"),
    Stage("s10_tg_classify", "s10", market="ru"),
    Stage("s10_tg_report", "s10", market="ru"),
    # S6 — final score, ceiling, passports; S7 — leaderboard
    Stage("s6_rescore", "s6"),
    Stage("s6_ru", "s6", market="ru"),
    Stage("s6_ceiling", "s6"),
    Stage("s6_passports", "s6"),
    Stage("s7_html", "s7"),
    # Info cohort: short video -> Telegram channel -> micro product (config/info_topics.yaml; its own score)
    Stage("info_discover", "info", market="ru"),
    Stage("info_suggest", "info"),
    Stage("info_youtube", "info"),
    Stage("info_telegram", "info"),    # Telegram funnels behind the teaching Shorts: shown in info_score, no score effect
    Stage("info_ai", "info"),          # AI substitute probe: flag I:ai-answers in info_score, no effect on the score
    Stage("info_paid", "info"),        # paid info market (Stepik, Litres): shown in info_score, no effect on the score
    Stage("info_score", "info"),
    # Russian B2B module (software registry, public procurement, Bitrix24 Market, hh.ru, Wordstat)
    Stage("ru_reestr", "ru", market="ru"),
    Stage("ru_zakupki", "ru", market="ru"),
    Stage("ru_bitrix", "ru", market="ru"),
    Stage("ru_hh", "ru", market="ru"),
    Stage("ru_wordstat", "ru", market="ru"),
    Stage("ru_vendor_revenue", "ru", market="ru"),   # income of registry vendors (FNS open data from financial statements)
    Stage("ru_ecosystems", "ru", market="ru"),
    Stage("ru_report", "ru", market="ru"),
]

BY_NAME = {s.name: s for s in STAGES}
GROUPS = list(dict.fromkeys(s.group for s in STAGES))


def resolve(targets: list[str]) -> list[Stage]:
    """Stage names, group names (s0…s10, ru) or `all` → ordered unique stages."""
    picked: list[Stage] = []
    for t in targets:
        if t == "all":
            picked += [s for s in STAGES if s.in_all]
        elif t in GROUPS:
            picked += [s for s in STAGES if s.group == t]
        elif t in BY_NAME:
            picked.append(BY_NAME[t])
        else:
            raise SystemExit(f"unknown stage or group: {t}. See `nf list`.")
    seen, out = set(), []
    for s in picked:
        if s.name not in seen:
            seen.add(s.name)
            out.append(s)
    order = {s.name: i for i, s in enumerate(STAGES)}
    return sorted(out, key=lambda s: order[s.name]) if len(targets) > 1 or targets == ["all"] else out
