# Stage reference

Every stage registered in `src/nichefinder/stages/__init__.py`, in execution order (`nf run all`; `nf run <stage|group>`). Paths are relative to the workspace: `raw/` = `data/raw/`, `out/` = `data/out/`, `cache/` = `data/cache/<namespace>/`. For why each stage exists and how its numbers are used, see [methodology.md](methodology.md).

Conventions

- **Keys** are environment variables (`.env`): `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD`, `YANDEX_API_KEY`, `YOUTUBE_API_KEY`, `LLM_API_KEY` (+ `LLM_BASE_URL`, `LLM_MODEL`). A stage whose keys are missing is skipped. "none" = keyless.
- **Tools**: `node` (Google Play scrapers), `trendspy` (Google Trends), `curl` (HTTP fallback for sites that reject Python clients).
- **Cost**: money or quota. Every network response is cached, so re-runs are free.
- Market `ru` stages run only when `nf.yaml` lists the `ru` market.
- `manual` stages (not in `nf run all`) are run on a schedule you choose.
- Order: `s9_entrants` and a first `s6_score` pass run right after S5, because the S8 and S10 reports show each niche's score and verdict; `s6_rescore` scores again once S8–S10 outputs exist. The tables below are grouped by stage family, not by run order — `nf list` shows the exact order.

Run-order logic: S0 -> S1 -> S2 -> S3 -> S4 -> S5 -> S8 -> S9 -> S10 -> S6 -> S7 (the score reads S4, S5, S8, S9 outputs, which is why S6 comes after S10 in the registry). The info cohort (`info_*`) runs after S7, then the Russian module (`ru_*`) runs last.

