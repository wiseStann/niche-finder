# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`niche-finder` (package `nichefinder`, CLI `nf`) is a market-research pipeline. Each niche is described as **who × task × product**; the pipeline measures search demand, supply fragmentation, pricing, off-search demand and buyer voice (Reddit + LLM), then scores each niche and gives it a red/yellow/green verdict. The owner uses it to pick a niche for their own product, which can be anything from a paid PDF guide to B2B SaaS, so the bundled software-heavy catalog is a starting point, not a limit. Screening is not validation (see `docs/methodology.md` §10–11).

## Commands

Requires Python ≥3.10. The only runtime dependency is pyyaml; `trendspy` is the optional `[trends]` extra and pytest is `[dev]`. Node 18+ is needed only for the Google Play stages.

```bash
python -m venv .venv && source .venv/Scripts/activate   # Linux/macOS: .venv/bin/activate
pip install -e ".[trends,dev]"

python -m pytest -q                                       # all tests, offline, ~2 s
python -m pytest tests/test_core.py::test_http_cache_hit_needs_no_network
python -m pytest -k s6_score                              # stage tests are parametrized by stage name

nf init <folder>                  # new workspace from src/nichefinder/examples/default (165 niches)
nf -w <folder> doctor             # keys, tools, niche count
nf validate                       # schema check of niches.yaml + queries/*.yaml
nf list                           # stages in run order, with readiness
nf run all                        # stages with a missing key/tool are skipped, not failed
nf run s3                         # one group
nf run s3_report -- --help        # one stage; args after `--` go to that stage only
nf setup node                     # npm-installs google-play-scraper into the workspace
python scripts/render_idea_sources.py   # regenerate docs/idea-sources.md from docs/idea-sources.yaml (never edit the .md)
```

CI (`.github/workflows/ci.yml`) runs pytest on Linux/Windows/macOS × Python 3.10/3.12, then runs `nf init` + `nf validate` on the example workspace. The repo has no linter config.

## Local setup in this checkout

- `.venv/` at the repo root: Python 3.12, package installed in editable mode with `[trends,dev]`.
- `workspace/` at the repo root was created with `nf init workspace`. It is gitignored, including its `.env`. `google-play-scraper` is installed in `workspace/node_modules`. Run `nf` from inside `workspace/` or pass `-w workspace`.
- `workspace/.env` holds the DataForSEO, LLM, Yandex and YouTube Data API keys, so `nf run all` runs every stage. DataForSEO is prepaid: `s3_dataforseo` prints the expected cost and the balance before it pulls. `workspace/nf.yaml` has `markets: [us, ww, ru]`, so the Russian module (`ru_*`, `s6_ru`, `s8_hh`, Wordstat) is on.
- Wordstat allows about 100 requests per hour, so an uncached `s2_wordstat` or `s4_wordstat_dynamics` run takes hours. Run them in the background; a restart resumes from the cache.
- The Windows console is cp1252: a script that prints Cyrillic needs `PYTHONIOENCODING=utf-8`, or `sys.stdout.reconfigure(encoding="utf-8")` under `python -I`, which ignores that variable.

## Architecture

### Code vs workspace

Code lives in this repo. All research state lives in a **workspace**: a folder with `nf.yaml`, found through `-w`, `$NF_WORKSPACE`, or the nearest parent folder that has `nf.yaml`. `Workspace` (`src/nichefinder/workspace.py`) is the only way stages get paths, settings and dates: `ws.out()`, `ws.raw()`, `ws.report()`, `ws.cache(namespace)`, `ws.load_config()`, `ws.setting("a.b")` and `ws.today`. `ws.today` honours `as_of` in `nf.yaml`, so a past run can be reproduced from cache. Don't hardcode paths or use `date.today()` in data logic.

`src/nichefinder/examples/default/` is package data that `nf init` copies. Editing it changes only workspaces created later. To change the actual research, edit the workspace's `niches.yaml`, `queries/` and `config/`.

### Stages

