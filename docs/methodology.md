# Methodology: how niche-finder decides what a "green market" is

This document explains the reasoning behind the pipeline: what it measures, why, which sources it trusts, which traps it knows about, and which questions it cannot answer. Stage-by-stage inputs, outputs and costs are in [stages.md](stages.md). Weights and thresholds quoted here are the defaults shipped in `config/score.yaml`, `config/ceiling.yaml` and `nf.yaml`.

Contents

1. [What "green" means](#1-what-green-means)
2. [Design principles](#2-design-principles)
3. [Ontology: niche = who x task x product](#3-ontology-niche--who--task--product)
4. [Source priors: proven vs rising](#4-source-priors-proven-vs-rising)
5. [Stages S0-S10](#5-stages-s0-s10)
6. [Known traps and how they are caught](#6-known-traps-and-how-they-are-caught)
7. [Gates and the score](#7-gates-and-the-score)
8. [Path to goal](#8-path-to-goal-the-ceiling-layer)
9. [Buyer voice rules](#9-buyer-voice-rules)
10. [What the pipeline proves and what it cannot](#10-what-the-pipeline-proves-and-what-it-cannot)
11. [Recommended validation after screening](#11-recommended-validation-after-screening)

---

## 1. What "green" means

A green market is one where demand is real and growing, supply is fragmented, nobody owns the category, and a small team can plausibly build and sell a product. Concretely the pipeline looks for the intersection of:

| Axis | Question | Measured by |
|---|---|---|
| Demand | Do people look for this, and does a click have commercial value? | Search volume, CPC (Keyword Planner via DataForSEO; Yandex Wordstat for the Russian module) |
| Trend | Is it growing, not shrinking, not a one-off spike? | Year-over-year, 3-year CAGR, momentum, Google Trends cross-check |
| Fragmentation | Many mid-sized players, no monopolist? | Brand-query shares, HHI, top-1 share, players in app stores / software directories |
| Platform risk | Is it one native feature of Apple, Google, Microsoft, OpenAI? | Manual review per shortlisted niche, platform share of nested queries |
| Liquidity | Do small products in this space earn money and change hands? | Marketplace listings with revenue, accelerator portfolios, launches, top-grossing apps |
| Switching | Can a new entrant take customers away? | Public self-serve pricing, monthly plans, "import from" features, lock-in (manual 0-2) |
| Feasibility | Can a small team build and sell it? | Four yes/no proxies (section 7.4) |
| Veto | Regulated expertise (medicine, licensed law, regulated finance)? | `expertise_flag` |

The tool ranks markets by *relative* signals. It does not estimate market size in money (section 10).

---

## 2. Design principles

1. **The niche is the unit; the query is a measuring instrument.** Queries are never analysed without a niche they belong to. A phrase-first scan of hundreds of topics produced mostly noise: TV series that share a name with a profession, benchmark and "what is" queries, features of voice assistants, one-day launch spikes. Niche-first with typed queries removes most of it.
2. **A cost funnel.** Each stage is roughly an order of magnitude more expensive (money, quota or manual time) than the previous one and cuts at least ~60 % of what reaches it. Cheap and wide first, expensive and deep on the shortlist only.
3. **Triangulation.** No verdict rests on one source. Demand needs two sources, supply needs two, trend needs two. A concentration gate based on hand-listed brand queries is re-checked against an independent signal (app store ratings, software-directory reviews).
4. **Pre-registration.** Gates, weights and thresholds are fixed in configuration before the first API call. They may change, but every change is written down with a reason, and a change is never made to rescue a favourite niche.
5. **Controls.** The cohort always includes known-red niches (small-business CRM, task manager, notes, site builder), known "one platform feature" niches (photo restoration, translator, generic image generation), and a calibration case for the monopolist gate (a category with one product holding about half of brand searches). If a control behaves unexpectedly, the *scoring* is suspect, not the control: examine and document the formula or thresholds rather than only explaining the result away.
6. **Cache and provenance.** Every tool call is cached by a hash of its parameters; every metric carries source and date. Re-running a month later is a free re-scan, not a new project.
7. **Human checkpoints.** The pipeline runs unattended between checkpoints: after the universe (add/remove), after the quick filter (edit the shortlist), and before the final pick.
8. **What to measure is separate from what to measure with.** Niches live in YAML, tool adapters are separate modules, scoring is configuration. Swapping a data vendor does not touch niches or formulas.
9. **Metrics are never edited by hand.** Only `niches.yaml`, the configs, and an explicit manual-overrides file (lock-in, feasibility, platform-risk, supply estimates where no proxy exists) change results.

---

## 3. Ontology: niche = who x task x product

### 3.1 Granularity rule

A niche is a **segment (who) x job (task) x product shape (product)**, for example "freelancers and micro-agencies x invoice a client and get paid without an accountant x web SaaS, $10-30/month".

- **Narrow enough** when one product can serve the segment's whole task and the niche has its own vocabulary (category queries different from the parent category).
- **Broad enough** when at least 3 competitors exist and category queries total at least ~1,000 searches/month (US) - or about 500 in Wordstat for the Russian module.
- Below the threshold: merge into the parent. Above ~10 competitors with large funding rounds: split by segment.

"AI for X" is a technology, not a niche. Clustering groups by who x task, never by technology.

### 3.2 Record

Each niche in `niches.yaml` carries: `id`, `name`, `who`, `task`, `product`, `geo` (`global | ru | both` - geography is an attribute of the niche, not of the pipeline), `side` (`b2c | prosumer | b2b-smb | b2b-mid`), `sources` (where it was found; two or more different source types make the prior stronger), `expertise_flag`, `control` (`red | platform | green | null`), a competitor list (name, domain, price, self-serve, founding year, team size) and a query set.

### 3.3 Query intents

| Intent | Measures | Used for |
|---|---|---|
| `category` | Demand for the product class ("invoicing software for freelancers") | demand, CPC, competition index, trend |
| `problem` | Latent demand (the task without a product name) | `demand_latent`; never in CPC |
| `brand` | Navigational demand for a named competitor | **supply** side: brand share, HHI, top-1 share |
| `info` | Reference queries, benchmarks, "what is" | excluded from every sum; stored only so they are not mistaken for something else |

One query per niche is marked `anchor: true`; it goes to Google Trends and to the ambiguity check. A typical niche has 8-12 English queries (at least 4 category, at least 2 problem, one brand query per competitor).

---

## 4. Source priors: proven vs rising

The universe (S0) mixes sources of different kinds, and the kind is stored as an attribute because it changes how a hit should be read.

| Type | Examples | What it tells you | Prior |
|---|---|---|---|
| **Proven / transactional** (best signal of "green") | Software-directory category indexes, small-business marketplaces with revenue-verified listings (Flippa-style), bootstrapped-fund portfolios, top-grossing app charts, WordPress.org plugins by installs, Shopify App Store | Small players *already earn money* here and are bought and sold: fragmentation and deals exist | High |
| **Rising** | Accelerator batches, Product Hunt, VC portfolio maps, subscription-app reports | Demand is rising, but so is competition: reads as "who is entering", i.e. a future red ocean | Medium |
| **Regional** | Ranking sites, accelerators and procurement portals for a specific country | Local niches where Google data is thin | By data |

A niche found by both a proven and a rising source is a priority candidate. Choosing "proven above rising" is a deliberate bias: it moves results away from fashionable AI categories toward unfashionable categories where money already changes hands.

The universe is also biased by construction: it only contains things that already exist as an app, plugin or listing. Tasks that exist without a product (job postings, tenders, regulation deadlines, product shutdowns) are covered only indirectly, via S8 and the source registry (`config/sources.yaml`, rendered to `S0-sources.md`), which records for each candidate source its role (rising / transactions / voice / hiring), access method, rate limits and freshness.

---

## 5. Stages S0-S10

The funnel in one table (details in [stages.md](stages.md)):

| Stage | Question | Cost |
|---|---|---|
| S0 universe | What products and companies exist, and who pays for them? | free (public endpoints) |
| S1 niches | Which who x task x product clusters does the universe contain? | LLM-assisted authoring + review |
| S2 query validation | Are the queries unambiguous and on-topic? | free |
| S3 quick filter | Which niches have real, growing, non-monopolised demand? | ~$0.27 per full run |
| S4 trend depth | Is the growth real outside Keyword Planner? | free (Trends, Wordstat) |
| S5 supply depth | Who are the players, how concentrated, what do they charge, are deals happening? | free |
| S6 score and passports | Gates, score, verdict, path-to-goal | free |
| S7 report | Leaderboard and HTML report | free |
| S8 off-search demand | Is there demand where Google cannot see it? | free |
| S9 supply over time | Who is growing now, and do new entrants survive? | free |
| S10 buyer voice | What do buyers say about existing products? Reddit, plus Russian reviews (App Store, Google Play, Startpack for business software) for niches with geo `both`/`ru` | LLM tokens |
| info cohort | For micro info products sold through short video: does the topic draw views, can a small channel break through, do creators already sell through Telegram? | free (YouTube quota) |

### S0 - Universe

**Measures:** nothing yet; it enumerates existing products in categories where someone pays. Output is `universe.csv` (entity, source, source type, geo, side, category, one-liner, signal, URL), typically thousands of rows from about ten sources.

**Sources (public or keyless):** accelerator batches (yc-oss JSON), Product Hunt top featured launches (official GraphQL API, free token), bootstrapped-fund portfolios, Empire Flippers businesses with a verified P&L (software and digital listings, for sale and sold), App Store top-grossing charts (iTunes RSS, by genre, US and other storefronts), Google Play top charts (Node scraper), WordPress.org plugin API (active installs), Shopify App Store category walk, BetaList (pre-launch startups, newest first), Product Radar (Russian-language launches by month, `ru` market), Kickstarter (Web Robots monthly dumps: projects, outcomes and money pledged).

BetaList and Product Radar show where founders are heading (rising), not proven demand; Kickstarter shows demand paid in advance, but only for physical products, games, books and design. The three are counted per niche by `s5_deals` and shown in passports, outside the score. The Kickstarter crawl under-samples failed projects, so its success rates are inflated: compare categories with each other, not with Kickstarter's own statistics.

Empire Flippers software listings (SaaS and apps, verified P&L, all years) are matched per niche the same way and shown in passports with the median profit and multiple, also outside the score: about ten software listings a year is too few to score (section 7.2). Its Amazon, e-commerce and content listings stay out of the universe, because their descriptions match seller-tool niches although those businesses are customers of the niche, not players in it.

**TrustMRR (`s0_trustmrr`, evidence).** TrustMRR lists startups whose revenue is read from the payment provider's API (Stripe, Lemon Squeezy, Paddle, RevenueCat), not self-reported. Without a key the stage takes a bounded public snapshot (the home page and the first page of each category, about 1,000 top earners; the site's llms.txt asks automated clients not to scrape further), with a free `TRUSTMRR_API_KEY` the full list above a revenue floor. `s0_merge` adds the startups with at least $1,000 of revenue in 30 days to the universe as `proven` (582 on the first run); `s5_deals` matches the startups to niches with the niche regexes and passports show the matched count, MRR sum and median, how many are for sale and the top three. It proves that a niche pays at the indie end; it leans toward AI, SaaS and developer tools and toward top earners, so a zero proves nothing and it never enters the score.

**Regulations (`s0_regulation`, discovery for a human).** A year of US final and proposed rules (Federal Register API) and Russian draft regulations (regulation.gov.ru open-data API, plus each selected draft's passport) is filtered by title against routine notices and ranked by compliance terms, the significant flag and the Russian regulatory-impact degree (`config/regulation.yaml`). An LLM reads the top 300 and says whether each creates a new obligation for small businesses, who must comply, by when, and gives a who x task x product idea. Rules with a deadline create demand before it shows in search, the blind spot of section 10 for young categories. Nothing is scored or written to `niches.yaml`: drafts may never be adopted and the LLM reads summaries, not rule texts, so check the source before a candidate becomes a niche.

**Why:** to start from "products that already earn" rather than from an imagined list of ideas. Games and medicine are excluded at the door.

**Traps:** top-grossing charts over-represent consumer apps, so the universe is skewed toward mature categories with shelves. The coverage stage (S1) reports which universe rows no niche explains, to expose gaps.

### S1 - Niches and coverage

**What it does:** clusters universe entities into niches (rules in section 3), then `s1_coverage` maps universe rows to niches by phrase lists and competitor names and reports what fraction of each source is explained, the most common terms among unexplained rows, and unexplained top-grossing apps by genre. Output: `niches.yaml`, `queries/*.yaml`, `S1-coverage.md`.

**Rules:** at least 3 competitors per niche; queries typed by intent; 6-8 control niches forced in; keyword lists used for coverage must be compound phrases ("shopify analytics"), not generic words ("analytics", "report") - generic words inflate coverage to meaningless levels.

### S2 - Query validation

**Measures:** `ambiguity` (share of off-topic nested phrases) and `platform_share` (share of phrases that name Google, Apple, a voice assistant, ChatGPT, Microsoft, Notion).

**How:** for each anchor, collect nested phrases (Wordstat top requests for Russian, about 10 Google/Yandex autocomplete suggestions) and have them labelled on-topic / off-topic / platform / brand. Autocomplete suggestions are keyless; Wordstat needs a Yandex key and a 100-requests/hour quota.

**Why:** a query that means something else is the commonest source of false signals - a profession that is also the title of a TV series, "translator" inside "English online". A niche with ambiguity above 25 % has its queries fixed or is dropped.

### S3 - Quick filter (search demand)

**Measures:** per niche and market - category demand (sum of monthly volume over `category` queries only; sums never mix intents), `cpc_med` (median CPC over category queries), `comp_idx` (mean Keyword Planner competition index, 0-100, used only as a weak proxy for number of advertisers), brand demand, `brand_share`, `hhi_brand`, `top1_brand_share`, and trend metrics from 48 months of history.

**Sources:** DataForSEO `google_ads/search_volume/live`, which returns volume, CPC, competition index, and monthly history (48 months) for up to 1,000 keywords per call. One call per market (US, worldwide without location, and a Russian-language pool) covers the demand and trend side of every niche at once - about $0.09 per call. Yandex Wordstat `totalCount` is added for the Russian module.

**Trend metrics** (computed on the category-query monthly sum):

| Metric | Definition |
|---|---|
| `yoy` | last 12 months / previous 12 months - 1, on a **robust series** (each month capped at 3x the median of the preceding 12) |
| `yoy_pre` | clean base period: calendar year after / calendar year before the contamination window (2024 / 2023 by default, configurable) |
| `momentum` | last 3 months / same 3 months a year earlier - 1 (robust series) |
| `cagr_3y` | (last 12 / the 12 months three years earlier)^(1/3) - 1 |
| `spike` | max month / median month over the last 24 months > 3 |
| `demand_2023` | monthly average of the clean base year (the last year before contamination); kept as a clean demand level |

**Verdict:** `UP` only if `yoy_pre` and `yoy` are both above +5 %; `DOWN` only if both are below -5 %; otherwise `FLAT`; `NA` without enough history. Requiring two periods to agree is the defence against Keyword Planner contamination (section 6).

**Brand metrics:** `brand_share = brand / (brand + category + problem)`; `hhi_brand = sum(share_i^2)` over brands; `top1_brand_share = max(share_i)`. Brand share is informational: it measures *navigational* demand, not concentration, and fires for most niches including healthy ones. Concentration is held by the top-1 gate.

**Output:** `metrics_quick.csv` with gate flags, and a leaderboard per market. A quick score exists (demand + growth + the brand part of fragmentation, normalised to 0-100) but only orders the shortlist; it is not the final score.

**Shortlisting:** pass = no `G0`, `G1`, `G2` flag (section 7.1); the human checkpoint then edits the list. A two-tier shortlist is used: tier A (passed G0-G2) and tier B (cut only by the top-1 brand gate but with substantial demand and a top-1 share that is not extreme) - because that gate depends on three to five hand-listed brands, tier B is re-tested against an independent concentration signal in S5. Niches with a top-1 brand share above ~80 % are not carried forward. Control niches that S3 has not settled go along as tier C (principle 5): red and platform controls that passed the gates, which the deep stages must still turn red, and every green control, which S6 must confirm. A green control cut by the top-1 gate is re-tested like tier B; a fragmented market outside search then points at the gate, not at the control.

**Demand inside chatbots (experiment `s3_ai_volume`, never scored).** Part of the questions people used to type into a search box now go to ChatGPT, DeepSeek or Alice, and no provider publishes per-query statistics for them. Search volume still ranks niches correctly if the move to chatbots is about the same across niches, because every score is a percentile within the cohort; it is biased only where the move differs. Commercial "AI search volume" products do not measure chatbots directly: DataForSEO models its index from Google People Also Ask, Ahrefs scales Google volume by a platform ratio, Profound and Semrush extrapolate small clickstream panels. The experiment compares the DataForSEO index with Keyword Planner volume under a rule fixed before the first run: the index adds nothing for screening when the niche-level Spearman on category demand is at least 0.8 and at most 10 % of niches move by 25 percentile points or more. The first run (2026-11-21, 1,714 US keywords, 163 niches) gave Spearman 0.83 with 14 % of niches moving, so formally "diverges". The movers come from how the index is built, not from chatbots: word forms collapse (the brand "whering" inherits 28 million questions with "where", "mobility app" probably takes in "mobile app"), and navigational or tool queries that nobody phrases as a question get almost nothing ("uscis case tracker" 60,500 on Google, 96 in the index; "photo math solver" 22,200 against 5). Without those keywords Spearman is 0.84 with 15 % movers, mostly low-volume niches where a percentile reacts to small numbers. The AI-to-Google ratio of category and problem queries did not grow over the 12 months (0.107 to 0.097). Conclusion: the index is a second reading of Google, it never counts toward triangulation, and the pipeline does not use it. The real exposure to chatbots is on the supply side, where a free answer replaces the product; that is measured in S5 (`s5_ai_substitute`) and in the info cohort (`info_ai`).

**Switching intent (`s3_switch_intent`, evidence, never scored).** For every brand query the stage asks Keyword Planner for "<brand> alternative(s)", "alternatives to <brand>", "apps like <brand>" and "cancel <brand>" (Russian pool: "аналог <brand>", "отменить подписку <brand>"; templates in `config/switch_intent.yaml`) with 24 months of history. Per niche: alternative and churn volumes, their ratio to the niche's brand demand (so a big brand does not look unhappy just for being big), the percentile of that ratio within the B2C or B2B cohort, the year-on-year change, and the brand people most want to leave. It sits beside the manual `lock_in` and the S10 switching shares: a high ratio means buyers already shop for a substitute. Keyword Planner answers close variants as one group ("x alternative" and "x alternatives" had identical monthly history for 265 of 273 brands on the first run), so phrases with the same history for the same brand and kind are counted once. A brand that is also a common word draws searches about the word ("paprika alternative" 15,060 a month is the spice; "cancel sling" is Sling TV): brands listed under `homonyms` in `config/switch_intent.yaml`, each with its reason, are left out of the niche's sums, and a brand whose phrases exceed half of its own brand demand is only marked as a suspect for a human, because a narrow brand query makes a real brand look high. Keyword Planner returns nothing below about 10 searches a month, so a missing phrase is "too small", not zero. First run (2026-11-23): the largest shortlisted ratios are tiny Shopify-app volumes; among real volumes, AI video dubbing (580 a month, HeyGen), managed n8n hosting (320, Railway, +111 % year on year) and astrology ("cancel Co-Star" 460, 7.5 % of brand demand).

### S4 - Trend depth

**Google Trends cross-check (anchors).** Independent of Keyword Planner. Each anchor is queried alone for 2021-2024 in the matching geography; the series shape is compared by annual means. Verdict: `UP` if the last year is at least 15 % above two years earlier and the last year-over-year is at least -5 %; `DOWN` if at least 15 % below and last year-over-year at most +5 %; otherwise `FLAT`. A category that did not exist two years earlier but has a mean index of at least 10 in the last year is `UP`. If the anchor's index is below 5, the result is `NA` (unusable) - this is typical for narrow B2B anchors. Data after the contamination window is deliberately not used.

**Why a broad fallback and why brands.** A narrow anchor gives `NA`; a broad "X software" phrase gives a verdict, but a single "X software" series is unreliable (section 6). So the pipeline queries 3-4 **brand anchors** of the category as well (`config/trends_brands.yaml`) and merges with a symmetric rule:

| Case | Result |
|---|---|
| At least 2 brands with a signal (index at least 5) | the majority verdict of brands applies |
| Broad `DOWN`, brands not `DOWN` | `FLAT` |
| Broad `FLAT`/`UP`, brands `DOWN` | one step down |
| Broad `NA` | the brands' verdict |
| Brands `UP` | do not lift a broad verdict to `UP` (growth of the category must be visible in the category itself) |
| Tie | `FLAT` |

The reasoning: people looking for tools search for brand names, not for "X software"; a falling generic phrase with rising brands is a change in query habits, not a shrinking market.

**Russian module:** Wordstat dynamics over 36 months for each Russian anchor, same robust metrics (`yoy`, `yoy_pre`, `momentum`; every month capped at 3x the median of the 12 months before it, in both years: until 2026-11-21 only the last year was capped, which turned flat seasonal series DOWN); `UP`/`DOWN` only when the two year-over-year figures agree; series below 300 searches/month are `NA`; disagreement with the Google-based Russian pool gives `FLAT`.

### S5 - Supply depth

**What it measures:** who the players are, how concentrated the niche is by an *independent* signal, what they charge, and whether deals happen.

| Source | Side | Signals |
|---|---|---|
| iTunes Search API + apps.apple.com pages | B2C | players with at least 1,000 / 10,000 ratings, top-1 / top-3 share and HHI by rating count, apps released in the last 12 / 24 months, free share of the top 20, largest-developer share (clone factories), in-app purchase prices (min monthly / annual / lifetime) |
| Capterra categories and GetApp product cards | B2B | products in the category (`numberOfItems`), reviews per product, top-1 / top-3 / HHI by reviews, entry price, billing period, free trial / free version |
| Shopify App Store subcategories | e-commerce B2B | reviews per app / subcategory total, players with at least 100 reviews, free-plan share |
| Marketplace / portfolio / launch corpora (from S0) | all | `3 x listings with revenue + 2 x bootstrapped-fund portfolio + launches in 12 months + accelerator companies + top-grossing apps` |

**Relevance is the hard part.** Search results include marketplaces, platforms and neighbours. App Store results are candidates if the app ranks in the top 15 of at least one category query. The candidates then pass an LLM product check (`appfit.py`): the model gets the niche (who, task, product) and the apps (name, developer, store genre) and answers per app whether these users would choose it, or weigh it against the niche's products, for the task. Games, apps for the other side of a market and big general apps where the task is a side feature fail. The check was added on 2026-11-21: by search position alone Pandora held 97 % of the ratings of the music-distribution niche, the Chase bank app 94 % of credit-card points, and Instagram led Russian transcription, so the concentration measured the giants, not the niche. Its decisions are the `fit` and `fit_why` columns of `appstore_apps.csv`, and `appstore_review.md` lists the most-rated apps it dropped. Google Play (`s8_gplay_filter`) has the same check since 2026-11-21: its regex and position candidates (name, developer and store description, since Google Play search returns no genre) pass it before the 30-app cap, so a game no longer takes the place of a product; decisions in `gplay_fit.csv`, a wrong "no" is kept through `config/gplay_keep.yaml`. Manual pruning by trackId in `config/appstore_relevance.yaml` (marketplaces, platforms, content media, games, adjacent categories) still applies, and a manual `include` wins over the check. Horizontal products that appear in every software directory category (generic project tools, general CRMs) are excluded from concentration by `config/capterra_generic.yaml` (and `shopify_generic.yaml`).

**Gate S5 - independent fragmentation:** top-1 share by ratings/reviews at most 50 % **and** at least 8 players (B2C: at least 1,000 ratings; B2B: at least 100 reviews, horizontals excluded; Shopify: at least 100 reviews). Niches where the directory category is only a weak proxy for the niche get `NA:proxy` and a manual supply estimate (flagged `S5:manual`, result `PASS*`). Missing data is not a failed gate: when a directory returns no concentration (on 2026-11-21 Capterra answered 45 of 51 category pages with an anti-bot "Security Check" page), the niche falls back to the other directory, or gets `NA:nodata`. Until then a missing share counted as 100 % and turned 16 B2B niches red, two saturated controls among them. GetApp, the source of B2B prices, sits behind the same check: `s5_pricing_b2b` stops at the first block page and writes nothing, so the switching block reads B2B price inputs as unmeasured (neutral 0.5), not as 0 % public prices.

**The "second platform" rule.** One app store is one signal of concentration. If the App Store gate fails on `top1` but, in Google Play US, the leader holds at most 50 % and at least 8 apps have 100,000+ installs, the gate becomes `PASS:android` with flag `S5:android` (mirror thresholds of the iOS gate). The rule only affects the gate; the score is unchanged. It applies to B2C and prosumer niches only (changed 2026-11-22): the first second-pass run with Google Play data turned the control `ctrl-website-builder` ([control red], App Store top-1 GoDaddy 56 %) green through mobile site-builder apps (WordPress 31 %, 11 apps with 100k+ installs). B2B products are bought on the web, and for B2B niches the App Store is only the fallback when Capterra has no data, so a second app store adds no independent signal about their market. The other eight niches that got `PASS:android` in that run are B2C or prosumer, among them the two [control green] niches (transcription, AI song generation) that the App Store alone had wrongly made red. Tightening the install floor to 1M instead did not help: the site builder has 8 apps above 1M installs, while transcription has 6 and would turn red again.

**Why not paid-ads advertiser counts?** The intended fifth point of fragmentation was the number of distinct advertisers in the SERP. The SERP vendor endpoint did not return paid blocks from a datacentre IP, so the point is filled by the percentile of the Keyword Planner competition index (`frag_comp`). It is a weak proxy and is documented as one. Advertisers per niche are planned from the Google Ads Transparency data that DataForSEO resells (`docs/idea-sources.yaml`, `google_ads_transparency`); they will be evidence first and enter the score only by a written change.

**Who owns the search page (`s5_serp`, evidence).** For the anchor and two more category queries of each shortlisted niche: one live Google US top 10 and the DataForSEO Labs keyword difficulty (0-100). Organic results are grouped by `config/serp_domains.yaml`: review directories, app stores and marketplaces, forums and video, media listicles, the niche's own brands (the domain contains a brand name from the queries) and other sites. Flags: `R:serp-leaders` (brands hold at least 2 of the top 3 on average: entry through SEO is hard), `R:serp-listicles` (directories and media hold half of the page: entry goes through listings and affiliate articles), `R:ai-overview` (Google answers at least half of the queries itself, evidence for G3 like the AI substitute probe). It turns step 3 of section 11 ("check that the SERP is not owned by the leaders") into data. One snapshot of a page that changes daily. Comparison pages of any site (titles such as "best ... apps", "8 top picks") count as media listicles, because affiliate sites now hold several positions of a page. Since 2026-11 the vendor returns many organic results as google.com redirects; the real domain is read from the result's breadcrumb. First run (2026-11-23, 74 niches, 1,893 organic results): an AI Overview on 97 % of the queries, so `R:ai-overview` fired for 73 niches and does not separate them (read it as "Google answers this kind of query", true of almost all); `R:serp-listicles` for 21 niches; `R:serp-leaders` for none, because app stores, forums and Facebook groups fill most of the pages; keyword difficulty from 0-17 (POD/KDP tools, feedback boards, marketplace analytics, law-firm intake, ASO tools) to 69-82 (eSIM, star maps, flight deals).

**AI substitute (`s5_ai_substitute`), evidence for G3.** Platform risk includes the free general chatbot: a product whose job is to produce a text, a plan, a solution or an identification competes with a free answer. Per shortlisted niche the LLM writes three messages a buyer from the niche's audience would type into a free chatbot (written as the buyer, because the niche fields describe a market: "I'm women 20-45 interested in esoterica, I need natal chart, daily forecasts, AI chat" reads as a founder's question and drew a build plan), answers each as a free chatbot, and a separate judge call rates each answer: `covers` 2 = the chat delivers the outcome the product sells, 1 = the chat does a part of the job well enough that some of the audience would use it instead of paying, but the core of what most people pay for still needs a product (records over time, automation and reminders, integrations and payments, several users, live data, device features, compliance), 0 = the chat only advises, or what it can do is not what people pay for (recommending vendors, generic tips and templates nobody would use instead of the product are advice). The first version of level 1 accepted any plan or template the chat could write and put 44 of 74 niches there; tying it to "some buyers would not pay" matches the manual meaning of platform risk 1 ("partially covered"). Both the chatbot and the judge are told what free chatbots can do today (photos, files, voice, image generation and editing, web, chat history) and what they cannot (background work, reminders, shared records, payments, integrations, audio and video), because the API model is text-only: without this it answered "I cannot see your photo" for a photographed math problem and "I cannot edit photos" for a haircut try-on, both jobs that free chatbots do. The judge lists what the chat can and cannot do before it rates, and ignores conveniences every app has. The niche gets the median of the three ratings; `votes` keeps them all. Why three requests: single ratings of borderline niches flipped between 1 and 2 with the wording of one request; the request that asks for an app recommendation pulls toward 0, the one that asks the chat to do the job pulls toward 2. The probe never sets `platform_risk`. It lists, for a human to read the answers, the niches where it rates the chatbot above the manual call: covers 2 against a lower call (review G3), covers 1 against 0 (consider P1). The comparison runs one way: the probe tests general chatbots only, so it cannot refute a platform risk that comes from an OS feature or a vendor's own service. The same model writes, answers and judges, which is a known bias of the method. First run (2026-11-21, 74 shortlisted niches, DeepSeek): covers 2 - 1 (homework solvers, 2/2/2, matching the manual veto), 1 - 48, 0 - 25; the probe agrees with the manual call on 30 niches, is lower on 30 (expected: the manual call also counts OS features and vendors' own services) and higher on 14, all of them covers 1 against 0. A haircut try-on stayed at 1 against a manual 2: the judge kept doubting that a chatbot edits a selfie despite the capability list, a limit of the model to keep in mind for image jobs.

**More app ecosystems (`s5_ecosystems`, evidence).** Supply in the Chrome Web Store (weekly users, read through the search page's own data call, 150 results a page) and the Atlassian Marketplace (cloud installs, open REST API), with the same concentration metrics as the Shopify measurement: relevant products, players above user thresholds, top-1 and top-3 shares, HHI. Only the niches whose buyer really installs from those stores are listed, by hand, in `config/ecosystems_map.yaml` (17 on the first run), each with a relevance regex, because store search matches any word. Store users are installs, not buyers, and an extension is often a free companion of a paid web product.

**Free substitutes (`s5_oss`, evidence for pricing power).** GitHub repository search with the niche's English category phrases (exact phrase in name, description or topics; a one-word phrase must be in the name or topics; per-niche overrides and exclusions in `config/oss.yaml`). The flag `O:oss-substitute` marks a niche with a maintained repository of 1,000 or more stars (not archived, pushed within 12 months). A free self-hosted alternative caps willingness to pay for technical buyers far more than for consumers. Stars measure developer attention and can be bought (the forks column helps), and phrase search misses projects worded differently.

**Pricing / switching:** `self_serve` (1.0 for B2C; share of products with a public price for B2B), `monthly` (share of plans below $100/month for B2B; share of apps with a monthly subscription for B2C), `import_from` (set to a neutral 0.5: not measured), `lock_in` (manual 0-2: 0 easy export, 2 annual contracts plus accumulated data). Shopify apps are given `self_serve = monthly = 1` (one-click install, public monthly prices).

### S6 - Score, gates, passports

Described in sections 7 and 8. Output: `score_final.csv`, `path_to_goal.csv`, per-niche passports (`reports/passports/<id>.md`) and a summary.

### S7 - Report

A static HTML leaderboard: all scored niches with filters, sorting, expandable passports, and the path-to-goal columns.

### S8 - Demand outside search

Stage S8 adds signals that never change the score (the weights are pre-registered) but go to passports and reports as confirmation or contradiction.

| Source | What it gives | Caveat |
|---|---|---|
| YouTube search (Google Trends `gprop=youtube`) | Level relative to a reference topic queried in the same request (Trends indices are only relative within one query), plus the 2022-2024 trend | People search YouTube for a *topic*, not "X app": phrases are topical (`config/youtube_topics.yaml`). B2B topics sit near zero, which is itself a result |
| Subreddit sizes | Comparative community size | A static snapshot, not growth |
| App Store rating velocity | Ratings per month since release; share of velocity coming from apps up to 24 months old ("pull of newcomers") | Computed from one point in time; S9 gives a direct measurement |
| Google Play search + details | Installs (`maxInstalls`, global, not per country), leader share, players with 100k+ / 1M+ installs, new apps, share paid | Storefront is the market in which the app was found, not where installs happened. Throttled, about 1 card/s |
| Job-posting counts (Russian module) | Vacancies mentioning a software brand = adoption proxy | Needs Russian egress; HTML search page |
| Hacker News Show HN / Ask HN (Algolia API) | Launches and "is there a tool for X" questions whose titles match the niche, last 12 months vs the 12 before, with a trend | Developer audience: B2C verticals are barely present, so a low count is NA. Titles only: news stories and post bodies mention a niche's words in passing |
| HN "Who is hiring?" threads | Startup job postings that match the niche: funded teams working on the task now | Free text matched by the niche regexes; a company may only *use* such a tool, so read the examples |
| Freelance exchanges (`s8_freelance`: Kwork buyer requests, FL.ru projects) | Posts where someone pays a person to build software for the niche's task (`build`) or to do the task by hand (`service`): paid demand with a budget. The public lists are read within robots.txt and every post is kept in a history, so the signal grows with the number of runs; keyword candidates are labelled by the LLM and only build and service count | A snapshot of open posts (Kwork requests live ~3 days); small budgets; zero is normal for consumer apps; without the LLM labels the counts are unverified keyword matches |
| Business registers (`s8_who_counts`, `ru_msp_counts`) | How many businesses of the niche's industry exist: US establishments with employees (Census County Business Patterns, latest year and the year before), the share under 20 employees, firms without employees (Nonemployer Statistics); Russian small and medium businesses by main OKVED code with the 12-month change (FNS register dump). Codes per niche are hand-kept in `config/who_counts.yaml`, only for niches whose buyers are one industry | A code can be wider or narrower than the niche (the config note says ceiling or floor); CBP counts locations, not firms; the Russian register has no self-employed (NPD), non-profits or religious organisations |

Why outside search? B2B demand barely exists in search ("meeting summary" can have two impressions a month while the category earns millions), and consumer demand is partly expressed in app stores.

### S9 - Supply over time

- **Snapshots.** `freeze` stores the relevant apps (App Store: `relevant = 1`, not `na`; Google Play: not excluded) under `data/snapshots/<date>/`; `refresh` fetches fresh rating counts later (iTunes lookup, 150 ids per call, keyless); a Google Play refresh stores fresh cards in a separate cache. `diff` computes per-app and per-niche growth: share of growth from apps up to 24 months old, share of the leader in growth. This replaces S8's computed "velocity" with a direct measurement and answers "who is growing now", which no demand source can.
- **Entrant survival** (`entrant_survival.csv`, from data already in the App Store set). Cohort = relevant US apps released 12-24 months ago. Alive = updated within 180 days; traction = at least 1,000 ratings. Flags when the cohort has at least 8 apps: `E:churn` (alive below 50 %) and `E:traction` (traction at least 30 %). The flags do not enter the score. They separate a healthy open market from a **clone factory**: high fragmentation plus many new releases and a small leader looks identical in the score, but a factory shows a cohort that stops updating and never earns ratings.
- **Site history** (`s9_wayback`, evidence). The websites of the top 10 App Store apps per niche (the iTunes `sellerUrl` already in the S5 cache) go through the Wayback Machine CDX API: first capture (age), last capture with HTTP 200, months with captures in the last 24. Per niche: median age of the top-5 apps' sites (how entrenched the leaders are), share first seen within 3 years, share without a live capture in 12 months. It needs no second snapshot. A domain's history can predate the current business, and rarely crawled small sites look quiet.

### S10 - Buyer voice (Reddit; Russian app reviews)

Described in section 9.

### Info - Short-video topics (micro info products)

A separate cohort for a different business model: a micro info product (a guide, checklist, template or mini course, a few hundred to a few thousand roubles) sold through short video (Shorts, Reels, TikTok) that funnels viewers into a Telegram channel. Search demand is the wrong signal here: a viewer of short video does not search for a solution, the content finds them. The cohort lives in `config/info_topics.yaml` (topic = who x task x product plus 1-3 YouTube search phrases), not in `niches.yaml`, and has its own score (7.6); it never mixes with the software cohorts.

- `info_discover` builds the topic universe from demand data instead of guesses. It takes Wordstat top requests (2,000 phrases each) for intent words that name no topic ("online courses", "learning", "how", "what to do if", "how to get rid of"... in `config/info_discover.yaml`), lets an LLM sort phrases above a volume threshold into learn / fix / ready-made material / other and name the subject, and ranks subjects by demand: the sum of their phrases without nested ones, since broad match already counts "english courses online" inside "english courses". Other (navigation, currency rates, spelling, device troubleshooting, one-off household fixes, medical symptoms, games and series, goods, local services) is dropped. With `--write-topics N` the top N subjects become the topics of the cohort; YouTube then measures them as a second, independent source. Why: the first 30 topics were the researcher's areas expanded by hand, so their ranking said which of our guesses was best, not what people want most. Traps of the stems: Wordstat lemmatizes "courses" to "course" and the top becomes currency rates (hence "online courses"); "guide" is mostly game guides and "marathon" anime marathons, which the sorting removes. With `--dynamics N` the head phrase of each of the top N subjects gets 36 months of Wordstat dynamics, so "most demanded" is read together with "growing now": yoy = last 12 months against the previous 12, both capped at 3x the 24-month median (a symmetric cap: capping only the last year, as S4 did until 2026-11-21, turns a stable topic with yearly peaks above 3x the median into a false DOWN), and momentum = last 3 months against the same months a year earlier; UP / DOWN at +-15 %.
- `info_suggest` expands broad seed areas through YouTube autocomplete (`seed`, `seed a`, `seed b`, ...) into phrases people actually type into YouTube. The output is a human checkpoint: the researcher groups phrases into topics.
- `info_youtube` takes, per phrase, the 100 most viewed videos under 4 minutes of the last 12 months (two search pages, YouTube Data API), keeps Shorts (up to 3 minutes), Cyrillic titles for the Russian market and, optionally, videos matching the topic's `must` regex, lets an LLM label each kept video as teaching, entertainment or off topic, and measures the teaching videos of the top of the topic's attention pool: median and 90th-percentile views, the share of videos that outgrew their channel (views >= 10x subscribers), the share made by channels under 10,000 subscribers, how many of the top videos the three most frequent channels made, the share of channels that point to Telegram, the share of videos that name an offer (guide, checklist, course...), and how much of the top is recent.
- `info_telegram` measures the end of the funnel without a paid API: the public page t.me/<name> shows a channel's subscriber count, a group's member count and its description. `info_youtube` keeps, per video, the Telegram links of the video and channel descriptions (t.me links and "@name" right after a Telegram word, a third of the mentions) and whether they link a payment, paid-content or sales-funnel platform (GetCourse, Boosty, Tribute, Prodamus, BotHelp, SaleBot...). Per topic, over the YouTube channels of its teaching videos: how many link a Telegram channel or group that shows a count, the median, 90th percentile and largest subscriber count (one per author: its largest link), how many have at least 10,000, and the share of authors who link a payment or funnel platform on YouTube or in the Telegram description. A link named by two or more different YouTube authors is a sponsor, not a funnel, and is left out (first run: a search engine's 590k channel from paid integrations). The counts are a floor: the links section of a YouTube channel ("link in profile") is not in the API, and many authors keep their Telegram only there. First run (2026-11-21, 61 topics): 944 YouTube channels with teaching videos, 169 (18 %) with a measurable Telegram funnel, 8 topics with none; payment or funnel links in 24 topics, at most a fifth of the authors (the one exception is a topic with a single teaching author). No effect on the score.
- `info_ai` asks whether a free chatbot gives the product away: the same probe as `s5_ai_substitute` (three buyer requests in the cohort language, answer, judge, median), with a rubric for info products. 2 = the answer with a follow-up gives the knowledge, steps, checklist or template the product sells; 1 = the chat gives much of the content, but the product rests on what a chat lacks (video demonstration of a physical technique, a tested sequence from a trusted author, designed or printable materials, accountability, a community); 0 = the text answer barely helps. First run (2026-11-21, 60 topics): 16 rated 2 (languages, investing, financial literacy, neural networks, exam preparation, accounting, law), 44 rated 1 (knitting, drawing, crafts, driving: physical technique needs video), none 0; two of the three green topics, neural networks and English, carry the flag.
- `info_paid` checks the paid side, which views cannot show: per topic, relevant paid Stepik courses (learners, price) and relevant paid non-fiction Litres ebooks with at least 5 ratings (a rating is a sales proxy). Store searches are loose, so titles must match the topic's `must` (overridable per topic in `config/info_paid.yaml`), and Litres books whose main genre is fiction are dropped; on the first run, 73 of the books matched under "law" were romance fantasy. It raises `I:paid-market` at 5,000 or more paid Stepik learners or 3,000 or more Litres ratings, and `I:no-paid` when neither store shows a sale. The thresholds are a draft set after the first run to mark about the top third, and the flags never change the score. Stepik is mostly IT and school courses, so an empty Stepik means little for craft topics, where Litres carries the signal (about 150 sold knitting books per topic). First run (2026-11-21, 61 topics): 23 `I:paid-market`, 1 `I:no-paid`.
- `info_score` scores, gates and reports (`reports/info.md`, with example videos per topic, the AI rating and the paid market column).

Why the most viewed and not YouTube's relevance order: on test topics the relevance order returned a median of 1-2k views (fresh videos nobody has watched yet) and 43 of 49 videos from the last half-year, so the recent/older split measured YouTube's freshness boost rather than the topic. The most viewed top separated topics clearly: 28 of 49 top videos from small channels on one topic, 2 of 47 on another. Its cost is drift: a broad phrase pulls in viral videos that only mention its words, which `must` and `must_not` filter (lullabies under "fall asleep fast", funny listings under "sales on Avito", air-raid alerts under "anxiety").

Why one short subject phrase per topic: phrase length decided the result more than the topic did. On the first 30-topic run, phrases with a how-to tail ("burnout at work what to do") gave median views of 1-2k, subject phrases 30-180k. Short-video audiences gather around a subject, so each topic is measured by the subject as people name it, in 1-3 words; the task and the product stay in `who`/`task`/`product`. `nf validate` warns about phrases longer than four words.

Why a `global` status: for some subjects the most viewed top of a short Russian phrase is English-language world hits ("guitar": 47 of 50, "dance": 31 of 50), and the language filter leaves one to three videos. That says the phrase cannot measure the Russian top, not that the topic is thin, so such a topic (fewer kept videos than the I0 gate and at least half of the top dropped by language) is reported as `global` and not scored; a Russian-specific phrase fixes it.

Why concentration is counted in videos, not views: in a top-50 by views a single viral video takes about half of all views (0.47-0.51 on test topics), so a views share says only whether there was a mega-hit. The share of top videos made by three channels separated the same topics (0.14-0.19 vs 0.87).

Why teaching videos only: on the first full run (2026-11-21, 61 topics) the most viewed top of broad subjects was mostly comedy and curiosities that only use the subject's words: "rare photos that will amaze you" filled 30 of 35 photography Shorts, sketches and Minecraft videos 27 of 36 under neural networks, a guessing game and nostalgia most of the exam-preparation top. Attention then measured how easy a subject is to joke about, and craft subjects, whose top is almost all practical, lost to it. A seller of a micro product makes teaching content, so its reach is the question. The LLM sees each video's title, channel and the start of its description and labels it T (gives the viewer something usable: an instruction, tips, an explanation, a process shown so it can be repeated), E (about the subject but made to amuse or to show: sketches, pranks, fails, vlogs, reactions, news, a result without the method) or O (another meaning of the word, a passing mention); an unlabelled video counts as T. Teaching videos were half of the top in the median topic (3-100 %), so the sample grew from one search page to two: from one page 25 of 61 topics kept fewer than 10. Weights and gates did not change; `teach_share` is reported, not scored.

Not measured: Reels and TikTok (no open API; TikTok is frozen in Russia), and views are not buyers. Shorts stand in for short video in general. Telegram beyond its public pages (channel growth, post views, mentions over time, paid posts marked with erid) needs a paid TGStat API plan, which was declined.

---

## 6. Known traps and how they are caught

| Trap | Example | Detector |
|---|---|---|
| Homonym / other meaning | A profession that is also a TV series | `ambiguity` from nested phrases (S2); manual review of the top-50 nested phrases before accepting any "growing" cluster |
| One-off spike | A platform launches a free feature; searches jump and fall back | `spike` (max / median over 24 months > 3); robust series caps each month at 3x the trailing median |
| Calendar artefact | Phrases containing the year ("horoscope 2026", "tax deduction 2026") show +10,000 % | Year-bearing phrases are rejected in review |
| "Ask an AI through search" | "come up with a name", imperative queries addressed to an assistant | `problem` intent excluded from CPC; `platform_share` |
| Brand is the category | A presentation generator that owns about half of brand queries | `top1_brand_share` gate G2; Cyrillic spellings of brands must be included in `brand` queries |
| Info queries | Benchmarks, "what is" | `info` intent excluded from all sums |
| B2B does not live in search | "meeting summary" has almost no searches although the category sells | For B2B, demand is read from directory reviews, job postings, tenders; search is used for trend only |
| Keyword Planner history contamination | see below | `yoy_pre` agreement, robust series, `Q:` flags, `demand_2023`, Trends brand anchors |
| Google Trends after the contamination window | A phrase "X app" jumping 0.1 -> 30 without confirmation in Keyword Planner | Trends is used only up to the clean window; `contaminated` flag |
| Directory category weaker than niche | Telephony category for an AI receptionist | `NA:proxy` plus manual estimate, flagged |
| Generic words in coverage lists | "analytics" matched everything | compound phrases only |

### Keyword Planner contamination

Keyword Planner's *history* is not a stable series for tool-type queries. Two distortions are built into the defaults:

- **The 2024 "X software" hump.** Many "X software" queries are inflated about 3-8x in 2024 and then fall back. A naive last-12-vs-previous-12 growth can read as steep decline or steep growth depending on where the window cuts the hump.
- **The 2025-26 "X app" step.** From 2025 many "X app" and broad tool queries step up about 2-5x with no support from flat anchors or from falling informational queries; it appears across several geographies, including English queries in non-English countries rising from zero. The cause is unknown (measurement change, automated traffic, agents); the consequence for validation is single: year-over-year growth of tool queries in the contaminated window should not be believed.

The pipeline responds with:

1. `UP`/`DOWN` only when `yoy_pre` (the clean year over the year before) and `yoy` (last 12 vs previous 12) agree, otherwise `FLAT`.
2. A robust series for `yoy` and `momentum`.
3. Flags, none of which is a hard gate: `Q:spike`; `Q:step2025` (monthly mean of a recent 12-month window inside the contaminated period is at least `step_ratio` = 2.5x the monthly mean of the hump year); `Q:hump2024` (the contaminated year at least `hump_ratio` = 2x the clean year **and** the latest year below `hump_drop` = 0.6x the contaminated year).
4. `demand_2023` - the clean base-year monthly level.
5. In the score (S6): when growth versus the clean base year is at least 3x (or a `Q:step`/`Q:hump` flag is set) **and** Trends is `FLAT` or `DOWN`, the demand percentile uses `demand_2023` instead of the current volume, with flag `D:2023-base`. If Trends confirms growth (`UP`) or has no signal (`NA`), current volume is kept. The affected years (here 2023 as the clean base year, 2024 hump, 2025 step) are configuration values, not code.
6. Growth on the shortlist is triangulated outside Google (Trends, brand anchors, Wordstat for the Russian module, app-store cohorts).

### Why Google Trends brand anchors

A single "X software" Trends series can flip a verdict. A category whose generic phrase peaked in one year looked flat or falling, while three of its leading brands were consistently rising. Searching for a *product category* by its generic name is itself a declining habit - buyers search for names. Brand anchors answer "is interest in the products of this category growing?", which is what the verdict is for. They are used symmetrically (they can also demote a generic `FLAT`), but they never lift a niche to `UP` on their own.

### Why Trends stops at the clean window

Trends data after the contamination window shows synchronous multi-fold rises across dozens of tool queries while informational queries fall. For validation the series is trusted only up to the clean window; later data can describe relative scale inside one batch only.

---

## 7. Gates and the score

### 7.1 Quick-filter gates (S3)

| Gate | Condition to pass | Notes |
|---|---|---|
| G0 data | at least 3 category queries with volume > 0 (`min_cat_nonzero`); ambiguity <= 25 % | otherwise fix queries first. A niche with a live category but no Google volume can be measured by stores instead |
| G1 trend | verdict is not `DOWN` | flag `Q:spike` is shown separately (an unspiked demand still passes) |
| G2 monopolist | `top1_brand_share` <= 0.50 (only evaluated with at least 2 brands) | calibration: a niche where one brand holds ~53 % of brand searches fails |
| G3 platform | no free native feature closes the task (manual `platform_risk`; value 2 = veto, 1 = flag `P1:platform-partial`) | `platform_share` of nested queries <= 20 % is the S2 pre-screen; `s5_ai_substitute` checks the free chatbot and flags disagreements with the manual call |
| G4 expertise | `expertise_flag` = 0 | medical, licensed legal, regulated finance. A veto, not part of any score |
| G5 feasibility | at least 2 of 4 proxies (section 7.4) | applied at S6 only |
| S5 supply | independent fragmentation test (section 5/S5), or `PASS:android`, or `PASS*` with manual estimate; `S5:unmeasured` is a failing flag | applied at S6 |

Informational flags that do not block: `I:brand_share` (brand share above 0.7 - it fires in most niches because it measures navigational demand), `Q:*` flags, `D:2023-base`, `S5:android`, `S5:manual`, `E:churn`, `E:traction`.

A niche failing any gate is **red**. A niche passing all gates is green or yellow: the verdict is a manual judgement recorded in the overrides file, with the score as support; the repo's default is a score of at least `verdict.green_min_score` (70) when no manual verdict is set.

### 7.2 Final score (0-100)

The score is computed on the shortlist cohort. **Percentiles are computed within segment** - B2C + prosumer on one side, B2B on the other - not over the whole cohort: volumes, number of players and top-grossing signal are not comparable between segments by construction (consumer query volumes are about ten times larger; top-grossing charts exist only for consumer apps). Computing percentiles over the pooled cohort made the median B2C score about 18 points higher than B2B - a property of the formula, not of the markets.

`pct(x)` below means the share of the segment cohort whose value is <= x (0.5 when the value is missing).

| Block | Weight | Components |
|---|---|---|
| Demand | 30 | `20 x pct(log10(demand_eff + 1))` + `10 x CPC-band factor` |
| Growth | 20 | `10 x pct(yoy)` + `5 x pct(momentum)` + `5 x pct(cagr_3y)` |
| Fragmentation | 25 | `10 x (1 - hhi_brand)` + `5 x pct(competition_index)` + `5 x pct(players)` + `5 x (1 - top3_share)` |
| Deals | 15 | `15 x pct(2 x fund_portfolio + launches_12m + accelerator + topgrossing_us)` |
| Switching | 10 | `4 x self_serve` + `3 x monthly` + `1 x import_from` (neutral 0.5) + `2 x (2 - lock_in) / 2` |

**Deals change, 2026-11-20.** The deals block had a `3 x marketplace_with_revenue` term fed by Flippa SaaS listings with revenue. Flippa now answers automated clients with a Cloudflare challenge (HTTP 403 since 2026-11-17) and has no API. The only open replacement, Empire Flippers, has 79 software listings among 2,871 over 2014-2026; matched by keywords they touch 9 of 98 niches, and matching all of its listings counts Amazon sellers as players in seller-tool niches. The term was dropped rather than refilled with noise; Empire Flippers is shown in passports. For runs where Flippa was already empty the deals points do not change (a term that is zero for every niche does not move a percentile); deals points from runs with Flippa data are not comparable with later runs.

`demand_eff` is `demand_us` or, when contamination is detected, `demand_2023` (section 6). When the supply proxy is `NA`/`NA:proxy`, the `players` and `top3` points are replaced with neutral half-credit (2.5 + 2.5). A niche with a manual estimate (`supply_manual`) is flagged `S5:manual`; without one it fails `S5:unmeasured` and gets no `S5:manual` flag (until 2026-11-21 the flag was set on every unmeasured niche, so the red ones showed "manual estimate" in the passport summary and the leaderboard).

**CPC band** (`cpc_band` in `score.yaml`, USD): B2C/prosumer 0.5-8.0; B2B 1.0-1000 (no upper penalty); Russian-market pool 0.15-3.5. Inside the band: factor 1.0; below it: `cpc_below` = 0.3 (not monetisable); above it: `cpc_above` = 0.6 (enterprise or regulated). A B2B niche with a $40-100 CPC is exactly where customers pay, so the upper penalty is disabled for B2B.

**Trend multiplier:**

```
base  = demand + growth + fragmentation + deals + switching
score = base x (1 + adj(trend_kp) + adj(trend_gt))     adj: UP = +0.05, DOWN = -0.05, else 0
```

`trend_kp` is the Keyword Planner verdict (S3), `trend_gt` the Trends verdict (S4, with brand merge).

All weights are the pre-registered defaults. The tool intentionally contains no machine learning: percentiles and weights can be checked by hand.

### 7.3 Why switching is not simply "good"

Low lock-in makes it easy to enter and equally easy for customers to leave. The switching block rewards easy entry; the path-to-goal layer (next section) uses the ticket tier as a retention proxy so the two halves of the argument are both represented.

### 7.4 Feasibility (0-4) for a small team

1. `indie_exists` - a competitor with a team of at most 3 and revenue evidence.
2. `stack_commodity` - no hardware, no two-sided marketplace, no proprietary data; buildable on APIs, LLMs, the web.
3. `no_regulated_data` - no special-category medical, financial or personal data.
4. `self_serve_motion` - at least 50 % of competitors sell without "contact sales".

Passing needs at least 2 of 4. Feasibility is a manual input in the overrides file.

### 7.5 Russian module

The Russian-language branch is scored separately (dollars and roubles of CPC are not comparable, and Wordstat volumes use broad match): Russian demand = `max(anchor, max category phrase) + sum(brand volumes)`; growth from 36-month Wordstat dynamics (`yoy > +15 %` up, `< -15 %` down); concentration from the Russian App Store (manually cleaned) and Yandex brand shares. The B2B sub-module (software registry, public procurement, marketplace of a dominant SMB platform, job postings, Wordstat) uses its own pre-registered score: demand 35, growth 20, fragmentation 25, money 20, with a rule-based verdict (red when the top brand holds more than 70 % of brand searches at a total of at least 5,000; yellow at 50-70 % or below the cohort median; otherwise green). Its measurement traps (full-text search catching attachments; registry search by name missing brand-named products; fuzzy marketplace search) are listed in the module's `config/ru_b2b_traps.yaml`.

Two evidence columns sit beside that score and never change it. **Vendor income** (`ru_vendor_revenue`): the right holders the software register lists for a niche are matched by normalised legal name to the FNS open dataset of income and expenses from financial statements; the report shows matched vendors, total and median income, vendors with 100 M RUB or more, the largest vendor's share and, once an earlier release is in the cache, the income growth of vendors matched in both years. Names shared by several companies are left out as ambiguous, entrepreneurs file no statements, and groups with more than 20 bn RUB of income are left out of the sums as diversified. The interactive statements site (bo.nalog.ru) gives scripts only an application shell and is not used. **Russian SMB marketplaces** (`ru_ecosystems`): apps per niche in the MoySklad catalogue (all 589 apps, developers, paid share) and the public amoCRM widget showcase, next to Bitrix24 Market; no installs are published, so concentration is by developer. YCLIENTS is not readable without a partner token (robots.txt disallows its API).

### 7.6 Info cohort score (draft)

Weights in `config/score_info.yaml`; `status: draft` until the researcher fixes them, and the report says so. Percentiles are **mid-rank** within the topics of the run (share below plus half of the ties): shares are often 0 for many topics, and with "share <= v" six zero topics out of ten would each get 0.6 for having nothing.

| Component | Points | Metric |
|---|---|---|
| Attention | 20 + 10 | percentile of median views of the top Shorts; percentile of 90th-percentile views |
| Newcomers | 15 + 10 | percentile of the breakout share (views >= 10x subscribers, >= 10k views); percentile of the share of top videos from channels under 10k subscribers |
| Monetization | 15 + 10 | percentile of the share of channels pointing to Telegram; percentile of the share of videos naming an offer |
| Spread | 10 | 10 x (1 - share of top videos made by the three most frequent channels), absolute |
| Trend | 10 | percentile of (recent half + 1) / (older half + 1) of the top videos |

Gates (red): I0 fewer than 10 teaching Shorts in the window after the filters (too thin to measure; 15 before `must` stopped counting hashtags, which cut kept Shorts by 20-40 %); I1 median views below 1,000 (nobody watches). Flags without effect: `I:top3` (three channels made at least 60 % of the top), `I:fading` (recent half below half of the older one), `I:no-tg`, `I:ai-answers` (`info_ai` rates the free chatbot answer at `flags.ai_answers`, 2 by default: the product has to offer what the chat lacks; added 2026-11-21 after the weights were fixed, which is allowed because it changes neither the score nor the verdict). Verdict: red on a failed gate, green at `verdict.green_min_score` (70), yellow otherwise.

Newcomers and monetization carry half of the score on purpose: for a beginner blogger the question is not how big a topic is but whether a channel with no audience gets views in it and whether its audience is already being sold to. The gates are deliberately lenient; the draft is meant to be fixed after the first look at real distributions and before the first ranking is read as a decision.

---

## 8. Path to goal (the ceiling layer)

The score answers "is this a market a small team can enter?". It does not answer "can this become a business that meets my income goal?". The second layer is computed on top of the score and does not change it. It is stage `s6_ceiling`.

### 8.1 From income goal to required revenue

```
required revenue / month = net income target / net margin           (default margin 0.40)
required ARR             = 12 x revenue / month
```

The goal (`nf.yaml: goal`) is a net monthly profit range, a currency and a conversion rate to USD. Example, purely illustrative: a target of $10,000/month net at a 40 % margin needs $25,000/month revenue, or $300,000 ARR.

### 8.2 Net revenue per payer (ARPU)

- **B2C:** `ARPU = median monthly price x annual_discount (0.70) x (1 - store_fee (0.20))`. The discount converts a monthly list price to an average that accounts for annual plans (an annual plan is about seven monthly payments); the fee is a blend of 15 % and 30 % store commissions.
- **B2B:** `ARPU = median entry price (GetApp) x (1 - payment_fee (0.06))`.

Price falls back to the niche's `product` field, then to a default ($8 B2C, $50 B2B) if no price was measured; prices quoted per seat or per screen are flagged because ARPU is then understated.

### 8.3 Payers needed vs payers in the niche

```
payers needed (low / high target) = required revenue / ARPU
```

Niche size in paying customers is estimated from the proxy that exists:

| Segment | Proxy | Defaults |
|---|---|---|
| B2C | `ratings/month (App Store) x installs_per_rating_ios x android_multiplier x install_to_paid x paid_lifetime_months` | 50 x 2.0 x 3 % x 8 months |
| B2B (directory) | `directory reviews x customers_per_review` | 30 customers per review (Shopify apps: 15) |
| B2B, no directory category | `monthly category searches x 12 x search_to_customer` | 2 % (flagged "coarsest proxy") |
| Any, manual | `size_override` with `size_note` in `config/overrides.yaml` | flagged as manual |

Every multiplier is an order-of-magnitude estimate; read all shares as plus/minus a factor of two. Installs per rating and customers per review are the least certain inputs.

**Cross-check against the registers (passports, not the grade).** For a niche whose buyers are one industry (`config/who_counts.yaml`), the passport divides the payers needed for the low and the high goal by the number of US establishments in that industry (s8_who_counts). That is the penetration of the whole industry the goal requires, a number that does not depend on any multiplier above. A proxy that estimates more paying customers than there are businesses, or a goal that needs a double-digit share of every business in the country, is visible at once. The grade itself still uses the proxy; replacing it would be a written change of section 8.

### 8.4 Required share and position

```
share = payers needed / payers in niche
```

| Share needed | Position you must reach |
|---|---|
| > 20 % | **leader** |
| 8 % - 20 % | top 3 |
| 2 % - 8 % | top 10 |
| <= 2 % | one of many (the goal is reachable without winning the niche; the question is only acquisition cost) |

### 8.5 Ticket tier, founder fit and grades

- **Ticket tier** by the median monthly price: `<50`, `50-250`, `>250` per month. Published retention benchmarks show a much lower gross retention for small tickets than for large ones, so the tier is a retention proxy.
- **Founder fit** 0-3: a manual field per niche with a written reason. 0 = outside competence (reselling, licences, hardware: the path to the goal is not through a product); the default is `default_fit` in `nf.yaml`.
- **Grades** (pre-registered):

| Grade | Condition |
|---|---|
| **A** | share for the lower target <= 8 %, ticket tier 50-250 or >250, fit >= 2 |
| **B** | share <= 20 % and (ticket tier >= $50 or fit >= 2) |
| **B-** | share <= 20 %, but ticket < $50 and fit < 2 |
| **C** | share > 20 % (needs to be the leader) or fit = 0 |
| `?` / `-` | size unknown / niche explicitly excluded |

(A niche that clears `a_max_share` but fails the ticket or fit condition falls through to B or B-.) Typical outcome of the grading: consumer apps priced $5-15/month land in B- (reaching the goal means being a top-3 to top-10 app in a mid-size niche, which is a race for acquisition cost, not for product), while grade A is dominated by B2B niches at $50-250/month that need a few hundred to a few thousand customers and where being "one of many" is enough.

The tool also carries an access flag (`ru_access`-style: can the revenue be collected without a foreign legal structure). It is not part of the grade and is meaningful only for users in jurisdictions where payment access is a constraint.

---

## 9. Buyer voice rules

S10 listens to what buyers say about existing products, at scale, using a public Reddit archive (Arctic Shift mirror) because the official Reddit API requires approval for new applications.

**Collection.** Each niche maps to native subreddits and larger general subreddits (`config/reddit_terms.yaml`). The archive's full-text search and aggregates time out on medium and large subreddits (HTTP 422), while date-ordered listing is fast, so subreddits are exported by date listing and terms are matched locally. Native subreddits (up to ~70,000 posts) are taken whole for the recent years plus the last 12 months of comments; larger ones are limited to a capped number of pages of matched posts plus the comment threads under them (threads under "which app do you use?" are the densest buyer voice).

**Matching.** Brands are matched at word boundaries and not after `/` (otherwise "liftin" matches "lifting" and "r/loseit" counts as an app).

**LLM classification.** A sample per niche, tiered: (1) matched niche terms **and** an intent marker (question, "looking for", "alternative", "switched", price), (2) matched terms, (3) marker only, (4) random. Without tiers, about three quarters of documents turn out to be not about software. Each item gets an intent (including `off_topic`), pains and themes; shares are computed over software-related documents only. A niche needs at least 300 documents and at least 60 software-related ones, otherwise it is "quiet" and Reddit is not informative.

**Verdict rule** (not a score; `reddit_verdict()`):

| Verdict | Condition |
|---|---|
| Satisfied | praise >= 25 % and greater than the share of "which one should I use" |
| **Seeking** (green) | dissatisfaction = complaints + switching + price >= 20 % **and** top-1 brand share of conversation <= 50 % |
| Leader | dissatisfaction >= 20 %, but one product dominates the conversation (> 50 %) |
| Seeking but satisfied | "which one" share >= 25 %, dissatisfaction < 20 % - buyers compare, they do not flee |
| Weak | everything else |
| Quiet | too few documents |

The rule was tightened once: a first version required only "in motion" (seeking + complaints + switching + price >= 30 %) and turned about three quarters of niches green - a rule that passes almost everything is not a filter. Requiring actual **dissatisfaction** is what makes green informative.

**Trend of discussion** is computed only for native subreddits and only where the export did not hit the page limit; otherwise the series would be distorted.

**Seller-side voice** (optional): the same machinery over seller/builder communities extracts role, monetisation model, prices, client counts, outcome and obstacles - useful to see how others sell into a niche, not whether buyers want it.

**Biases to remember:** Reddit skews US and technical; it lags new categories; LLM themes and quotes are not hand-validated.

### Russian buyer voice: reviews

Reddit hears almost no Russian speakers, yet most shortlisted niches have geo `both`. For them S10 also reads the reviews of each niche's leading products in the Russian App Store and Google Play and, for business software, on Startpack (`s10_ru_reviews_*`, market `ru`; settings and thresholds in `config/ru_reviews.yaml`).

**Collection.** App stores, per niche and store: the relevant apps with the most ratings from the S5 App Store set and the S8 Google Play set (by default up to 8 per store, at least 20 ratings each) that pass a product check. The relevance of S5 and S8 is loose: a top search position or a substring is enough. And the most-rated candidates are often giants where the task is a side feature. In the first full-shortlist fetch (2026-11-21) these were CookieRun games for cookie consent widgets, Instagram and TikTok for transcription, the Wildberries and Ozon shopper apps for seller analytics, Yandex Go for auto repair shops. So an LLM gets the niche (who, task, product) and the 30 most-rated candidates per store (name, developer, store genre). For each app it answers whether these users would choose it or weigh it against the niche's products. Games, apps for the other side of a market (shoppers, guests, tenants, a club's members when the niche serves the business) and general apps fail. The check kept 1,103 of 1,487 candidates. The decisions with reasons are in `ru_reviews_fit.csv`, and `apps` in the config overrides them per niche. App Store: the public reviews RSS, at most the 500 newest reviews per app. Google Play: the 500 newest Russian reviews. Only the last 12 months are kept. Startpack (startpack.ru), the Russian analogue of Capterra, carries the B2B voice that app stores lack: the products listed per niche in `config/startpack_map.yaml`, up to 200 newest reviews each (pros, cons, text), last 36 months. Its categories are broad and overlap (an online-booking category mixes fitness CRMs, clinics and hotel PMS), so the map lists products by hand rather than taking whole categories. B2B products collect reviews slowly: in a 24-month window half of the B2B niches tried on 2026-11-20 had fewer than 80 reviews, hence 36 months.

**Labelling.** Up to 240 reviews per niche with at least 40 characters, drawn round-robin across apps so the leader does not drown the smaller players. The LLM marks whether a review is about the app or about the offline service behind it (the driver, the salon, the shop), the intent, the pain, the switch and willingness to pay. Shares are over reviews about the app. **Unmet needs** = missing feature + price + switching. **The gap** = missing feature + switching in unhappy reviews: what a new product could offer. **Price** in unhappy reviews gets its own mark (see below). **Quality** = bugs + UX + ads + support: the incumbents do the job badly.

**Verdict rule** (not a score; `reviews_verdicts()`; it does not change S6):

| Verdict | Condition |
|---|---|
| **Gap** (green) | missing features and switches in reviews rated 3 stars or lower >= 15 % of all reviews about the app, and in the top third of the cohort (mid-rank percentile >= 0.67) |
| Quality | not a gap; bug/UX/ads/support share >= 30 % and in the top third |
| Unmeasured | not quality, and fewer than 30 reviews rated 3 stars or lower: the gap cannot be read |
| Content | praise >= 50 % and neither gap nor quality |
| Mixed | everything else |
| Quiet | fewer than 80 labeled reviews about the app, or fewer than 2 apps |

Beside any measured verdict a niche can carry the mark **💰 paywall**: price complaints in reviews rated 3 stars or lower >= 15 % of all reviews about the app and in the top third of the cohort where the gap can be read. It never changes the verdict.

**Why the gap counts only unhappy reviews (changed 2026-11-21, while the thresholds were a draft).** The first rule counted every unmet-need review. In the trial run of 11 niches the control `ctrl-task-manager`, an expected saturated market, had the highest unmet share of the B2B cohort, 32 %. Its reviews showed why. 34 of its 42 missing-feature reviews were five-star wishlists ("no per-user language setting"): Startpack asks every reviewer for cons, and 90 % of its reviews are five-star. All 31 switches were arrivals ("moved from Trello after it left Russia"), a sign that substitutes exist, the opposite of a gap. Dropping feature wishes alone did not help: price and switching still put the control first in B2B (15 %). Counting an unmet need only in a review rated 3 stars or lower gives the control 2 %: a missing feature counts when it makes the user unhappy. The share stays over all reviews about the app, and the floors were not changed. A niche with fewer than 30 unhappy reviews is "unmeasured", not "content": too few unhappy reviews on Startpack say more about the source than about the market. Such niches are left out of the gap percentiles, so they do not lift the others' ranks. In practice the Startpack-heard B2B niches are almost all unmeasured, so for them the reviews layer is qualitative: pain themes as interview material. Not yet done: the direction of a switch (leaving vs arriving) as a separate label, and a check whether an unmet feature is praised in a rival's reviews, which would separate "my product lacks it" from "nobody offers it".

**Why price left the gap (changed 2026-11-21, while the thresholds were a draft).** The first full-shortlist run (45 niches, after the product check) failed its controls. Two of the three saturated controls got "gap": document scanners (B2C, 27 %) and website builders (B2B, 16 %, just over the 15 % floor). The AI song control (Suno and a dozen clones) topped the B2C gap at 55 %. Split by intent, the unmet share in unhappy reviews was almost all price: 25 % of 27 % for scanners, 52 % of 55 % for AI songs. Missing features in unhappy reviews were 0 to 6 % in every niche with enough reviews, at most 12 %. So the gap measured anger at paywalls, and the hardest paywalls sit in saturated clone markets, where many near-identical apps monetize with a paywall before any trial. That is the opposite of a gap. Price now gets the separate 💰 paywall mark with the same floor and percentile as the gap, and the gap counts missing features and switches only. The floors were not changed: lowering the gap floor to about 8 % would have let one product niche through above every control, but that would be a threshold chosen after seeing the data. After the change no niche reaches the gap floor; all five controls are "mixed", and two of them (document scanners, AI songs) carry the paywall mark. In practice an app store review rarely names a missing feature when it is unhappy: the layer's signals are quality, paywall pressure and the pain themes as interview material.

Why relative: written reviews lean negative, since the unhappy user is the one who writes. An absolute complaint threshold like the Reddit rule's 20 % would pass nearly every niche, so a share must stand out against the other niches of the run and clear an absolute floor. Percentiles are taken within a segment, B2C + prosumer or B2B, as in the score: the segments are heard through different sources with different biases (app stores lean negative, Startpack leans positive), and one pooled cohort would rank the sources, not the niches. With fewer than 6 measured niches in a segment percentiles mean nothing and the floors alone decide. The thresholds start as a draft (`status: draft`, a banner in the report) and are fixed before the first real verdicts are read, under the same rules as the score weights.

**Biases:** reviews come from people who already use a product, so they show what is missing in existing products, not demand from people who have none. Startpack reviews arrive in vendor campaigns (bursts of same-day five-star reviews from new accounts), so one product can be most of a niche's B2B voice: the reason then carries a caution when one product gives more than 60 % of the sample. RuStore is not covered, and a B2B niche without mobile apps or Startpack products is quiet here. For big apps the 500-review cap covers days or weeks, not a year.

### Buyer voice: YouTube comments

For shortlisted niches (Russian by default, `--lang en` for US English), `s10_yt_comments_*` searches YouTube with the niche's own queries, keeps the videos an LLM judges to be watched by the niche's buyers (how-to videos, product reviews) and reads up to 300 top-level comments under each of the five most-commented ones; comments by the video's own channel and non-Cyrillic comments (in the Russian run) are dropped. A sample of 300 comments per niche is labelled: about the niche, about the video only, or off topic; then pain, unmet need, price, product request, how-to question or praise. The verdict is relative like the reviews rule, within B2C + prosumer or B2B: `gap` needs unmet needs + price in the top third of the segment and at least 10 %, then `pain`, `seeking` (product requests: buyers compare, they do not flee), `how-to`, `content` and `mixed`; `quiet` under 60 comments about the niche or under 2 such videos; `incomplete` when an LLM batch gave no answer. The reason carries a caution when one video gives more than 60 % of the comments. Comments under how-to videos carry the voice of the task more than of the products, so a high how-to share points to demand for know-how (the info cohort) rather than a software gap. It never changes S6, and its thresholds are a draft in `config/yt_comments.yaml`. Searches spend the YouTube quota shared with `info_youtube` (100 units each, plus a separate daily cap on search calls), so a full shortlist takes two or three days of runs; cached niches are free.

---

## 10. What the pipeline proves and what it cannot

### It supports

- Where demand exists in search and in app stores, and whether it is rising on more than one independent source.
- Where supply is fragmented by an independent signal, and where one product dominates.
- Which niches are crowded with new entrants and which have survivors.
- Whether the goal is reachable without winning the niche, as an order-of-magnitude statement.
- Which trap-ridden numbers to ignore (contaminated history, homonyms, calendar artefacts).

### It cannot prove

| Not covered | Consequence |
|---|---|
| **Customer conversations.** No interviews, no willingness-to-pay test, no evidence of a specific buyer's pain | A green niche has a market; it does not have *your* customer. Reddit voice and app reviews are weak, biased substitutes |
| **Customer-acquisition cost.** The path-to-goal layer says how many payers you need, not what each costs. Keyword Planner CPC is the only price signal; `s5_serp` shows whether the organic page is winnable (who owns it, keyword difficulty), not what a customer costs | The most likely reason a "reachable" niche fails is that acquisition costs more than revenue per customer |
| **True market size.** Sizes are proxies (ratings x multipliers, reviews x multipliers, searches x conversion), accurate to about a factor of two at best; some niche sizes are manual estimates. For one-industry B2B niches the business registers now count the *who* (s8_who_counts), which bounds the proxy but is not a count of buyers | Do not quote a niche size to anyone as a fact |
| **Revenue of competitors.** Only listings and top-grossing positions are visible; for Russian B2B vendors in the software register, company income from public statements (`ru_vendor_revenue`) - the whole company's, not the product's | You cannot see unit economics |
| **Quality of competitors and of your product.** The tool does not use the product at all | A fragmented market can be fragmented because every product is bad - or because none can retain users |
| **Demand inside chatbots.** No provider publishes per-query statistics; "AI search volume" products are models of Google data (S3, `s3_ai_volume`) | Search volume ranks niches correctly only if the move to chatbots is similar across them. Expect it to differ most for how-to and informational queries; read a falling trend in such niches as possible migration, not only lost demand |
| **Platform response.** Platform risk is a manual call, and by construction the tool is blind to categories where a new leader forms quickly | New categories with an early leader fail the monopolist gates (the pipeline sees mature fragmented markets, not young ones) |
| **Anything after the clean window.** Recent growth in tool queries cannot be confirmed from search; app-store snapshots and cohorts are the only fresh signals | Re-run snapshots a month later; do not trust recent year-over-year in Keyword Planner |
| **B2B in search.** Search barely shows B2B demand | B2B verdicts rest more on directories, reviews and brand-anchored trends than on volume |
| **Legal, tax and payment feasibility** for a specific founder | Outside scope |
| **Info cohort: views are not buyers.** Short-video metrics show attention and whether creators sell, not conversion or revenue; Reels and TikTok are not measured at all | Validate an info topic by publishing: a series of shorts and a lead magnet in a Telegram channel, then count subscribers and sales |

The honest reading of the output: "a niche that passes is a *candidate worth interviewing about*", not "a niche worth building in".

---

## 11. Recommended validation after screening

Screening is the cheap part. The following steps are suggested, in increasing cost; stop at the first that kills the idea.

1. **Dependencies and access.** Confirm you can charge customers in this niche through the relevant channel (app-store payouts, payment processor, telephony or data APIs you need, regulatory registrations).
2. **Market size by hand.** Re-estimate the niche from the vendors' own pages (customer counts, pricing pages, case studies) and compare with the proxy in the passport; any manual estimate in the output is the first to verify.
3. **Competitors and channels.** Use the top 5 players for a week: pricing, onboarding, reviews of 1-2 stars (app-store RSS, directory reviews), where each one acquires customers (SEO, ads, marketplaces, partners). Check that the SERP is not owned by the leaders.
4. **Unit economics.** A back-of-envelope model: ARPU from section 8, retention by ticket tier, acquisition cost from paid search at the observed CPC and a realistic conversion rate, and the cost of serving a customer (API, telephony, support). The required number of new customers per month to hit the goal follows directly.
5. **Customer interviews and a landing page.** 10-20 conversations with people in the segment; a landing page with a price and a call to action; look for willingness to pay, not agreement.
6. **One-page spec, then MVP.** Only after steps 1-5 survive.

Re-run S9 snapshots after 30 days to see who is actually growing, and re-run the pipeline monthly from cache to see whether the shortlist is moving.