## S0 - Universe

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s0_yc` | accelerator company JSON (yc-oss open API) | `raw/yc_*.json`, `raw/yc_companies.csv` (recent batches; out-of-scope industries dropped: medicine, biotech, hardware, regulated finance, crypto, defence, government) | none | free |
| `s0_appstore_top` | iTunes RSS top-grossing feeds by genre (US + other storefronts; games and medicine excluded) | `raw/appstore_top.csv` | none | free, ~1 request per genre/storefront |
| `s0_producthunt` | Product Hunt GraphQL API v2: featured posts by votes, top `--top-month` (60) per month for 12 months and top `--top-week` (20) per week for 52 weeks (the web pages are behind a Cloudflare challenge) | `raw/ph_top.csv` (period, name, slug, tagline, votes, topics) | `PRODUCTHUNT_TOKEN` (free developer token) | free; complexity limit 6,250 per 15 min, the stage waits for the reset; cached per page |
| `s0_empireflippers` | Empire Flippers public JSON API, all listings (for sale and sold), 100 per page | `raw/ef_listings.csv` (P&L, price, multiple, status, monetizations, `kind` = software / digital / other) | none | free; ~29 requests, cache per month of the run |
| `s0_tinyseed` | bootstrapped-fund portfolio page(s) | `raw/tinyseed_portfolio.csv` | none | free |
| `s0_gplay_top` | Google Play top charts, every non-game category x {US grossing, second-market grossing, second-market free} | `raw/gplay_top.csv` | node (`google-play-scraper`) | free; ~1 request/s, minutes |
| `s0_wordpress` | WordPress.org plugin API (`plugins/info/1.2`), 250 plugins per page, ordered by popularity | `raw/wordpress_plugins.csv` (active installs, ratings, tags) | none | free |
| `s0_shopify` | Shopify App Store: `/browse` -> subcategories -> app cards | `raw/shopify_apps.csv` (name, rating, reviews, price text) | none (curl) | free; page walk takes tens of minutes |
| `s0_betalist` | BetaList chronological list `betalist.com/startups?page=N`, newest first, until `--months` (12) back | `raw/betalist.csv` (name, slug, tagline, date, url); pre-launch, `source_type=rising` | none | free; ~110 pages a year, 1.5 s apart (~4 min the first time); cache per month of the run |
| `s0_productradar` (`ru`) | Product Radar feed via WordPress `admin-ajax` (`action=more-handler`, `group_by=month`), `--months` (12) | `raw/productradar.csv` (name, description, month, votes, comments, categories, founder asks: partners / investors / mentor / roast...) | curl (the site's TLS chain fails Python's check) | free; ~3 requests a month of history |
| `s0_kickstarter` | Web Robots monthly Kickstarter dump (line-delimited JSON, gzip), the latest on or before the run date or `--dump` | `raw/kickstarter_projects.csv` (projects launched within 24 months), `out/kickstarter_categories.csv` (per subcategory: launches 12m vs prior 12m, success rate, money pledged), `reports/S0-kickstarter.md` | none | free; one ~120 MB download per dump, kept in `cache/kickstarter/` |
| `s0_merge` | all `raw/*.csv` above (Kickstarter: successful projects with >= 200 backers) (+ optional directory category index and ranking-site rows if present) | `out/universe.csv` (entity, source, source_type, geo, side, category, one_liner, signal, url, niche_id) + per-source summary | none | free |

## S1 - Niches

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s1_niches` | `out/universe.csv` (and your own research); `niches.yaml`, `queries/*.yaml` are the source of truth you author; this stage validates the schema and renders the niche list for the checkpoint review | validated `niches.yaml`/`queries/`, rendered niche list (`reports/`) | none (an LLM is optional and only for drafting by hand) | free |
| `s1_coverage` | `out/universe.csv`, `niches.yaml`, `config/coverage_keywords.yaml`, `config/coverage_conclusions.md` (optional) | `out/coverage.csv` (entity -> niches), `reports/S1-coverage.md` (coverage by source, frequent terms among unmatched rows, unmatched top-grossing apps by genre) | none | free |

## S2 - Query validation

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s2_suggest` | anchor + category queries from `queries/*.yaml` | `out/suggest_en.csv` (Google autocomplete), `out/suggest_ru.csv` (Yandex suggest) | none | free |
| `s2_wordstat` (`ru`) | all Russian queries (order: anchors, brands, categories, problems) | `out/wordstat_ru.csv` (keyword, niche_id, intent, anchor, `total_count`, `nested_json` with the top-50 nested phrases), `out/wordstat_progress.log` | `YANDEX_API_KEY` | free; quota 100 requests/hour -> a full run of ~500 phrases takes ~5 hours; restart resumes from cache |

## S3 - Search demand quick filter

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s3_dataforseo` | all queries of all niches; markets from `nf.yaml` | `out/dfs_us.csv`, `out/dfs_ww.csv`, `out/dfs_ru.csv` (keyword, search_volume, cpc, competition_index, `monthly_json` with up to 48 months) | `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | paid: ~$0.09 per call of up to 1,000 keywords; one call per market, about $0.27 for the three markets and ~1,000 keywords. Batches cached by hash, re-runs free |
| `s3_metrics` | `out/dfs_*.csv`, `out/wordstat_ru.csv` (optional), `niches.yaml`, `queries/`, `config/score.yaml` | `out/metrics_quick.csv`: demand, CPC, competition index, brand share / HHI / top-1, trend metrics (`yoy`, `yoy_pre`, `momentum`, `cagr_3y`, `spike`, `step_2025`, `hump_2024`, `demand_2023`), verdict, quick score, gate flags `G0/G1/G2/G4/Q:*/I:brand_share` | none | free |
| `s3_report` | `out/metrics_quick.csv` | `reports/S3-quick-filter.md` (leaderboards per market, control niches, shortlist candidates) | none | free |
| `s3_ai_volume` (manual, group `exp`) | English queries, `out/dfs_us.csv`, `config/score.yaml` (`demand_vol`) | `out/ai_volume_us.csv` (per keyword: Google volume, DataForSEO `ai_search_volume`, 12-month AI history), `out/ai_volume_niches.csv` (category demand percentile from each source, shift), `reports/S3-ai-volume.md` (Spearman per intent and across niches, pre-registered verdict, suspected word-form collisions, navigational queries the index cannot see, monthly AI/Google ratio). An experiment: the index is modeled from Google People Also Ask, so it never feeds the score | `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | paid: $0.0001 per keyword, about $0.19 for 1,700 keywords; cached by batch. Its own group, so `nf run s3` never pays for it |