Each pipeline step is a module in `src/nichefinder/stages/`, registered in `STAGES` in `stages/__init__.py`. The registry order is the `nf run all` order. `tests/test_stages.py` enforces this contract:
- `SUMMARY: str` and `run(ws, args)`. Optional: `KEYS` (env vars; if one is missing the stage is skipped), `NEEDS` (a subset of `node`, `trendspy`, `curl`) and `add_arguments(parser)`.
- `Stage(..., market="ru")` runs only when `nf.yaml` markets include `ru`. `in_all=False` marks a manual stage (snapshots) that `nf run all` skips.
- Cyrillic may appear only in data literals, never in comments or docstrings.

Raising `keys.MissingKey` or `tools.ToolMissing` inside `run` makes the CLI skip the stage instead of failing it.

Stages talk to each other only through workspace files: `data/raw/*.csv` (S0 dumps) → `data/out/*.csv|json` → `reports/*.md` and `reports/leaderboard.html`. The main hand-offs:
- `metrics_quick.csv` (S3) → `config/shortlist.yaml`. `s3_report` writes the shortlist only when the file is missing, or with `--rewrite-shortlist`. It is a human checkpoint. Tiers: `tier_a` passed the gates, `tier_b` was cut only by the top-1 brand gate, `tier_c` holds the control niches S3 has not settled (they are scored in the same cohort for calibration).
- The deep stages S4, S5, S8 and S9 measure only shortlisted niches.
- `supply_deep.csv` (S5) → `score_final.csv` (S6) → passports and the leaderboard.

The `info` group (`info_discover` → `info_suggest` → `info_youtube` → `info_telegram` → `info_score`) is a separate cohort for micro info products sold through short video and a Telegram channel. Its topics live in `config/info_topics.yaml`, not in `niches.yaml`, and it has its own score in `config/score_info.yaml` (methodology §5 "Info" and §7.6). It never mixes with the software score. Without topics or seeds its stages print a note and do nothing. `info_discover` builds the topic list from demand data (Wordstat top requests for topic-free intent stems, sorted into subjects by an LLM). `--write-topics` overwrites the topics in `info_topics.yaml`, and the previous list is kept in `info_topics.previous.yaml`, because the workspace is not under git. `info_youtube` spends YouTube quota: 10,000 units and 100 search calls a day, and a search page costs 100 units (two pages per phrase). Its metrics count only the Shorts an LLM labels as teaching (`kind`), because the most viewed top of broad subjects is mostly comedy. `info_telegram` reads the public t.me pages of the Telegram channels those Shorts link to (subscribers, payment links); no key. `--budget` caps a run, and a run stopped by the quota resumes from the cache the next day. The API key goes in the `X-Goog-Api-Key` header, never in a URL (`sources/youtube.py`). The weights stay `status: draft` until the owner fixes them, and `reports/info.md` shows a DRAFT banner until then.

S10 has two buyer-voice sources. Reddit (`s10_reddit_*`) is English. Russian reviews (`s10_ru_reviews_fetch` → `s10_ru_reviews_classify` → `s10_ru_reviews_report`, market `ru`) read the Russian App Store and Google Play reviews of the apps that S5 (`appstore_apps.csv`) and S8 (`gplay_apps.csv`) found for niches with geo `both`/`ru` and that pass an LLM product check (S5/S8 relevance lets in games and giants such as Instagram; decisions in `ru_reviews_fit.csv`, manual `apps` keep/drop in the config), plus Startpack reviews of business software (`sources/startpack.py`) for the products listed per niche in `config/startpack_map.yaml`, a hand-kept map. The reviews verdict compares niches with each other (percentile plus a floor) within the B2C and B2B segments, because written reviews lean negative and Startpack leans positive. Its gap counts a missing feature or a switch only in a review of 3 stars or lower, and a niche with too few such reviews is `unmeasured` (most Startpack reviews are five-star). Price complaints are not a gap (they peak in saturated clone markets) but a separate `💰 paywall` mark that never changes the verdict. Its thresholds are in `config/ru_reviews.yaml` and stay `status: draft` until the owner fixes them. Like the Reddit verdict, it never changes the S6 verdict; passports and the leaderboard show it as a separate column.

The AI substitute probe (`src/nichefinder/aiprobe.py`) asks whether a free chatbot answer replaces the product: the LLM writes three buyer requests, answers each as a free chatbot, a separate judge call rates `covers` 0-2, and the median counts. `s5_ai_substitute` runs it for shortlisted software niches as evidence for the manual G3 `platform_risk` (it flags disagreements, never sets the gate; passports show it). `info_ai` runs it for info topics, and `info_score` shows the rating and the flag `I:ai-answers`, with no effect on the score. `s3_ai_volume` is a paid experiment in its own group `exp` (manual, so `nf run s3` never pays for it). It compares DataForSEO's `ai_search_volume`, which is modeled from Google People Also Ask, with Keyword Planner and never feeds the score. Its first run found nothing usable (methodology §5 S3).

Evidence-only sources (added 2026-11-21) never touch the score, a gate or a verdict; `src/nichefinder/evidence.py` renders their passport blocks and leaderboard tags in one place. `s3_switch_intent` (paid: "<brand> alternative" / "cancel <brand>" / "аналог <brand>" volumes vs brand demand) and `s5_serp` (paid: who owns the Google top 10 for category queries, AI Overview share, Labs keyword difficulty) both check the DataForSEO balance and stop before paying when it is below 1.5x the estimate. `s8_who_counts` counts the target industry in US Census bulk files (CBP establishments and Nonemployer firms, keyless) and joins the Russian SME register counts of `ru_msp_counts` (2 x 2.2 GB FNS dumps on the first run, counted while streaming, the per-dump aggregate in `data/out/ru_msp/` is the cache; group `ru` but placed before `s8_who_counts` in the registry); NAICS / OKVED codes per niche are hand-kept in `config/who_counts.yaml`, and passports divide the payers needed by the US count. `ru_vendor_revenue` matches the software register's right holders to the FNS open dataset of income from financial statements (bo.nalog.ru is not used: it serves scripts an empty shell). `s9_wayback` dates the websites of the top App Store apps (sellerUrl from the S5 cache) in the Wayback Machine. Also `s5_ecosystems` (Chrome Web Store, Atlassian Marketplace), `s5_oss` (GitHub substitutes), `s8_freelance` (Kwork and FL.ru posts within robots.txt, kept in a cumulative history; LLM labels build / service), `s0_trustmrr` (Stripe-verified MRR, through `s5_deals`), `s0_regulation` (a discovery report of rules with compliance deadlines; never writes niches), `s10_yt_comments_*` (Russian buyer voice in YouTube comments), `info_paid` (Stepik and Litres: whether people pay for a topic; flags in `info_score`, no score effect) and `ru_ecosystems` (MoySklad catalogue and amoCRM showcase; YCLIENTS needs a partner token). `http.download` resumes an interrupted `.part` with a Range request.

In `s6_score`, required inputs fail with a hint ("run the S5 stages first") and optional inputs (S8 `offsearch.csv`, S9 `entrant_survival.csv`) are read as empty when missing.

The run order has one non-obvious part. `s9_entrants` and a first `s6_score` pass run right after S5, because the S8 and S10 reports display score and verdict. `s6_rescore` re-exports `s6_score.run` and scores again after S8–S10.

To add a data source, write a new stage module and add it to the registry. Vendor adapters shared by several stages go in `src/nichefinder/sources/` (DataForSEO, autocomplete, Wordstat). Node helpers for Google Play are the `.mjs` files in `src/nichefinder/node/`, run through `tools.run_node`.

### Shared infrastructure