## S4 - Trend depth

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s4_trends` | shortlist (`config/shortlist.yaml`), anchors from `queries/`, broad-anchor fallbacks, `config/trends_brands.yaml` | `out/trends_deep.csv` (per anchor and kind `anchor`/`broad`/`brand`: annual means 2021-2024, `yoy_24_23`, `yoy_23_22`, slope, verdict; `NA` when index < 5) | `trendspy` | free; throttled, about 12 s per uncached query |
| `s4_wordstat_dynamics` (`ru`) | Russian anchors of niches with geo `ru`/`both`, extra corrected phrases | `out/wordstat_dynamics.csv` (36 monthly points, `yoy`, `yoy_pre`, `momentum`, verdict) | `YANDEX_API_KEY` | free; shares the 100/hour quota |

## S5 - Supply depth

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s5_appstore` | shortlist, category queries, `config/appstore_relevance.yaml` | `out/appstore_apps.csv` (every app: trackId, ratings, release/update dates, price, developer, hits, `relevant`), `reports/appstore_review.md` (top 25 per niche for eyeball check) | none (iTunes Search API, 200 results/query) | free |
| `s5_appstore_metrics` | `out/appstore_apps.csv` | `out/appstore_metrics.csv` (`players_1k/10k`, `top1/top3/hhi` by ratings, `new_12m/new_24m`, `free_share_top20`, `top_seller_share`); niches with `na: true` skipped | none | free |
| `s5_capterra` | `config/capterra_map.yaml` (niche -> category slug) | `out/capterra_products.csv`, `out/capterra_categories_stats.csv` (products in category, reviews, top-1/top-3/HHI); HTML cached | none (curl may be needed) | free; ~25 cards on page 1, 50 per further page |
| `s5_shopify_metrics` | `raw/shopify_apps.csv`, `config/shopify_map.yaml`, `config/shopify_generic.yaml` | `out/shopify_metrics.csv` (share = app reviews / subcategory reviews, players >= 100 reviews, free-plan share) | none | free |
| `s5_pricing_b2b` | top products per B2B niche from the Capterra stage, `config/capterra_generic.yaml` | `out/pricing_b2b.csv` (start price, billing period, model, free trial / free version from GetApp cards) | none | free |
| `s5_pricing_b2c` | relevant apps per niche | `out/pricing_b2c.csv` (per app), `out/pricing_b2c_niche.csv` (in-app purchases from apps.apple.com pages; min monthly / annual / lifetime) | none | free |
| `s5_deals` | S0 corpora (`raw/`, incl. BetaList, Product Radar and Kickstarter of the last 12 months, which are shown in passports but not scored), `config/deal_keywords.yaml` (regexes with `not` exclusions; Product Radar also by the Russian coverage phrases) | `out/deals.csv` (per-niche counts), `out/deals_matches.csv` (what matched, for verification) | none | free |
| `s5_ai_substitute` | shortlisted niches (`--all`, `--niches`), `niches.yaml` `who` / `task` / `product` / `competitors`, `config/overrides.yaml` `platform_risk` | `out/ai_substitute.csv` (per niche: `covers` 0-2 = median over three buyer requests, `votes`, manual `platform_risk`, `check` when the probe rates the chatbot above the manual call, DIY route, brands the chatbot recommends, listed competitors named, what the chat can and cannot do), `out/ai_substitute_answers.jsonl` (requests, answers, per-run ratings), `reports/S5-ai-substitute.md`. Evidence for G3, not a gate; passports show it | `LLM_API_KEY` | 7 LLM calls per niche (cents for the shortlist), `--workers` threads, cached |
| `s5_merge` | `metrics_quick.csv`, `trends_deep.csv` (+ brand merge rule), app-store / Capterra / Shopify metrics, pricing, deals, `config/shortlist.yaml` | `out/supply_deep.csv`: one row per shortlisted niche, `supply_src`, top-1 / top-3 shares, players, gate `gate_s5` (`PASS`, `FAIL:top1`, `FAIL:players`, `NA`, `NA:proxy`), final trend verdicts | none | free |