- `http.py`: stdlib-only HTTP with retries and a disk cache keyed by the SHA-1 of the URL (or URL + body). `backend="curl"` or `"auto"` handles sites that block Python clients, and `proxy="ru"` routes a request through `NF_PROXY_RU`. `get_text(min_size=...)` does not cache short responses, which are usually block pages; a block page can be larger than any floor (Capterra's Cloudflare "Security Check" is 44 KB), so a scraper also checks for its markers (`s5_capterra.blocked`). Route every external call through it with `cache=ws.cache("<namespace>")`, so re-runs are free and work offline.
- `llm.py`: any OpenAI-compatible chat endpoint (DeepSeek by default), JSON mode, cached in `data/cache/llm/`. Configured with `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` and `LLM_EXTRA_BODY`.
- `appfit.py`: the LLM product check. Store search relevance lets in games, apps for the other side of a market and giants (Instagram for transcription), so `s5_appstore` (the `relevant` flag every App Store consumer reads), `s8_gplay_filter` (the Google Play set, before its 30-app cap; the store description stands in for the missing genre) and `s10_ru_reviews_fetch` ask, per niche, which candidates these users would choose for the task.
- `keys.py`: keys come from the environment or `<workspace>/.env`, and the environment wins. `keys.GROUPS` drives the `nf doctor` hints.
- `niches.py`: loads and validates niches and queries, and gives access to the shortlist and overrides. `niches.text_matchers(ws)` is the one place that ties free text to niches: the `deal_keywords.yaml` regexes, with a fallback to coverage phrases for shortlisted niches. `with_coverage=True` adds the Russian coverage phrases for Russian text. `s5_deals`, `s8_hn_mentions` and `s8_hn_hiring` all use it.
- `http.download(url, path)`: streams large dumps (Kickstarter, ~120 MB) through a `.part` file; an existing file counts as the cache.
- Sources whose list pages shift over time (BetaList, Product Radar, HN search, Empire Flippers) put the run month (`ws.today:%Y-%m`) into the cache key, so a re-run in the same month is free and the next month fetches fresh data.

### Data model (workspace inputs)

- `niches.yaml`: `id` (a slug, used everywhere as `niche_id`), `who`, `task`, `product`, plus:
  - `geo`: `global`, `ru` or `both`; sets which query languages are required.
  - `side`: `b2b-smb`, `b2b`, `b2c` or `prosumer`; score percentiles are computed within the B2C or B2B cohort.
  - `tier`: `A` measure, `B` candidate, `C` control.
- `queries/*.yaml`: niche id → language → a list of `{q, i, b, anchor}`.
  - `i` is the intent: `category`, `problem`, `brand` or `info`. Brand queries need `b`, the brand name.
  - Each required language has exactly one `anchor: true` query.
  - Minimums per language are 3 category, 1 problem and 2 brand queries; a shortfall is only a warning. When no second brand has real demand, a YAML comment above the language block says so.
  - A category or problem query listed in two niches is warned about, because its volume counts in both; keep it in the most specific niche. Word order is ignored, as in Wordstat broad match. A shared brand query is fine: brand volume feeds only the concentration metrics.
  - Russian queries are broad match in Wordstat, so check the nested phrases (`nested_json` in `wordstat_ru.csv`) before trusting a number. Replace a query whose volume belongs to another topic and leave a trailing comment with the reason; `trap_anchor` / `trap_brands` in `config/overrides_ru.yaml` only patch `s6_ru`.
- `config/score.yaml`: weights and CPC bands.
- `config/info_topics.yaml` (info cohort): `_settings` (`lang`, `region`, `window_months`, `seeds`) and `topics` (`id`, `q`: 1-3 YouTube phrases, optional `must` regex, `who`, `task`, `product`). `config/score_info.yaml` holds the info weights, gates and the `measure` block (sample order, Shorts length, breakout and Telegram/offer regexes).
- `config/overrides.yaml`: human judgments per niche (platform risk, lock-in, feasibility, supply estimates, founder `fit`, a manual `verdict`).
- Other `config/*.yaml` files: per-source maps and exclusions.

### Methodology rules that constrain changes (`docs/methodology.md`)

- Gates, weights and thresholds are fixed in config before the run. Any change gets a written reason and is never made to rescue a favourite niche.
- Metrics are never edited by hand. Results change only through the niches, the configs and `overrides.yaml`.
- Triangulation: demand, supply and trend each need two independent sources. Control niches (tier C) must behave as expected; if one doesn't, suspect the scoring, not the control.
- Verdict: if any gate fails (G0–G5, S5 supply) the niche is red. Otherwise it is green when the score reaches `verdict.green_min_score` (70 by default) and yellow below that.
- Score = demand 30 + growth 20 + fragmentation 25 + deals 15 + switching 10, using percentiles within the cohort and a ±5% trend adjustment. Exact formulas are in the `s6_score` docstring and methodology §7. The path-to-goal grade (`s6_ceiling`) is in methodology §8.