## S8 - Demand outside search

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s8_youtube_trends` | `config/youtube_topics.yaml` (topical phrases + reference topic) | `out/youtube_trends.csv` (level vs reference, 2022-2024 trend) | `trendspy` | free; throttled |
| `s8_subreddit_stats` | `config/reddit_map.yaml` | `out/reddit_subs.csv`, `out/reddit_niche.csv` (subscribers, posts/comments per hour; a static snapshot) | none | free |
| `s8_appstore_velocity` | `out/appstore_apps.csv` | `out/appstore_velocity.csv` (ratings/month since release, `new_24m`, `new_share`, `vel_total_pm`, `vel_median_pm_top20`, per niche and store) | none | free, offline |
| `s8_gplay_search` | category queries of the shortlist | `out/gplay_search.csv`, `out/gplay_search_plan.json` | node (`google-play-scraper`) | free; slow, rate-limited |
| `s8_gplay_filter` | `out/gplay_search.csv`, `config/deal_keywords.yaml`, `config/coverage_keywords.yaml` | `out/gplay_match.csv` (relevant apps, capped per niche and country) | none | free |
| `s8_gplay_details` | `out/gplay_match.csv` | `out/gplay_apps.csv` (installs, ratings, release date, price/IAP); cache `cache/gplay_app/` | node | free; ~1 card/s; supports sharding `k/N` |
| `s8_gplay_metrics` | `out/gplay_apps.csv`, `config/gplay_exclude.yaml` | `out/gplay_metrics.csv` (installs sum, players 100k / 1M, top-1 share, new in 24 months, paid share) | none | free |
| `s8_hh` (`ru`) | Russian brand queries of B2B niches | `out/hh_vacancies.csv`, `out/hh_niche.csv` (vacancies mentioning the brand) | none; needs Russian egress (`proxy="ru"`) | free |
| `s8_hn_mentions` | Latin coverage phrases of the shortlist; Algolia HN Search API, exact phrase in titles of Show HN + Ask HN posts, 36 months | `out/hn_niche.csv` (Show HN / Ask HN in 12m vs prior 12m, `hn_trend`, top posts), `out/hn_matches.csv` | none | free; one request per search term, 0.3 s apart |
| `s8_hn_hiring` | monthly "Ask HN: Who is hiring?" threads, `--months` (36) | `raw/hn_hiring.csv` (all postings: month, company, headline, text), `out/hn_hiring_niche.csv` (postings 12m vs prior 12m per niche, recent companies), `out/hn_hiring_matches.csv` | none | free; one request per month (~0.5 MB) |
| `s8_offsearch` | `youtube_trends.csv`, `reddit_niche.csv`, `appstore_velocity.csv`, `gplay_metrics.csv`, `hh_niche.csv`, `hn_niche.csv`, `hn_hiring_niche.csv` | `out/offsearch.csv` (per niche, with `offsearch_flags` confirming / contradicting the search signals; used by the second-platform rule) | none | free |

## S9 - Supply over time

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s9_snapshot` (manual) | `freeze`: current `appstore_apps.csv` / `gplay_apps.csv`; `refresh`: fresh App Store counts; `diff`: two snapshots | `data/snapshots/<date>/`, `out/snapshot_diff_*.csv`, `reports/S9-snapshot-<date>.md` (growth by app and niche, share of growth from new apps, leader share of growth) | none (iTunes lookup, 150 ids per call, ~40 calls) | free; run `freeze` once, `refresh` + `diff` ~30 days later |
| `s9_gplay_refresh` (manual) | base snapshot `gplay.csv` | `data/snapshots/<date>/gplay.csv`; separate cache `cache/gplay_app_<date>/` | node | free; ~1 card/s |
| `s9_entrants` | `out/appstore_apps.csv` (US, relevant, released 12-24 months ago) | `out/entrant_survival.csv` (cohort size, share updated within 180/90 days, share with >= 1,000 ratings, flag `E:churn` / `E:traction` when cohort >= 8) | none | free, offline |

## S10 - Buyer voice

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s10_reddit_fetch` | `config/reddit_terms.yaml` (subreddits, terms, brands, seller pseudo-niches) | `cache/arctic/<niche>_posts.jsonl`, `_comments.jsonl`; `out/reddit_fetch_log_*.csv`, `out/reddit_subs_stats_*.csv` | none (Arctic Shift archive; ~15 % of connections may be reset - retries are cached; shardable) | free; ~155 pages/minute; hours for the full shortlist |
| `s10_reddit_threads` | matched posts of large subreddits | appends comments of the densest threads to `cache/arctic/<niche>_comments.jsonl` (up to 3 pages x 100 per thread) | none | free |
| `s10_reddit_classify` | `cache/arctic/*.jsonl` | `out/reddit_voice_items.jsonl`, `out/reddit_voice_llm.csv` (intent shares, themes), `out/reddit_voice_themes.json` (pains clustered into themes); tiered sampling | `LLM_API_KEY` (+ `LLM_BASE_URL`, `LLM_MODEL`) | LLM tokens; thousands of short items per niche; responses cached |
| `s10_reddit_metrics` | `cache/arctic/*.jsonl`, `config/reddit_terms.yaml` | `out/reddit_voice.csv` (per niche: documents, marker shares, top-1 brand share, trend), `out/reddit_brands.csv`, `out/reddit_monthly.csv` | none | free |
| `s10_reddit_report` | the three CSVs above, `reddit_voice_llm.csv`, `reddit_voice_themes.json`, `score_final.csv` (if present) | `reports/S10-reddit-voice.md` with the verdict rule (satisfied / seeking / leader / seeking-but-satisfied / weak / quiet) | none | free |
| `s10_ru_reviews_fetch` (market `ru`) | `out/appstore_apps.csv` (RU store, relevant), `out/gplay_apps.csv` (RU), `config/startpack_map.yaml` (Startpack products per niche), shortlisted niches with geo `both`/`ru`, `config/ru_reviews.yaml` (`fetch`) | `out/ru_reviews_docs.jsonl` (one review per line and niche), `out/ru_reviews_apps.csv` (per product: ratings, reviews fetched and kept, status) | none (App Store RSS; Google Play through the `gplay_reviews.mjs` Node helper, skipped without Node; Startpack HTML, 1 request/s) | free; the run month is in the cache key, so a re-run in the same month is offline |
| `s10_ru_reviews_classify` (market `ru`) | `out/ru_reviews_docs.jsonl`, `config/ru_reviews.yaml` (`sample`) | `out/ru_reviews_items.jsonl`, `out/ru_reviews_llm.csv` (shares: unmet needs, quality complaints, praise), `out/ru_reviews_themes.json` (pain themes, switches, intents per app) | `LLM_API_KEY` | LLM tokens: up to 240 reviews per niche, 12 per call, plus one clustering call; `--dry` estimates |
| `s10_ru_reviews_report` (market `ru`) | the outputs above, `score_final.csv` (if present), `niches.yaml` (side), `config/ru_reviews.yaml` (`verdict`, `status`) | `out/ru_reviews_verdict.csv`, `reports/S10-ru-reviews.md` (verdict gap / quality / unmeasured / content / mixed / quiet, percentiles within the B2C and B2B segments; the gap counts unmet needs only in reviews of 3 stars or lower, read from `ru_reviews_items.jsonl`; DRAFT banner while the thresholds are not fixed) | none | free |

## S6 - Score, path to goal, passports; S7 - report

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `s6_score` | `out/supply_deep.csv`, `out/metrics_quick.csv`, `out/offsearch.csv`, `out/entrant_survival.csv`, `config/score.yaml`, manual overrides (lock-in, feasibility, platform risk, verdicts) | `out/score_final.csv`: score, block scores (`s_demand`, `s_growth`, `s_frag`, `s_deals`, `s_switch`), gates failed, flags, verdict, ticket tier | none | free, offline |
| `s6_rescore` | same as `s6_score`, now with S8–S10 outputs | rewrites `out/score_final.csv` | none | free, offline |
| `s6_ru` (`ru`) | Wordstat metrics and dynamics, Russian App Store set, manual Russian notes | `out/score_ru.csv`, `reports/S6-ru.md` | none | free |
| `s6_ceiling` | `score_final.csv`, `supply_deep.csv`, `appstore_velocity.csv`, `capterra_categories_stats.csv`, `shopify_metrics.csv`, `offsearch.csv`, `config/ceiling.yaml`, `config/overrides.yaml` (`fit`, `size_override`), `nf.yaml: goal`, `default_fit` | `out/path_to_goal.csv` (price, ARPU, payers needed, niche payers estimate and proxy, required share, position, ticket tier, fit, grade A/B/B-/C), `reports/S6-path-to-goal.md` | none | free, offline |
| `s6_passports` | all `out/*.csv` above, `niches.yaml` | `reports/passports/<niche>.md`, `reports/S6-passports.md` (leaderboard, gates, cut niches) | none | free |
| `s7_html` | passports, `score_final.csv`, `path_to_goal.csv` | `reports/leaderboard.html`: self-contained HTML leaderboard (filters, sort, expandable passports, path-to-goal columns) | none | free |

## Info cohort (`info`): short video -> Telegram -> micro product

Independent of the software score; topics live in `config/info_topics.yaml`, weights in `config/score_info.yaml` (methodology: "Info" in section 5 and 7.6). Without topics or seeds the stages do nothing.

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `info_discover` (`ru`) | `config/info_discover.yaml` (intent stems without topics, `min_count`, `batch`, `top_n`) | `out/info_discover_phrases.csv` (phrase, impressions, stems, kind L/F/M/O, topic, area), `out/info_discover.csv` (topics by demand: sum of non-nested phrases, head phrase, learn/fix/material mix, examples), `reports/info_discover.md`; `--write-topics [N]` replaces the topics in `info_topics.yaml` (a hand-made previous list is kept in `info_topics.previous.yaml`); `--dynamics [N]` adds trend, yoy and momentum of the top N topics' head phrases | `YANDEX_API_KEY`, `LLM_API_KEY` | one Wordstat request per stem; ~45 LLM calls for ~11k phrases (cents); all cached |
| `info_suggest` | `info_topics.yaml` `_settings.seeds` (or `--seed`), `lang`, `region` | `out/info_suggest.csv` (seed, phrase, hits = expansions that returned it, best position, already a topic phrase) | none | free; ~30 autocomplete requests per seed |
| `info_youtube` | `info_topics.yaml` topics (`q`: one subject phrase of 1-3 words; optional `must` / `must_not` regexes), `score_info.yaml` `measure` | `out/info_youtube.csv` (per topic: status ok / global / quota / empty, videos dropped by language and by `must`, Shorts kept, views median/p90, breakout share, small-channel share, top-3 channel share, Telegram and offer shares, recent/older), `out/info_youtube_videos.csv` (per video) | `YOUTUBE_API_KEY` | free quota of 10,000 units/day: ~100 units per phrase + 2-4 for statistics; `--budget` caps a run, a run stopped by the quota resumes from cache |
| `info_ai` | `info_topics.yaml` topics (`who`, `task`, `product`), `_settings.lang` | `out/info_ai.csv` (per topic: `covers` 0-2 = how much of the micro product a free chatbot answer gives away, median over three buyer requests; `votes`; what the chat can and cannot give), `out/info_ai_answers.jsonl` | `LLM_API_KEY` | 7 LLM calls per topic (cents for 60 topics), `--workers` threads, cached |
| `info_score` | `out/info_youtube*.csv`, `out/info_ai.csv` (optional), both configs, `nf.yaml` `verdict.green_min_score` | `out/info_score.csv`, `reports/info.md` (ranking, gates, flags incl. `I:ai-answers`, AI covers column, example videos per topic; a DRAFT banner while the weights are not fixed) | none | free, offline |

## Russian B2B module (`ru`)

| Stage | Inputs | Outputs | Keys / tools | Cost |
|---|---|---|---|---|
| `ru_reestr` | `config/ru_b2b_niches.yaml` (`reestr` keys); software registry search by product name, 100 per page; with `--classes`, the classifier map | `out/ru_b2b_reestr.csv`, `ru_b2b_reestr_items.csv`, `ru_b2b_reestr_classes.csv` (products, rights holders, new per registration year, largest-holder share) | none | free |
| `ru_zakupki` | `ru_b2b_niches.yaml` phrases | `out/ru_b2b_zakupki.csv` (public procurement count, last 12 vs previous 12 months, sum and median of starting price for tenders with the phrase in the title) | none | free; full-text hits include attachments (noisy) |
| `ru_bitrix` | `ru_b2b_niches.yaml` (`bitrix` keys) | `out/ru_b2b_bitrix.csv`, `ru_b2b_bitrix_apps.csv` (apps, installs, leader share; up to 3 result pages; fuzzy search = coarse signal) | none | free |
| `ru_hh` | `ru_b2b_niches.yaml` (`hh_roles`, `hh_brands`) | `out/ru_b2b_hh.csv`, `ru_b2b_hh_terms.csv` (vacancies by role in title; by brand in title or description) | none; Russian egress (`proxy="ru"`) | free |
| `ru_wordstat` | `ru_b2b_niches.yaml`, `config/ru_b2b_traps.yaml` | `out/ru_b2b_wordstat.csv`, `ru_b2b_wordstat_dyn.csv` (brands + category phrases, 36-month dynamics) | `YANDEX_API_KEY` | free; shares the Wordstat quota |
| `ru_report` | the five outputs above | `out/ru_b2b_score.csv`, `reports/S0-ru-b2b.md` (score: demand 35, growth 20, fragmentation 25, money 20; rule-based verdict) | none | free |

## Typical total cost

A full run for ~100 niches and ~1,000 keywords costs about **$0.3** of DataForSEO credit plus LLM tokens for the S10 classification. Everything else is free; time is dominated by the Wordstat quota (hours), the Google Play card scrape (~1 card/s), the Reddit export, and Trends throttling.
