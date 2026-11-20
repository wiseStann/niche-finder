# Idea sources: where to look for niches and how to read each signal

This page is a registry of 49 platforms that can be used to find business ideas or to evaluate a niche, each probed for access (API, RSS, server-rendered HTML, bulk dump, browser only, paid). The registry is the source of truth in [`idea-sources.yaml`](idea-sources.yaml); everything below the introduction is generated from it by `scripts/render_idea_sources.py`.

Only a few of the sources are wired into the pipeline today (status `in_pipeline`; the `adapter` field names the stage module). The rest are documented so that a stage can be written without repeating the research: what the platform gives, how fresh the data is, how to get it for free, and where the traps are. Stage group names used in the registry (`s0`, `s5`, `s8`, `s10`, ...) match the groups in `src/nichefinder/stages/__init__.py`.

Every probe is a dated fact ("probed 2026-09-20 with curl, no keys, from one network"). Sites change paths, put up Cloudflare, or open APIs. Re-probe before relying on an entry.

## Three questions for every source

| Axis | Question | Registry field |
|---|---|---|
| Role | Does it give new entities for the universe (`discovery`), a metric for a niche (`evaluation`), buyer voice (`voice`) or dynamics over time (`trend`)? | `role`, `stages`, `feeds` |
| Access | API / RSS / server-rendered HTML / bulk dump / browser only / paid; key; price; limits; what the probe showed | `access[]`, `probe` |
| Freshness | realtime / daily / weekly / monthly / quarterly; can a time series be accumulated, or only a snapshot? | `freshness` |

Two rules from the pipeline design carry over. First, never reach a verdict from one source: a new platform is valuable mostly as a second or third source for an axis that had only one (deals, voice, "who is entering"). Second, source prior: proven beats rising. Most launch and funding platforms are "rising" and are read in reverse: many launches, rounds or portfolio companies in a niche mean a red ocean in about 12 months, not a green market.

## The three signal classes

Keep these apart when reading any table below.

1. **Rising** (Product Hunt, BetaList, Launching Next, Show HN, YC, VC portfolios, Crunchbase). Says who is entering. These are competitors a year from now, not demand.
2. **Proven / transactions** (Flippa, Empire Flippers, Quiet Light, Acquire, Indie Hackers verified revenue, successful Kickstarter campaigns). Says who already earns money and what a business sells for. This is the only direct money signal for niches of small players.
3. **Voice / hiring** (Reddit, Ask HN, HN "Who is hiring?", Wellfound, hh.ru). Says what hurts and what people hire for. Confirms demand outside search.

Patents are a fourth, narrow case: for SMB software the count is almost always 0 (report it as NA, not as "no interest"). They are useful as a big-tech platform-risk flag and for hardware niches.

## How to read the numbers

- A zero from a developer-heavy platform (Hacker News, Product Hunt, Wellfound, Remote OK) in a consumer or offline vertical (gardeners, churches, tattoo studios) means "not represented": use NA, not 0.
- Launch counts are a density signal, not a quality signal. Votes, reviews and self-reported revenue are inflated; count launches and repeats instead.
- A snapshot is not a history. Where a source gives only a snapshot (portfolios, Kickstarter dumps, marketplaces), a trend appears only from a series of snapshots taken on a schedule.
- Full-text search catches homonyms ("church" outside religion); keep a stop-context list per niche, the same as for query generation.
- New signals are best used as confirmation or a flag in the niche passports (like the Reddit and off-search blocks), not as new score components. A veto flag ("3+ top-fund portfolio companies in the niche") is cheaper and more honest than a score.

## Traps per platform family

| Family | Main trap |
|---|---|
| Product Hunt, BetaList, Launching Next | Votes are bought; topics are labelled by authors (up to 4 per post), so map to a niche with keyword regexes. About half of BetaList entries never launch (that is a feature: you see intentions, mark them `pre`). Launching Next is volume and freshness only. |
| Indie Hackers | The list is a JS app; revenue is rendered client-side. Only about 20% of products have verified revenue, the rest is self-reported. Biased toward dev tools. |
| Hacker News | Developer audience. Algolia full text matches homonyms. Hiring posts are free text and need keyword matching plus an LLM for disputed cases. |
| Reddit | US/English. The official API is closed; a mirror (Arctic Shift) works for date listings only and some networks drop about 15% of connections. |
| Crunchbase, Dealroom, PitchBook | Paid and behind Cloudflare. For niches worth a few million dollars, venture money is closer to a counter-indication than a plus. |
| SEC Form D | Issuer is often a legal entity, not the brand; the industry field has about 30 coarse classes ("Other Technology" is all software). Useful as a counter over known competitor names, not as niche discovery. |
| VC portfolios | A portfolio is a thesis from 2-8 years ago. Freshness comes only from the delta between snapshots. Market maps are reading material, not data. |
| Marketplaces for businesses | Low segments are self-reported; Empire Flippers verifies numbers but most of its listings are Amazon FBA, content and e-commerce, and the niche exists only as text in the title. |
| Kickstarter | Hardware, games and design, not SaaS. The live site is behind Cloudflare; monthly full dumps exist. |
| Patents | Software patents rarely mean a product. "Abandoned patents" are not a source of ideas for software. |
| Wellfound | Company cards are blocked; keyword search needs a login, so only role and location pages are usable. |

## Paid versus open access, and replacements

Free and keyless sources found by probing: Hacker News (Algolia API plus the official Firebase API), Empire Flippers (public JSON of about 2,900 listings with verified P&L), BetaList, Launching Next and Product Radar (launches), Kickstarter monthly dumps (Web Robots), Google Patents (XHR JSON), five VC portfolios in server-rendered HTML (a16z, Index, NEA, Greylock, Accel), Crunchbase News RSS, the NVCA Venture Monitor PDF.

Paid or closed, with the replacement that was found:

| Closed or paid | What it would give | Free replacement |
|---|---|---|
| Crunchbase (API from about $1k/month, site behind Cloudflare) | Funding rounds per niche | SEC Form D for the fact of money raised in the US; Crunchbase News RSS for rounds as text; VC portfolios and YC for "who is building what" |
| Dealroom, PitchBook (about $20k/year) | Rounds, M&A, multiples | Free sector PDF reports; the NVCA Venture Monitor for macro volumes and public SaaS M&A multiples |
| Kickstarter live site, Indiegogo | Pre-order demand | Web Robots monthly Kickstarter dumps |
| BizBuySell, Avito and Russian business-for-sale sites (anti-bot) | Economics of the customer (median cash flow of a salon or a repair shop) | Browse by hand for 3-5 niches |
| Acquire.com | Largest flow of SaaS listings with ARR and multiples | Buyer account and manual export, about 20 minutes per niche |
| SEC full-text search (geo filter) | Form D by keyword | The quarterly `form.idx` index is open, but amounts require downloading each XML |

## Freshness: what can become a series

Daily or realtime without keys: Hacker News (archive since 2007, so a series exists immediately), the Product Hunt Atom feed, Launching Next RSS, Remote OK (latest 100, needs daily accumulation), Empire Flippers (listing dates and days on marketplace give a series). Monthly snapshots that accumulate into a series: Kickstarter dumps (history since 2014), BetaList, Product Radar, VC portfolios, Flippa. Quarterly: YC batches, NVCA. This complements the App Store and Google Play snapshot stages: next to "supply over time" you get "entries and exits over time".

## What was deliberately judged not worth doing

- Buying Crunchbase, Dealroom, PitchBook or Tracxn: "capital in a niche" works as a veto flag, which is free from VC portfolios plus YC.
- Headless-browser parsers for JavaScript-only sites (Sequoia, live Kickstarter, Indiegogo, Acquire, Indie Hackers) while server-rendered sources and dumps are enough.
- Searching patents for ideas in software.

## Probe journal (2026-09-20, curl, no keys, one network)

- Open (200, no key, parseable): Product Hunt leaderboard / feed / topics, Product Radar categories, BetaList home and topics, Launching Next RSS, HN Algolia and Firebase, Empire Flippers API, Quiet Light, Microns, FE International, Google Patents XHR, Web Robots Kickstarter dumps, Wellfound `/jobs`, `/role`, `/startups`, Remote OK API, a16z / Index / NEA / Greylock / Accel, Crunchbase News RSS, NVCA, SEC `form.idx`, USPTO bulk catalogue, FIPS registers (forms).
- Key needed (401): Product Hunt GraphQL (free), Crunchbase API (paid), USPTO Open Data Portal (free), Lens (free for non-commercial), Rospatent API (by request).
- Closed from the probing network (403, 429, 406, 000): Crunchbase site, Dealroom, PitchBook (including RSS), SEC full-text search (geo), Kickstarter live, Indiegogo, Wellfound company pages, Work at a Startup, BizBuySell, BusinessesForSale, Avito, Biboss, Tiny Acquisitions, PatentsView (connection), EPO OPS (fair use), Growjo, Tracxn.
- Changed paths (404 / 500): Bessemer, Kleiner, Point Nine, Initialized, Calm Fund, Altera Invest, Boomstarter, Planeta (307).

The generated registry follows.

---

# Registry of idea sources (v2026-09-20)

Generated from [`idea-sources.yaml`](idea-sources.yaml) by `scripts/render_idea_sources.py`. Edit only the YAML.

**50 sources, 77 access methods:** ✅ in_pipeline - 23, 🛠 planned - 8, ✋ manual - 5, ⛔ blocked - 11, 💰 paid - 3.  
Priorities: P1 - 6, P2 - 20, P3 - 15, none - 9.

Legend. **Status:** ✅ a pipeline stage exists · 🛠 no stage yet (not implemented) · ✋ by hand / browser only · ⛔ closed from the probing network · 💰 paid only. **Probe:** the HTTP code of a keyless curl probe (date). **Role:** discovery = entities for the universe, evaluation = a metric for a niche, voice = buyer voice, trend = dynamics over time.

## Implementation queue (planned, by priority)

| P | Source | Group | Stage | Stage groups | What it would give |
|---|---|---|---|---|---|
| P1 | Empire Flippers (API) | m_and_a | not implemented | s0, s5, s6 | 29 requests -> a CSV of listings; in the deals stage count ef_listings, ef_sold_12m, ef_median_profit, ef_multiple per niche; in the ceiling stage the median SaaS multiple is an anchor for the exit price |
| P2 | Otvety Mail.ru (Q&A) | community | not implemented | s10 | Discovery through the SERP, questions and answers through the JSON API, then the S10 labelling (seeking / complaint / switching / price) as for Reddit |
| P2 | Wellfound (AngelList Talent) | hiring | not implemented | s8, s0 | Walk /role/l/<role>/<location> for 10 roles x 5 locations monthly -> JSON from the HTML -> a company table with high_concept; match to niches. Low priority: HN hiring gives the same more cheaply |
| P2 | Launching Next | launch | not implemented | s0 | Collect the RSS daily into a cache (accumulate), merge into the universe once a month; use as a third 'launch density' counter (PH + BetaList + LN) |
| P2 | Quiet Light Brokerage | m_and_a | not implemented | s5, s6 | The same fetcher as Empire Flippers: page -> CSV; multiples by type feed the ceiling stage |
| P2 | Google Patents (XHR) | patents | not implemented | s5, s6 | For shortlisted niches: total over 24 months and over the 24 months before (YoY), top-3 assignees; an IP:bigtech flag if the top 3 include Google / Apple / Microsoft / Amazon / Meta / Salesforce / Intuit. On demand only - not part of a mandatory run |
| P2 | Portfolios of top funds (a16z, Sequoia, Accel, Index, NEA, Greylock, ...) | vc_portfolio | not implemented | s0, s6 | A stage for the 5 SSR funds (a16z JSON, Index, NEA, Greylock, Accel) -> a CSV (fund, name, one_liner, category, url); a snapshot every quarter; a VC:crowded flag at >= 3 portfolio companies in a niche goes into the passport |
| P3 | Remote OK (API) | hiring | not implemented | s8 | A daily accumulator into a cache folder; match monthly |

## Summary table

| Source | Group | Geo | Role | Freshness | Best access | Probe | Status | P | Stage groups |
|---|---|---|---|---|---|---|---|---|---|
| **Product Hunt** (`product_hunt`) | launch | global | discovery, evaluation | daily | html_ssr · none · $0 | 200 (2026-09-20) | ✅ in_pipeline | P2 | s0, s5 |
| **Product Radar (RU)** (`product_radar`) | launch | ru | discovery | daily | html_ssr · none · $0 | 200 (2026-09-20) | ✅ in_pipeline | P2 | s0, s5 |
| **BetaList** (`betalist`) | launch | global | discovery | daily | html_ssr · none · $0 | 200 (2026-11-17) | ✅ in_pipeline | P1 | s0, s5 |
| **Launching Next** (`launching_next`) | launch | global | discovery | daily | rss · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s0 |
| **Crunchbase** (`crunchbase`) | funding | global | evaluation | daily | rss · none · $0 | 200 (2026-09-20) | 💰 paid | P3 | s5, s6 |
| **Dealroom** (`dealroom`) | funding | global | evaluation | daily | manual · email · $0 | 200 (2026-09-20) | 💰 paid | none | s5 |
| **PitchBook** (`pitchbook`) | funding | global | evaluation, trend | quarterly | manual · none · $0 | 200 (2026-09-20) | 💰 paid | none | s6 |
| **SEC EDGAR - Form D (US private placements)** (`sec_form_d`) | funding | global | evaluation | daily | bulk_index · a User-Agent with a contact is mandatory (SEC rule), <= 10 requests/s · $0 | 200 (2026-09-20) | ⛔ blocked | P3 | s5 |
| **Y Combinator (yc-oss JSON)** (`yc_oss`) | funding | global | discovery, evaluation | quarterly | json · none · $0 | 200 (2026-09-15) | ✅ in_pipeline | P2 | s0, s5 |
| **TinySeed (portfolio)** (`tinyseed`) | funding | global | discovery, evaluation | quarterly | manual · none · $0 | 200 (2026-09-15) | ✅ in_pipeline | P3 | s0, s5 |
| **Indie Hackers** (`indie_hackers`) | community | global | discovery, voice | daily | html_spa · none · $0 | 200 (2026-09-20) | ✋ manual | P3 | s0, s5 |
| **Hacker News (Algolia API)** (`hacker_news`) | community | global | discovery, voice, trend | realtime | api · none · $0 | 200 (2026-09-20) | ✅ in_pipeline | P1 | s8 |
| **Reddit (Arctic Shift + subredditstats)** (`reddit`) | community | global | voice, trend | daily | api · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s8, s10 |
| **Otvety Mail.ru (Q&A)** (`otvet_mail_ru`) | community | ru | voice | daily | api · none · $0 | 200 (2026-11-20) | 🛠 planned | P2 | s10 |
| **Kickstarter (Web Robots dumps)** (`kickstarter`) | crowdfunding | global | discovery, evaluation | monthly | bulk_dump · none · $0 | 200 (2026-09-20) | ✅ in_pipeline | P2 | s0, s5 |
| **Indiegogo** (`indiegogo`) | crowdfunding | global | discovery | daily | html · none · $0 | 403 (2026-09-20) | ⛔ blocked | none | s0 |
| **Planeta.ru / Boomstarter (RU)** (`ru_crowdfunding`) | crowdfunding | ru | discovery | daily | html · none · $0 | 307 (2026-09-20) | ✋ manual | none | s0 |
| **HN 'Who is hiring?' (monthly threads)** (`hn_who_is_hiring`) | hiring | global | evaluation, trend | monthly | api · none · $0 | 200 (2026-09-20) | ✅ in_pipeline | P1 | s8 |
| **Wellfound (AngelList Talent)** (`wellfound`) | hiring | global | evaluation, discovery | daily | html_ssr · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s8, s0 |
| **Remote OK (API)** (`remoteok`) | hiring | global | evaluation | daily | api · none · $0 | 200 (2026-09-20) | 🛠 planned | P3 | s8 |
| **YC Work at a Startup** (`yc_jobs`) | hiring | global | evaluation | daily | html · none · $0 | 406 (2026-09-20) | ⛔ blocked | none | s8 |
| **hh.ru (API, needs a Russian IP)** (`hh_ru`) | hiring | ru | evaluation | daily | api · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s8 |
| **Portfolios of top funds (a16z, Sequoia, Accel, Index, NEA, Greylock, ...)** (`vc_portfolios`) | vc_portfolio | global | discovery, evaluation | monthly | html_json · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s0, s6 |
| **Google Patents (XHR)** (`google_patents`) | patents | global | evaluation, trend | weekly | xhr_json · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s5, s6 |
| **USPTO PatentsView API** (`patentsview`) | patents | global | evaluation | quarterly | api · a free API key (a form on patentsview.org) · $0 | 000 (2026-09-20) | ⛔ blocked | P3 | s5 |
| **USPTO Open Data / Bulk (PEDS, maintenance fees)** (`uspto_bulk`) | patents | global | evaluation | weekly | bulk · none · $0 | 200 (2026-09-20) | ⛔ blocked | P3 | s5 |
| **Lens.org** (`lens_org`) | patents | global | evaluation | weekly | api · a token (free for non-commercial use, by request) · $0 | 401 (2026-09-20) | ⛔ blocked | none | s5 |
| **EPO OPS (Espacenet)** (`epo_ops`) | patents | global | evaluation | weekly | api · registration, an OAuth key; 4 GB/week free · $0 | 403 (2026-09-20) | ⛔ blocked | none | s5 |
| **FIPS / Rospatent / Yandex.Patents (RU)** (`fips_rospatent`) | patents | ru | evaluation | weekly | html_form · none · $0 | 200 (2026-09-20) | ✋ manual | P3 | s5 |
| **Flippa (SaaS listings)** (`flippa`) | m_and_a | global | discovery, evaluation | daily | html_ssr · none · $0 | 200 (2026-09-15) | ✅ in_pipeline | P2 | s0, s5 |
| **Empire Flippers (API)** (`empire_flippers`) | m_and_a | global | discovery, evaluation | daily | api · none · $0 | 200 (2026-09-20) | 🛠 planned | P1 | s0, s5, s6 |
| **Quiet Light Brokerage** (`quiet_light`) | m_and_a | global | evaluation | weekly | html_ssr · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s5, s6 |
| **Acquire.com (MicroAcquire)** (`acquire_com`) | m_and_a | global | discovery, evaluation | daily | html · a buyer account (free, but with verification); listings are visible after login · $0 | 404 (2026-09-20) | ✋ manual | P3 | s0, s5 |
| **FE International / Microns / Tiny Acquisitions / SideProjectors** (`fe_microns_tiny`) | m_and_a | global | discovery | daily | html · none · $0 | 200 (2026-09-20) | ✋ manual | P3 | s0 |
| **BizBuySell / BusinessesForSale.com** (`bizbuysell`) | m_and_a | global | discovery, evaluation | daily | html · none · $0 | 403 (2026-09-20) | ⛔ blocked | P3 | s6 |
| **RU 'ready business': Avito / Biboss / Altera Invest / business-asset** (`ru_business_sale`) | m_and_a | ru | discovery, evaluation | daily | html · none · $0 | 429 (2026-09-20) | ⛔ blocked | P3 | s6 |
| **App Store (iTunes Search / RSS / pages)** (`appstore`) | store | both | discovery, evaluation, trend, voice | daily | api · none · $0 | 200 (2026-09-16) | ✅ in_pipeline | P2 | s0, s5, s8, s9, s10 |
| **Google Play (google-play-scraper)** (`google_play`) | store | both | discovery, evaluation, trend, voice | daily | scraper · none · $0 | 200 (2026-09-16) | ✅ in_pipeline | P2 | s0, s5, s8, s9, s10 |
| **Shopify App Store** (`shopify_app_store`) | store | global | discovery, evaluation | daily | html_ssr · none · $0 | 200 (2026-09-16) | ✅ in_pipeline | P2 | s0, s5 |
| **WordPress.org plugins** (`wordpress_org`) | store | global | discovery | daily | api · none · $0 | 200 (2026-09-16) | ✅ in_pipeline | P3 | s0 |
| **Capterra / GetApp (Gartner Digital Markets)** (`capterra_getapp`) | store | global | evaluation | weekly | html_ssr · none · $0 | 200 (2026-09-15) | ✅ in_pipeline | P2 | s5 |
| **G2** (`g2`) | store | global | evaluation | weekly | html · none · $0 | 403 (2026-09-15) | ⛔ blocked | none | s0 |
| **DataForSEO (Google Ads search_volume)** (`dataforseo`) | search | global | evaluation, trend | monthly | api · DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD · $0.09/call up to 1,000 keywords | 200 (2026-09-16) | ✅ in_pipeline | P1 | s3, s4 |
| **Yandex Wordstat API v2** (`wordstat`) | search | ru | evaluation, trend | monthly | api · YANDEX_API_KEY · $0 | 200 (2026-09-16) | ✅ in_pipeline | P1 | s2, s3, s4 |
| **Google Trends (trendspy) + YouTube (gprop=youtube)** (`google_trends`) | search | global | trend | weekly | scraper · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s4, s8 |
| **Google / Yandex autocomplete** (`suggest`) | search | both | evaluation | daily | api · none · $0 | 200 (2026-09-15) | ✅ in_pipeline | P3 | s2 |
| **Register of Russian software (Ministry of Digital Development)** (`reestr_mincifry`) | ru_registry | ru | evaluation | daily | html_ssr · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s0 |
| **zakupki.gov.ru (Federal Laws 44-FZ / 223-FZ)** (`zakupki`) | ru_registry | ru | evaluation | daily | html · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s0 |
| **Bitrix24 Market** (`bitrix24_market`) | ru_registry | ru | evaluation | daily | html · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P3 | s0 |
| **Startpack** (`startpack`) | ru_registry | ru | evaluation | weekly | html · none · $0 | 403 (2026-09-17) | ⛔ blocked | none | s0 |

## Sources by group

### launch - Launch platforms - what is entering the market now (rising)

#### ✅ Product Hunt (`product_hunt`) - P2

https://www.producthunt.com · geo global · role discovery, evaluation · freshness daily · stage groups s0, s5 · stage `s0_producthunt`

Signals:
- new products for a period: name, tagline, topics, votes - who is launching and with what
- launch density per topic over 12 months -> ph_launches_12m (s5 deals / liquidity)
- repeat launches of one product (v2, v3) - a sign of a live market

Feeds: `data/out/universe.csv (source=ph:*, rising)`; `data/out/deals.csv: ph_launches_12m`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://www.producthunt.com/leaderboard/{monthly\|weekly}/{y}/{m}/all | none | $0 | ~1.5 s between pages; 612 KB per page; JSON inside the HTML (regex on __typename:Post) | 200 2026-09-20 - works, same as on 2026-09-15; monthly and weekly leaderboards |
| atom | https://www.producthunt.com/feed  (?category=<topic-slug>) | none | $0 | 50 latest posts; has title, tagline, published, link; no votes and no topics | 200 2026-09-20 - 44 KB, 50 entries, the freshest - a daily pulse |
| graphql | https://api.producthunt.com/v2/api/graphql | developer token (free, register an application at producthunt.com/v2/oauth/applications) | $0 | query complexity <= 6,250 / 15 min; posts(topic, postedAfter) + votesCount, commentsCount, makers, topics | 401 2026-09-20 - invalid_oauth_token without a token - expected; with a token it gives an exact slice by topic and date |
| html_ssr | https://www.producthunt.com/topics/<slug> | none | $0 | topic page: number of followers and products of the topic - the size of the category audience | 200 2026-09-20 - 606 KB SSR |

Traps:
- Votes are bought or inflated; the signal is the number of launches and repeats, not votes
- Biased toward AI wrappers and dev tools; SMB B2B verticals are poorly represented
- Up to 4 topics per post, labelled by the authors - matching to a niche needs regexes (deal_keywords.yaml)

Plan: Add the Atom feed as a daily pulse (a weekly delta of what launched per topic) and GraphQL for an exact per-topic slice once a token is available

#### ✅ Product Radar (RU) (`product_radar`) - P2

https://productradar.ru · geo ru · role discovery · freshness daily · stage groups s0, s5 · stage `s0_productradar`

Signals:
- Russian-language launches: name, description, category, awards (product of the week / month), number of comments
- categories 'looking for a partner / investor / mentor' - who has not found a model yet
- slices ?groupby=week|month|year|base - what won in a category over a period

Feeds: `data/out/universe.csv (source=productradar, rising, geo=ru)`; `data/out/deals.csv: productradar_12m (passport, not scored)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://productradar.ru/wp-admin/admin-ajax.php  POST action=more-handler&next_period=<months back>&next_page=<n>&group_by=month (15 cards per page); also https://productradar.ru/category/<cat>/<subcat>/?groupby=month\|year\|base | none | $0 | WordPress theme vchunt; cards article.products__item: card__title, card__description, awards, comments; the product post type is hidden from REST | 200 2026-09-20 - 78 KB, 8 products on a category page; REST /wp-json/wp/v2/product -> 404 (rest_no_route), only posts/blog |
| rss | https://productradar.ru/feed | none | $0 | blog only (10 entries), not launches | 200 2026-09-20 - 187 KB RSS, blog / streams - useless for the universe |

Traps:
- Small volume (tens of launches a month) - weak as a source of niches, useful as an indicator of Russian competitors in a chosen niche
- No revenue metrics; voting is done by platform residents

Plan: Done (2026-11-17): s0_productradar reads the monthly feed through admin-ajax (action=more-handler, group_by=month; ~40 launches a month) over curl, because the TLS chain fails Python's check. Next: one walk of ?groupby=base for the full base

#### ✅ BetaList (`betalist`) - P1

https://betalist.com · geo global · role discovery · freshness daily · stage groups s0, s5 · stage `s0_betalist`

Signals:
- products BEFORE launch (beta): name, tagline, topics - a window of 3-6 months before Product Hunt
- density of beta submissions per topic - where new founders are heading

Feeds: `data/out/universe.csv (source=betalist, rising)`; `data/out/deals.csv: betalist_12m (passport, not scored)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://betalist.com/startups?page=N  (chronological, ~50 startups per page under day headings data-duplicate-id=day_<unix>); categories moved to /browse/<cat>/<sub> | none | $0 | 55 startups on the home page, 21 on a topic page; links /startups/<slug>, a card is name + tagline + topics; /feed and /startups -> 404 | 200 2026-11-17 - /startups?page=N works (250-270 KB, 50 rows with name + tagline); /topics/* is gone, replaced by /browse/* |

Traps:
- Many 'ideas without a product'; ~50% never launch - that is a feature (it shows intentions), but mark them source_type=rising/pre in the universe
- No numbers (votes / subscribers) in a card - only the fact and the date

Plan: Done (2026-11-17): s0_betalist walks /startups?page=N newest first for 12 months (~110 pages, ~5,300 startups); s5_deals counts betalist_12m per niche. Next: dedupe against Product Hunt by domain

#### 🛠 Launching Next (`launching_next`) - P2

https://www.launchingnext.com · geo global · role discovery · freshness daily · stage groups s0 · stage not implemented

Signals:
- daily launches (mostly micro-SaaS, indie, no-code): name, description, date

Feeds: `data/out/universe.csv (source=launchingnext, rising)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| rss | https://www.launchingnext.com/rss/ | none | $0 | 15 latest entries; title, link (/s/<slug>/<id>/), pubDate, description | 200 2026-09-20 - 7 KB RSS, 15 items, fresh within a day (2026-09-19) |
| html_ssr | https://www.launchingnext.com/  (categories and archive via /s/<slug>/<id>/ - the id is monotonic, ~152,000 on 2026-09-20) | none | $0 | 33 KB, static HTML; the archive is walked by id | 200 2026-09-20 - open |

Traps:
- Low quality (paid placements, SEO sites); the value is only volume and freshness. Match to niches with regexes, do not read by hand

Plan: Collect the RSS daily into a cache (accumulate), merge into the universe once a month; use as a third 'launch density' counter (PH + BetaList + LN)

### funding - Funding and rounds - where the money goes (rising; expensive confirmation of demand)

#### 💰 Crunchbase (`crunchbase`) - P3

https://www.crunchbase.com · geo global · role evaluation · freshness daily · stage groups s5, s6 · stage not implemented

Signals:
- rounds per company / category: amount, date, investors -> 'how much money entered the niche in 24 months'
- number of funded companies in a category -> capital concentration (many small rounds = fragmentation; one mega-round = a future monopolist)
- Crunchbase News - fresh rounds as text (a weak substitute for the API)

Feeds: `data/out/supply_deep.csv: funding_24m, funded_cos (idea, only with paid access)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.crunchbase.com/api/v4/  (searches/organizations, funding_rounds) | user_key - only on the Pro / Enterprise plan (~$49-99/month for Pro without API; the API is separate, from ~$1k/month) | paid | without a key 401 LA401 | 401 2026-09-20 - Unauthorized user_key |
| html | https://www.crunchbase.com/discover/... and /hub/... | none | $0 | Cloudflare 403 on any request without a browser | 403 2026-09-20 - blocked |
| rss | https://news.crunchbase.com/feed/ | none | $0 | news about rounds (tens a day), text - extract company / amount / category with a regex or an LLM | 200 2026-09-20 - 106 KB RSS, open |

Traps:
- Expensive for the signal it gives: for SMB niches worth '$5-10M', VC rounds are more of a counter-indication than a plus
- Free replacements: for the fact of money raised in the US - SEC Form D (see sec_form_d); for 'who is building what' - YC / Product Hunt / BetaList

Plan: Not worth buying. Accumulate the Crunchbase News RSS in a cache and once a month run niche regexes over it -> a funding_news_12m column in the passport as a reference

#### 💰 Dealroom (`dealroom`) - none

https://dealroom.co · geo global · role evaluation · freshness daily · stage groups s5 · stage not implemented

Signals:
- same as Crunchbase, with a focus on Europe; segment reports (open reports per vertical)

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.dealroom.co/api/v2/ | API key - corporate plan only | paid | both app.dealroom.co and the API sit behind a Cloudflare 'Just a moment' page without a browser | 403 2026-09-20 - Cloudflare |
| manual | https://dealroom.co/reports  (PDF reports per sector / country, free after a form) | email | $0 | quarterly reviews, not data | 200 2026-09-20 - blog open (HTML), no RSS |

Traps:
- Duplicates Crunchbase; gives little for SMB / prosumer niches. Useful only for reading vertical reports once a niche is chosen

Plan: Not worth implementing. Read the reports by hand when studying a chosen niche

#### 💰 PitchBook (`pitchbook`) - none

https://pitchbook.com · geo global · role evaluation, trend · freshness quarterly · stage groups s6 · stage not implemented

Signals:
- the fullest base of rounds / M&A / multiples; 'Emerging Spaces' - new segments according to analysts
- free: PitchBook-NVCA Venture Monitor (quarterly PDF) - volumes by stage and sector

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://pitchbook.com/news, /news/reports, /rss | none | $0 | Cloudflare 403 on everything, including RSS | 403 2026-09-20 - Cloudflare 'Just a moment' |
| manual | https://nvca.org/research/pitchbook-nvca-venture-monitor/  (PDF) | none | $0 | once a quarter, macro level (sectors, not niches) | 200 2026-09-20 - NVCA page open, PDF behind a link |

Traps:
- A subscription from ~$20k/year is out of scale for a small tool. For the revenue-ceiling estimate only public SaaS M&A multiples are useful (free in reports)

Plan: Not worth implementing. Read the Venture Monitor quarterly to calibrate ceiling assumptions (multiples, volumes by stage)

#### ⛔ SEC EDGAR - Form D (US private placements) (`sec_form_d`) - P3

https://www.sec.gov/edgar · geo global · role evaluation · freshness daily · stage groups s5 · stage not implemented

Signals:
- every round raised in the US (> $0) must file a Form D: issuer, amount, date, industryGroupType (Other Technology, Business Services...) - a free Crunchbase for the fact of money, without a product description
- number of new Form D filings by a keyword in the name / industry over 12 months -> 'how many companies in the niche raised money'

Feeds: `data/out/deals.csv: formd_12m (idea)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| bulk_index | https://www.sec.gov/Archives/edgar/full-index/{YYYY}/QTR{n}/form.idx  (+ /Archives/edgar/data/<cik>/<accession>.txt - XML Form D) | a User-Agent with a contact is mandatory (SEC rule), <= 10 requests/s | $0 | the index is 42 MB per quarter; 2026-Q3: 9,063 Form D + 4,996 D/A; the index holds only the issuer name, CIK, date -> to get the amount and industry, every XML must be downloaded | 200 2026-09-20 - index open from the probing machine |
| fulltext_api | https://efts.sec.gov/LatestSearch/?q=<phrase>&forms=D&startdt=... | a User-Agent with a contact | $0 | full-text search by name and fields - the most convenient path, but | 403 2026-09-20 - Forbidden from the probing IP even with a correct UA (SEC geo filter) - retry from another network |

Traps:
- The issuer name is often a legal entity (Acme Holdings LLC), not the brand; matching to a niche works only through the name -> low recall
- Industry has 30 coarse classes; 'Other Technology' = all software. The signal is useful as a counter over competitor names from a niche passport, not as a niche discovery tool

Plan: If efts opens from another network, a stage could search Form D filings over 24 months for the competitors of each niche -> funded, amount. Otherwise skip

#### ✅ Y Combinator (yc-oss JSON) (`yc_oss`) - P2

https://yc-oss.github.io/api/ · geo global · role discovery, evaluation · freshness quarterly · stage groups s0, s5 · stage `s0_yc`

Signals:
- YC companies by batch: industry, one_liner, team_size, tags - rising entities; yc_companies in deals.csv

Feeds: `data/out/universe.csv (source=yc:*)`; `data/out/deals.csv: yc_companies`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| json | https://yc-oss.github.io/api/batches/<batch>.json | none | $0 | updated with every batch | 200 2026-09-15 - 1,157 companies W25-F26 |

Traps:
- YC only; strong bias toward AI infrastructure in 2025-26

Plan: Add new batches as they come out

#### ✅ TinySeed (portfolio) (`tinyseed`) - P3

https://tinyseed.com/portfolio · geo global · role discovery, evaluation · freshness quarterly · stage groups s0, s5 · stage `s0_tinyseed`

Signals:
- B2B SaaS for small teams with revenue - the best prior for proven-fragmented; tinyseed in deals.csv

Feeds: `data/out/universe.csv (source=tinyseed)`; `data/out/deals.csv: tinyseed`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| manual | https://tinyseed.com/portfolio | none | $0 | 215 companies (2026-09-15); refresh twice a year; exported by hand to a CSV that the stage reads | 200 2026-09-15 - exported by hand |

Plan: Add analogues by hand: Calm Company Fund (/portfolio -> 404, the path changed), Indie.vc, Earnest

### community - Communities - buyer and builder voice (voice)

#### ✋ Indie Hackers (`indie_hackers`) - P3

https://www.indiehackers.com · geo global · role discovery, voice · freshness daily · stage groups s0, s5 · stage not implemented

Signals:
- products with confirmed revenue (Stripe-verified) -> proven-fragmented niches of small players
- 'how I got to $X MRR' posts - monetization model, channels, time to revenue
- interviews - what did not work

Feeds: `data/out/universe.csv (source=ih, proven)`; `data/out/deals.csv: ih_products (idea)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_spa | https://www.indiehackers.com/products?revenueVerification=stripe&sorting=highest-revenue | none | $0 | SPA: only 19 /product/* links in the HTML, revenue is rendered by JS; the API is closed; /product/<slug> -> 404 for some slugs | 200 2026-09-20 - 81 KB shell without data; /feed.xml is HTML, /rss -> 404 |
| browser | the same list through a headless browser (Playwright) or by hand: export the 'Products' table with the revenue filter | none | $0, ~30 min by hand per slice | a one-off slice of ~1,000 products with MRR | None 2026-09-20 - not tried |

Traps:
- Verified revenue is rare (~20% of products); the rest is self-reported
- Biased toward dev / SaaS tools for indies - the same niches as Product Hunt

Plan: One manual / headless slice of Stripe-verified products -> universe (proven); repeat quarterly

#### ✅ Hacker News (Algolia API) (`hacker_news`) - P1

https://news.ycombinator.com · geo global · role discovery, voice, trend · freshness realtime · stage groups s8 · stage `s8_hn_mentions`

Signals:
- Show HN by niche keywords over a period -> new products from technical people (rising, earlier than Product Hunt)
- Ask HN 'is there a tool for / how do you handle X' -> pain without a product (voice)
- dynamics of niche mentions per month (points, num_comments) -> interest of the technical audience
- 'Who is hiring?' / 'Who wants to be hired?' - monthly threads (see hn_who_is_hiring)

Feeds: `data/out/hn_niche.csv, data/out/hn_matches.csv`; `data/out/offsearch.csv: hn_posts_12m, hn_show_12m, hn_ask_12m, hn_trend (flags HN:up / HN:down / HN:asks)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://hn.algolia.com/api/v1/search?query=<phrase>&tags=story\|show_hn\|ask_hn&numericFilters=created_at_i>...&hitsPerPage=1000 | none | $0 | 10,000 requests/h, no key; full text over title / story_text / comment_text; filters by date and type; search_by_date for chronology | 200 2026-09-20 - JSON, works; 'Show HN invoicing' for 2026 has hits |
| api | https://hacker-news.firebaseio.com/v0/item/<id>.json | none | $0 | official API: comment tree by id; no search | 200 2026-09-20 - topstories.json open |

Traps:
- Algolia matches words loosely by default ('dog grooming' -> 341 stories, 3 relevant): use a quoted phrase, typoTolerance=false and restrictSearchableAttributes=title
- The audience is developers; B2C niches (gardeners, churches, tattoo) are barely represented -> NA, not 0
- Full text catches homonyms ('church' in a non-religious sense) - the same traps as in query generation; a stop-context list per niche is needed

Plan: Done (2026-11-17): s8_hn_mentions searches the Latin coverage phrases of each shortlisted niche as exact phrases in titles of Show HN + Ask HN posts (typoTolerance=false, restrictSearchableAttributes=title) and keeps titles that match the niche regex. Plain stories and post bodies were tried and dropped: about 9 in 10 hits were homonyms. Next: pain-bearing Ask HN threads into the s10 corpus

#### ✅ Reddit (Arctic Shift + subredditstats) (`reddit`) - P2

https://www.reddit.com · geo global · role voice, trend · freshness daily · stage groups s8, s10 · stage `s10_reddit_fetch`

Signals:
- s8: size and growth of native subreddits; s10: pains, products, 'from -> to', willingness to pay across thousands of labelled documents

Feeds: `data/out/reddit_niche.csv`; `data/out/reddit_voice*.csv|json`; `data/out/reddit_brands.csv`; `data/out/reddit_monthly.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=...&after=...&before=...&limit=100 | none | $0 | listing by dates; full text search returns 422; ~15% of connections drop on some home networks - use retries, or a stable server / proxy | 200 2026-09-17 - 632k posts + 463k comments from 114 subreddits |
| api | reddit.com/*.json, the official API | application request - the form is closed | $0 | 403 | 403 2026-09-17 - dead end |

Traps:
- Reddit is US / English; Russian-language voice: app reviews of the RU App Store and Google Play (s10_ru_reviews_*), Otvety Mail.ru planned (otvet_mail_ru); otzovik / VK / Telegram / 4PDA by hand

Plan: Add 'buyer' subreddits (r/smallbusiness, r/Entrepreneur, r/SaaS) to the markers of 'which tool do you use for X' - partly present in the reddit term list already

#### 🛠 Otvety Mail.ru (Q&A) (`otvet_mail_ru`) - P2

https://otvet.mail.ru · geo ru · role voice · freshness daily · stage groups s10 · stage not implemented

Signals:
- s10: Russian 'which app / program for X' questions and their answers - seeking, complaints, products named; mass B2C audience

Feeds: `planned: Russian Q&A documents for the S10 corpus`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://otvet.mail.ru/api/topic/question/<id> ; /api/topic/answers/<id> (the site's own JSON, used by its Nuxt front end) | none | $0 | unofficial, may change without notice | 200 2026-11-20 - question and answers as JSON without a key |
| api | https://otvet.mail.ru/api/topic/search?text=... | none | $0 | 20 recent posts sorted by date, barely related to the query - useless for finding questions | 200 2026-11-20 - 'programma dlya ucheta sklada' returned posts about the USA, Windows admin rights and cutlets |
| serp | DataForSEO Google SERP 'site:otvet.mail.ru <query>' (sources/dataforseo.serp), then the question JSON by id | DataForSEO login | a fraction of a cent per query | much of the archive is 2008-2015: filter by created_at | None 2026-11-20 - not tried |

Traps:
- Relaunched by VK in May 2025, 38.6 M monthly users (Mediascope, January 2025); a young mass audience - weak for B2B
- Yandex Q is read-only since June 2023: an archive, no fresh voice

Plan: Discovery through the SERP, questions and answers through the JSON API, then the S10 labelling (seeking / complaint / switching / price) as for Reddit

### crowdfunding - Crowdfunding - a pre-order as demand before the product (B2C hardware / consumer)

#### ✅ Kickstarter (Web Robots dumps) (`kickstarter`) - P2

https://www.kickstarter.com · geo global · role discovery, evaluation · freshness monthly · stage groups s0, s5 · stage `s0_kickstarter`

Signals:
- projects in Technology / Design / Games / Publishing: goal, pledged, number of backers, date, state - demand that has already been paid for
- share of successful projects and median pledged per subcategory -> 'where people pay in advance' (B2C hardware, board games, gadgets, accessories)
- repeat campaigns of one team - a live segment

Feeds: `data/out/universe.csv (source=kickstarter:<category>, proven: successful with >= 200 backers)`; `data/out/kickstarter_categories.csv, reports/S0-kickstarter.md`; `data/out/deals.csv: kickstarter_12m, kickstarter_success_12m, kickstarter_pledged_12m (passport, not scored)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| bulk_dump | https://webrobots.io/kickstarter-datasets/  -> https://s3.amazonaws.com/weruns/forfun/Kickstarter/Kickstarter_<date>.json.gz\|.zip | none | $0 | a full snapshot of all projects once a month (latest on 2026-09-10, zip 268 MB); fields: name, blurb, category, goal, pledged, backers_count, state, deadline, launched_at, creator | 200 2026-09-20 - HEAD 200, 268 MB; the S3 bucket listing is closed (403), direct links from the page are open |
| json | https://www.kickstarter.com/discover/advanced?category_id=16&sort=newest&format=json | none | $0 | Cloudflare from the probing IP | 403 2026-09-20 - 'Just a moment' - the live site is closed; the dumps are enough |

Traps:
- The crawl under-samples failed projects: in the 2026-11-16 dump 79% of finished projects are successful, against ~40% in Kickstarter's own statistics
- This is B2C hardware / games / design, not SaaS; empty for software niches - use only for niches with a physical product or to find an 'accessory -> companion app' pattern
- A dump is a snapshot, not a history: a trend is built from a series of dumps (Web Robots keeps them since 2014, so a retrospective exists)

Plan: Done (2026-11-17): s0_kickstarter takes one dump (2026-11-16: 107k records, 27k projects launched within 24 months) and compares launches by launch date, last 12 months vs the 12 before, instead of two dumps a year apart. The crawl under-samples failed projects (79% of finished ones are successful vs ~40% on Kickstarter): compare success rates between categories only

#### ⛔ Indiegogo (`indiegogo`) - none

https://www.indiegogo.com · geo global · role discovery · freshness daily · stage groups s0 · stage not implemented

Signals:
- same as Kickstarter, plus InDemand (post-campaign)

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.indiegogo.com/explore/all?... | none | $0 | Cloudflare | 403 2026-09-20 - 'Just a moment'; no open dumps |

Traps:
- Duplicates Kickstarter with lower-quality campaigns

Plan: Not worth implementing

#### ✋ Planeta.ru / Boomstarter (RU) (`ru_crowdfunding`) - none

https://planeta.ru · geo ru · role discovery · freshness daily · stage groups s0 · stage not implemented

Signals:
- Russian crowdfunding: mostly creative / social projects, technology is a handful

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://planeta.ru/search/projects?category=technology ; https://boomstarter.ru/projects/technology | none | $0 | Planeta - 307 redirect without a body; Boomstarter - 404 on the old path | 307 2026-09-20 - structure changed; not worth writing a parser - the volume of technology projects is small |

Traps:
- The signal for software niches is negligible

Plan: Not worth implementing

### hiring - Hiring - who hires for which tasks (a proxy for budget and growth)

#### ✅ HN 'Who is hiring?' (monthly threads) (`hn_who_is_hiring`) - P1

https://news.ycombinator.com/submitted?id=whoishiring · geo global · role evaluation, trend · freshness monthly · stage groups s8 · stage `s8_hn_hiring`

Signals:
- ~400 postings a month from funded startups: company, what it builds (1 line), roles, stack, remote / salary -> 'who hires for niche X' and how that changes over 36+ months
- 'Who wants to be hired?' (~580/month) - which technical people look for work in which domain (a weak but free proxy of talent supply)
- 'Freelancer? Seeking freelancer?' - demand for contractors by topic

Feeds: `data/raw/hn_hiring.csv`; `data/out/hn_hiring_niche.csv, data/out/hn_hiring_matches.csv`; `data/out/offsearch.csv: hn_hiring_12m, hn_hiring_prev12m (flag HN:hiring)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring  -> thread ids; then /search?tags=comment,story_<id>&hitsPerPage=1000 - all postings | none | $0 | 10,000 requests/h; full archive since 2011; a monthly thread takes 1-2 requests | 200 2026-09-20 - Sep-2026 hiring 402 comments, wants-to-be-hired 583; Aug 379 |

Traps:
- Postings are free text, a company describes itself in one line; matching to a niche needs the deal_keywords.yaml regexes + an LLM for disputed cases
- Biased toward dev infrastructure and AI; vertical SMB SaaS appears but rarely - with 0 matches the value is NA

Plan: Done (2026-11-17): s8_hn_hiring reads 36 monthly threads through /items/<id> (one request each, ~11,400 postings), matches postings to niches by the s5_deals regexes and counts 12 months vs the 12 before. Next: an LLM pass for disputed matches (a nonprofit that hires is not a donor-CRM vendor)

#### 🛠 Wellfound (AngelList Talent) (`wellfound`) - P2

https://wellfound.com · geo global · role evaluation, discovery · freshness daily · stage groups s8, s0 · stage not implemented

Signals:
- startup vacancies: company, size, stage, 'high concept' (1 line about the product), roles, salary ranges -> who actively grows for which task
- pages /startups/industry/<x> - company lists per industry with size and funding

Feeds: `data/out/offsearch.csv: wellfound_jobs (idea)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://wellfound.com/role/l/<role>/<location>  and  /jobs | none | $0 | Next.js SSR: an Apollo cache in the HTML (688 KB per role page, vacancy titles and companies inside the JSON); Turnstile exists but does not fire on the first page load | 200 2026-09-20 - /jobs 224 KB, /role/l/software-engineer/san-francisco 688 KB with data; /startups 324 KB |
| html | https://wellfound.com/company/<slug> | none | $0 | 403 (noindex, anti-bot) - company cards are closed | 403 2026-09-20 - blocked |

Traps:
- Keyword search for a niche in vacancies is unavailable without a login - only by role / location, then filter by the company text locally
- Funding / size data are self-reported by the companies; AngelList Venture (fund / syndicates) is a separate product, closed

Plan: Walk /role/l/<role>/<location> for 10 roles x 5 locations monthly -> JSON from the HTML -> a company table with high_concept; match to niches. Low priority: HN hiring gives the same more cheaply

#### 🛠 Remote OK (API) (`remoteok`) - P3

https://remoteok.com · geo global · role evaluation · freshness daily · stage groups s8 · stage not implemented

Signals:
- the 100 latest remote vacancies as JSON: company, position, tags, description, salary -> a quick 'who hires' slice without parsing

Feeds: `data/out/offsearch.csv: remoteok_jobs (idea, together with hn_hiring)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://remoteok.com/api  (condition: link back to the source) | none | $0 | only the 100 latest - history needs daily accumulation | 200 2026-09-20 - 622 KB JSON, 100 vacancies, fields present |

Traps:
- A small slice, remote only; the value is as a complement to HN hiring

Plan: A daily accumulator into a cache folder; match monthly

#### ⛔ YC Work at a Startup (`yc_jobs`) - none

https://www.workatastartup.com · geo global · role evaluation · freshness daily · stage groups s8 · stage not implemented

Signals:
- vacancies of YC companies by batch: what they build and whom they look for

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.workatastartup.com/companies \| /jobs | none | $0 | 406 without browser Accept headers; ycombinator.com/jobs is Inertia SSR (371 KB) with a list | 406 2026-09-20 - ycombinator.com/jobs -> 200 SSR, 20 vacancy links |

Traps:
- Duplicates yc_oss + HN hiring

Plan: Not worth implementing

#### ✅ hh.ru (API, needs a Russian IP) (`hh_ru`) - P2

https://hh.ru · geo ru · role evaluation · freshness daily · stage groups s8 · stage `s8_hh`

Signals:
- vacancies by niche keywords in Russia: count, employers, salaries -> Russian demand for competencies / tools (s8, Russian B2B module)

Feeds: `data/out/hh_niche.csv`; `data/out/hh_vacancies.csv`; `data/out/ru_b2b_*.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.hh.ru/vacancies?text=... | none | $0 | forbidden from foreign IPs; works from a Russian IP (use the ru proxy option of the HTTP helper) | 200 2026-09-17 - through a Russian-IP route |

Plan: -

### vc_portfolio - Fund portfolios - a map of what is already funded (rising; a red ocean a year later)

#### 🛠 Portfolios of top funds (a16z, Sequoia, Accel, Index, NEA, Greylock, ...) (`vc_portfolios`) - P2

https://a16z.com/portfolio/ · geo global · role discovery, evaluation · freshness monthly · stage groups s0, s6 · stage not implemented

Signals:
- a map of 'where big money has already gone' per category - a niche with 3+ portfolio companies of top funds = a future red ocean (veto / downgrade); with 0 - either empty, or too small for VC
- one-liner descriptions of portfolio companies -> entities for the universe (rising), comparison with YC / Product Hunt
- dynamics: new logos over 12 months per category (needs snapshots)

Feeds: `data/out/universe.csv (source=vc:<fund>, rising)`; `score: a VC:crowded flag (idea, as a veto flag, not a score component)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_json | https://a16z.com/portfolio/ | none | $0 | 3.6 MB; an Alpine component wr25Portfolio with JSON inside the HTML - 877 unique titles, categories | 200 2026-09-20 - parsed with regex / JSON |
| html_ssr | https://www.indexventures.com/companies (330 links) · https://www.nea.com/portfolio (918) · https://greylock.com/portfolio/ (161) · https://www.accel.com/companies (152) | none | $0 | links to company cards in the HTML; the description is on the card (a second request) or in meta | 200 2026-09-20 - 4 funds with full lists in SSR |
| html_js | Sequoia (Framer, 21 h2 in the HTML), Lightspeed, Founders Fund, General Catalyst / Khosla / Craft / Antler (Webflow w-dyn-item, the collection is loaded by JS), Techstars, Insight | none | $0 | needs a headless browser or a search for a JSON endpoint on the site (Webflow CMS serves collections via /.../cms) - 20-40 min per fund | 200 2026-09-20 - HTML without the list |
| html | Bessemer /companies (500), Kleiner /companies/ (404), Point Nine /portfolio (404), Initialized /portfolio (404), Calm Fund /portfolio (404) | none | $0 | paths changed - find the current ones | 404 2026-09-20 - re-check the URLs |

Traps:
- A fund portfolio is its thesis from 2-8 years ago, not a fresh signal; freshness comes only from the delta between snapshots
- For niches worth '$5-10M' the presence of a top VC is more of a veto (a capitalised competitor) than a plus; evaluate as a flag, not a score
- Bessemer 'State of the Cloud', a16z market maps, Sequoia Arc - read by hand twice a year, these are maps, not data

Plan: A stage for the 5 SSR funds (a16z JSON, Index, NEA, Greylock, Accel) -> a CSV (fund, name, one_liner, category, url); a snapshot every quarter; a VC:crowded flag at >= 3 portfolio companies in a niche goes into the passport

### patents - Patents - R&D activity and abandoned directions (feasibility / IP risk)

#### 🛠 Google Patents (XHR) (`google_patents`) - P2

https://patents.google.com · geo global · role evaluation, trend · freshness weekly · stage groups s5, s6 · stage not implemented

Signals:
- number of applications / patents for a niche phrase over a period (priority_date) -> R&D activity: growth = someone is investing, zero = either not patentable (most SMB SaaS) or empty
- assignee -> big corporations in the niche (Google / Microsoft / Salesforce patent 'scheduling') = platform risk
- families (family_metadata) and countries - where they protect

Feeds: `data/out/supply_deep.csv: patents_24m, patents_top_assignee (idea); an IP:bigtech flag`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| xhr_json | https://patents.google.com/xhr/query?url=q%3D<phrase>%26after%3Dpriority%3A20240101%26num%3D100&exp= | none | $0 | JSON: total_num_results, per result title, snippet, priority / filing / publication_date, assignee, inventor, publication_number, family_metadata; ~1 s/request, pagination page=N | 200 2026-09-20 - 'appointment scheduling' after 2024 -> 286 results; status=EXPIRED in the XHR -> 500 (a status filter exists only in the UI / BigQuery) |
| bigquery | bigquery-public-data.patents.publications (+ google_patents_research) | Google Cloud account; 1 TB/month free | $0 | full texts, CPC, statuses, citations; SQL - the only large-scale path for 'abandoned' (expired / withdrawn) | None 2026-09-20 - not tried |

Traps:
- For software a patent is not a product: patent activity is a signal for hardware / AI models / devices; for SMB SaaS it is almost always 0 -> NA
- 'Abandoned patents' as a source of ideas is a myth for software: expired patents from 2005 describe things that are obvious today; useful only in hardware (Kickstarter-type niches) and as a check that the core of a product is not patented by big tech

Plan: For shortlisted niches: total over 24 months and over the 24 months before (YoY), top-3 assignees; an IP:bigtech flag if the top 3 include Google / Apple / Microsoft / Amazon / Meta / Salesforce / Intuit. On demand only - not part of a mandatory run

#### ⛔ USPTO PatentsView API (`patentsview`) - P3

https://patentsview.org · geo global · role evaluation · freshness quarterly · stage groups s5 · stage not implemented

Signals:
- structured US patents: CPC, assignee, citations; more convenient than Google Patents for aggregates by class

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://search.patentsview.org/api/v1/patent/?q=... | a free API key (a form on patentsview.org) | $0 | 45 requests/min | 000 2026-09-20 - connection not established from the probing machine (geo / network) - retry from another network, get a key |

Traps:
- US only and granted patents only; applications are separate

Plan: Not needed if the Google Patents XHR is enough

#### ⛔ USPTO Open Data / Bulk (PEDS, maintenance fees) (`uspto_bulk`) - P3

https://data.uspto.gov · geo global · role evaluation · freshness weekly · stage groups s5 · stage not implemented

Signals:
- application statuses (Abandoned) and fee non-payment events (expired) - the only honest source of 'abandoned' US patents

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.uspto.gov/api/v1/patent/applications/search | a free key (Open Data Portal) | $0 | 401 without a key | 401 2026-09-20 - Unauthorized - a key is required |
| bulk | https://data.uspto.gov/apis/bulk-data/products  (Patent Maintenance Fee Events, PEDS) | none | $0 | gigabyte-sized dumps | 200 2026-09-20 - catalogue open (SPA) |

Traps:
- See google_patents: not needed for software

Plan: Only if a hardware niche appears (Kickstarter-type) - then BigQuery is simpler

#### ⛔ Lens.org (`lens_org`) - none

https://www.lens.org · geo global · role evaluation · freshness weekly · stage groups s5 · stage not implemented

Signals:
- patents + scientific papers in one search; a free API for non-commercial use

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.lens.org/patent/search | a token (free for non-commercial use, by request) | $0 | 401 without a token | 401 2026-09-20 - Missing Authorization Header |

Traps:
- Duplicates Google Patents

Plan: Not worth implementing

#### ⛔ EPO OPS (Espacenet) (`epo_ops`) - none

https://www.epo.org/en/searching-for-patents/data/web-services/ops · geo global · role evaluation · freshness weekly · stage groups s5 · stage not implemented

Signals:
- European and worldwide patent families; legal status (INPADOC) - including 'lapsed' per country

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://ops.epo.org/3.2/rest-services/published-data/search?q=... | registration, an OAuth key; 4 GB/week free | $0 | 403 fair-use without a key | 403 2026-09-20 - violation of Fair Use policy |

Traps:
- Duplicates Google Patents for this purpose

Plan: Not worth implementing

#### ✋ FIPS / Rospatent / Yandex.Patents (RU) (`fips_rospatent`) - P3

https://new.fips.ru/registers-web/ · geo ru · role evaluation · freshness weekly · stage groups s5 · stage not implemented

Signals:
- Russian patents and computer programs (the software register!) - registration of software at FIPS by title / owner: who registers software in a niche (for the Russian B2B branch; partly duplicates the Ministry of Digital Development software register)
- status 'ceased to be in force' - abandoned Russian patents

Feeds: `data/out/ru_b2b_*.csv: fips_progs (idea)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_form | https://www.fips.ru/registers-web/action?acName=clickRegister&regName=RUPAT \| EVM | none | $0 | HTML forms with a session, search by number / date; full text only via the paid PatSearch | 200 2026-09-20 - registers open, but they are forms - a parser is 1-2 days of work |
| api | https://searchplatform.rospatent.gov.ru/patsearch/v0.2/search | a JWT token by request | $0 | 401 without a token | 401 2026-09-20 - Authorization error |
| html | https://yandex.ru/patents?text=... | none | $0 | JS rendering, captcha on frequent requests | 200 2026-09-20 - 584 KB HTML without results in the markup |

Traps:
- The FIPS software register is an interesting Russian signal of 'who files software', but the Ministry of Digital Development register (see ru_reestr) covers the same for accredited vendors

Plan: By hand for 3-5 chosen Russian niches: the number of software registrations by keyword over the last 2-3 years

### m_and_a - Business sales - deals, multiples, real revenue of small players (proven, transactions)

#### ✅ Flippa (SaaS listings) (`flippa`) - P2

https://flippa.com · geo global · role discovery, evaluation · freshness daily · stage groups s0, s5 · stage `s0_flippa`

Signals:
- SaaS for sale with revenue / profit / price -> flippa_listings, flippa_with_revenue, max / median MRR per niche

Feeds: `data/out/universe.csv (source=flippa, transactions)`; `data/out/deals.csv: flippa_*`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://flippa.com/search?filter[property_type]=saas&page[number]=N | none | $0 | SSR JSON in the HTML, 15 pages (382 listings on 2026-09-15) | 200 2026-09-15 - works |

Traps:
- The low segment (MRR $100-5k), many 'built in a month, selling'; revenue is self-reported

Plan: Add the filters property_type=app|ecommerce for B2C niches; a snapshot every month for the listings trend

#### 🛠 Empire Flippers (API) (`empire_flippers`) - P1

https://empireflippers.com/marketplace/ · geo global · role discovery, evaluation · freshness daily · stage groups s0, s5, s6 · stage not implemented

Signals:
- 2,878 listings (including sold) with a verified P&L: average_monthly_net_profit, revenue, listing_price, listing_multiple, monetizations (SaaS / Amazon FBA / eCommerce / Content / Apps), days_on_marketplace, net_profit_trend, risks / opportunities as text
- multiple and 'days on market' per monetization type -> liquidity and exit price (the revenue ceiling)
- listing_status For Sale / Sold / Under Offer -> deal speed per niche

Feeds: `data/out/universe.csv (source=ef, transactions)`; `data/out/deals.csv: ef_listings, ef_median_profit, ef_multiple (idea)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.empireflippers.com/api/v1/listings/list?limit=100&page=N | none | $0 | public JSON without a key; 2,878 listings = 29 pages of 100; the monetizations filter did not work via the query (check the syntax in the docs) - filter locally | 200 2026-09-20 - JSON, pagination.count=2878, P&L fields present; niche / industry are null (the niche is in public_title: '...in the Kitchenware Niche') |

Traps:
- EF verifies the numbers - the best free source of real profit of small businesses; but SaaS is a minority (most are Amazon FBA / content / e-commerce)
- The niche is only in the title as text; match with the deal_keywords.yaml regexes over public_title + summary

Plan: 29 requests -> a CSV of listings; in the deals stage count ef_listings, ef_sold_12m, ef_median_profit, ef_multiple per niche; in the ceiling stage the median SaaS multiple is an anchor for the exit price

#### 🛠 Quiet Light Brokerage (`quiet_light`) - P2

https://quietlight.com/listings/ · geo global · role evaluation · freshness weekly · stage groups s5, s6 · stage not implemented

Signals:
- the upper segment ($500k-$20M): SaaS / e-commerce / content with SDE, price and multiple - where exits >= $1M really happen (ceiling)

Feeds: `data/out/deals.csv: ql_listings (idea)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://quietlight.com/listings/  (+ /listings/<id>/) | none | $0 | 1.2 MB SSR, 81 listings per page with title, price, SDE, type | 200 2026-09-20 - open, parseable |

Traps:
- Small volume (tens a month); the value is calibrating the ceiling: 'what a SaaS with $X profit sells for'

Plan: The same fetcher as Empire Flippers: page -> CSV; multiples by type feed the ceiling stage

#### ✋ Acquire.com (MicroAcquire) (`acquire_com`) - P3

https://acquire.com · geo global · role discovery, evaluation · freshness daily · stage groups s0, s5 · stage not implemented

Signals:
- the largest flow of SaaS startups for sale ($10k-$5M ARR): MRR, ARR, multiple, TTM profit, tech stack, number of customers

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://acquire.com/startups/ (no public list) ; app.acquire.com/api - not public | a buyer account (free, but with verification); listings are visible after login | $0 | SPA + login; 404 on direct paths | 404 2026-09-20 - same as on 2026-09-15 - only by hand from under an account |

Traps:
- The best source of SaaS deals, but only by hand: export the list by keyword from under a login, ~20 min per niche

Plan: By hand for the top-5 niches when estimating the ceiling: number of listings by keyword, median ARR and multiple -> into the passport

#### ✋ FE International / Microns / Tiny Acquisitions / SideProjectors (`fe_microns_tiny`) - P3

https://www.microns.io · geo global · role discovery · freshness daily · stage groups s0 · stage not implemented

Signals:
- micro-SaaS and side projects for sale ($1k-$100k): the fact that small products exit; FE is the upper segment

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.microns.io/ (Webflow, 86 w-dyn-item) · https://feinternational.com/buy-a-website/ (Webflow, 12) · https://www.sideprojectors.com (Laravel SPA) · https://www.tinyacquisitions.com | none | $0 | Microns / FE - Webflow collections in the HTML (parseable); SideProjectors - an API behind CSRF; Tiny Acquisitions - connection not established | 200 2026-09-20 - Microns 121 KB and FE 139 KB open; SideProjectors 59 KB shell; TinyAcq - 000 |

Traps:
- Small volume and low tickets; the signal is a yes / no on 'are there any exits in the niche at all'

Plan: Microns could be added to the Empire Flippers fetcher as a third source (Webflow w-dyn-item -> name, price, MRR); the others are not worth doing

#### ⛔ BizBuySell / BusinessesForSale.com (`bizbuysell`) - P3

https://www.bizbuysell.com · geo global · role discovery, evaluation · freshness daily · stage groups s6 · stage not implemented

Signals:
- 60k+ offline US businesses for sale by category (auto repair, salons, cleaning, vet clinics...) with cash flow and price -> size and economics of the buyer segment for vertical SMB SaaS (who the customer is and how much they earn)
- 'a bird in the hand': a ready business with a customer base on which you can put your own software

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.bizbuysell.com/<category>-businesses-for-sale/ | none | $0 | Akamai 'Access Denied' from the probing IP; businessesforsale.com - Cloudflare | 403 2026-09-20 - both closed; retry from another network, otherwise by hand |

Traps:
- This is not a source of software niches but a source of customer economics: the median cash flow of an auto shop / salon is the ceiling of a SaaS ticket. Valuable for the ceiling estimate in vertical niches, 10 min by hand per niche

Plan: By hand for vertical SMB niches: number of listings, median cash flow and price per category -> into the ceiling assumptions

#### ⛔ RU 'ready business': Avito / Biboss / Altera Invest / business-asset (`ru_business_sale`) - P3

https://www.avito.ru/rossiya/gotoviy_biznes · geo ru · role discovery, evaluation · freshness daily · stage groups s6 · stage not implemented

Signals:
- the Russian analogue of BizBuySell: ready businesses by industry with revenue / profit / price -> economics of the Russian customer for the Russian B2B branch (auto repair, utilities contractors, salons, clinics...)
- IT businesses for sale (SaaS, apps, Telegram channels) - small Russian exits

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.avito.ru/rossiya/gotoviy_biznes/prodazha_biznesa/it-... | none | $0 | 429 (anti-bot) on curl; open in a browser; there is an unofficial m.avito.ru/api with an application key | 429 2026-09-20 - blocked for curl |
| html | https://www.biboss.ru (000) · https://alterainvest.ru (404 on the old path) · https://business-asset.com/ru/ (a noRobot page) | none | $0 | all three - anti-bot or changed paths | 404 2026-09-20 - by hand |

Traps:
- Same meaning as BizBuySell - customer economics, not software niches; by hand for 3-5 Russian niches is enough

Plan: By hand: Avito in a browser - number of listings and median profit per customer category

### store - App and plugin stores - supply and concentration (proven)

#### ✅ App Store (iTunes Search / RSS / pages) (`appstore`) - P2

https://apps.apple.com · geo both · role discovery, evaluation, trend, voice · freshness daily · stage groups s0, s5, s8, s9, s10 · stage `s0_appstore_top`, `s5_appstore`, `s5_appstore_metrics`, `s5_pricing_b2c`, `s8_appstore_velocity`, `s9_snapshot`, `s9_entrants`, `s10_ru_reviews_fetch`

Signals:
- top-grossing by genre (s0); number of apps, ratings, top-1 concentration, IAP prices (s5); rating accumulation speed (s8); snapshots (s9); survival of newcomers; s10: Russian reviews of the leading apps - unmet needs, quality complaints, switching

Feeds: `data/out/appstore_*.csv`; `data/out/pricing_b2c*.csv`; `data/out/appstore_velocity.csv`; `data/out/entrant_survival.csv`; `data/out/ru_reviews_*.csv|jsonl|json`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://itunes.apple.com/search?term=...&entity=software&country=us\|ru ; /lookup?id=... ; RSS top-grossing | none | $0 | ~20 requests/min; relevance - position <= 15 + config/appstore_relevance.yaml | 200 2026-09-16 - 5,542 apps in the snapshot |
| api | https://itunes.apple.com/ru/rss/customerreviews/page=N/id=<trackId>/sortby=mostrecent/json | none | $0 | 50 newest reviews a page, pages 1-10 (page 11 -> 400): at most 500 per app; an app without reviews has no `entry` | 200 2026-11-20 - 50 Russian reviews per page with rating, version, date |

Traps:
- Reviews: at most the 500 newest per app, so for big apps the window is days or weeks; written reviews lean negative - compare niches with each other, not with a fixed threshold

Plan: -

#### ✅ Google Play (google-play-scraper) (`google_play`) - P2

https://play.google.com · geo both · role discovery, evaluation, trend, voice · freshness daily · stage groups s0, s5, s8, s9, s10 · stage `s0_gplay_top`, `s8_gplay_search`, `s8_gplay_filter`, `s8_gplay_details`, `s8_gplay_metrics`, `s9_gplay_refresh`, `s10_ru_reviews_fetch`

Signals:
- US / RU top charts (s0); installs, ratings, leader <= 50% - the 'second platform' rule (s5 / s8); snapshots (s9); s10: Russian reviews of the leading apps

Feeds: `data/out/gplay_*.csv`; `data/out/offsearch.csv`; `data/out/ru_reviews_*.csv|jsonl|json`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| scraper | npm google-play-scraper (search, app, list) | none | $0 | ~30 min for a full refresh of 2,392 apps | 200 2026-09-16 - works |
| scraper | npm google-play-scraper reviews({appId, lang: 'ru', country: 'ru', sort: NEWEST, num}) | none | $0 | ~1 app/s with a pause; node helper gplay_reviews.mjs | 200 2026-11-20 - 100 of 100 requested Russian reviews returned |

Traps:
- Reviews: written reviews lean negative - compare niches with each other, not with a fixed threshold

Plan: -

#### ✅ Shopify App Store (`shopify_app_store`) - P2

https://apps.shopify.com · geo global · role discovery, evaluation · freshness daily · stage groups s0, s5 · stage `s0_shopify`, `s5_shopify_metrics`

Signals:
- subcategories, apps, reviews -> concentration for Shopify niches (rule: >= 20 apps with >= 100 reviews, leader <= 25%)

Feeds: `data/out/shopify_metrics.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://apps.shopify.com/categories/<slug> | none | $0 | ?page=N does not paginate - the first ~24 apps of a category + subcategories | 200 2026-09-16 - works |

Plan: -

#### ✅ WordPress.org plugins (`wordpress_org`) - P3

https://wordpress.org/plugins/ · geo global · role discovery · freshness daily · stage groups s0 · stage `s0_wordpress`

Signals:
- plugins by tag: active installs, reviews -> entities and concentration

Feeds: `data/out/universe.csv (source=wordpress)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request[tag]=... | none | $0 | open JSON | 200 2026-09-16 - works |

Plan: -

#### ✅ Capterra / GetApp (Gartner Digital Markets) (`capterra_getapp`) - P2

https://www.capterra.com · geo global · role evaluation · freshness weekly · stage groups s5 · stage `s5_capterra`, `s5_pricing_b2b`

Signals:
- category: number of products (numberOfItems), reviews -> B2B concentration (s5); GetApp cards - prices (s5 B2B pricing)

Feeds: `data/out/capterra_*.csv`; `data/out/pricing_b2b*.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://www.capterra.com/<category>/?page=N ; https://www.getapp.com/<cat>/<product>/ | none | $0 | categories are open, Capterra cards are closed -> GetApp | 200 2026-09-15 - works |

Traps:
- A Capterra category is a weak proxy for new niches (NA:proxy)

Plan: -

#### ⛔ G2 (`g2`) - none

https://www.g2.com · geo global · role evaluation · freshness weekly · stage groups s0 · stage not implemented

Signals:
- category taxonomy (2,245 entries in the universe) - used; products / reviews - unavailable

Feeds: `data/out/universe.csv (source=g2:category)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.g2.com/categories/<slug> | none | $0 | 403 both via curl and via a page-fetch tool; the category list was taken once by hand | 403 2026-09-15 - closed; Capterra is the replacement |

Plan: Not worth implementing

### search - Search demand - volumes, CPC, trend

#### ✅ DataForSEO (Google Ads search_volume) (`dataforseo`) - P1

https://dataforseo.com · geo global · role evaluation, trend · freshness monthly · stage groups s3, s4 · stage `s3_dataforseo`

Signals:
- volume, CPC, competition_index, 48 months of history per keyword - the core of s3

Feeds: `data/out/dfs_*.csv`; `data/out/metrics_quick.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | google_ads/search_volume/live | DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD | $0.09/call up to 1,000 keywords | a positive balance is required | 200 2026-09-16 - works with a positive balance |

Traps:
- Google Ads does not target Russia; a hump in 'X software' in 2024 and an acceleration of 'X app' in 2025-26 distort year-over-year comparisons (see the base-year setting of the metrics stage)

Plan: -

#### ✅ Yandex Wordstat API v2 (`wordstat`) - P1

https://wordstat.yandex.ru · geo ru · role evaluation, trend · freshness monthly · stage groups s2, s3, s4 · stage `s2_wordstat`, `s4_wordstat_dynamics`, `ru_wordstat`

Signals:
- totalCount, 50 nested phrases, dynamics, regions - Russian demand (s2 / s3 / s4, Russian B2B module)

Feeds: `data/out/wordstat_ru.csv`; `data/out/wordstat_dynamics.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | api.wordstat.yandex.net/v2 | YANDEX_API_KEY | $0 | 100 requests/h; sometimes 499 'cancelled' - retry in an hour | 200 2026-09-16 - 679/679 phrases |

Plan: -

#### ✅ Google Trends (trendspy) + YouTube (gprop=youtube) (`google_trends`) - P2

https://trends.google.com · geo global · role trend · freshness weekly · stage groups s4, s8 · stage `s4_trends`, `s8_youtube_trends`

Signals:
- direction over several years via anchors and brands (s4); YouTube interest per topic (s8)

Feeds: `data/out/trends_deep.csv`; `data/out/youtube_trends.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| scraper | trendspy (unofficial) | none | $0 | throttling; narrow B2B anchors -> index < 5 = NA | 200 2026-09-17 - works with pauses |

Plan: -

#### ✅ Google / Yandex autocomplete (`suggest`) - P3

https://suggestqueries.google.com · geo both · role evaluation · freshness daily · stage groups s2 · stage `s2_suggest`

Signals:
- suggestions -> ambiguity, platform_share, query expansion (s2)

Feeds: `data/out/suggest_*.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | suggestqueries.google.com/complete/search?client=firefox&q=... ; suggest.yandex.ru/suggest-ff.cgi?part=... | none | $0 | no key | 200 2026-09-15 - works |

Plan: -

### ru_registry - Russian registries and open government data - Russian B2B branch

#### ✅ Register of Russian software (Ministry of Digital Development) (`reestr_mincifry`) - P2

https://reestr.digital.gov.ru · geo ru · role evaluation · freshness daily · stage groups s0 · stage `ru_reestr`

Signals:
- number of entries per software class (156 classes) and year -> Russian supply and its growth

Feeds: `data/out/ru_b2b_reestr.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://reestr.digital.gov.ru/reestr/?... | none | $0 | open | 200 2026-09-17 - works |

Plan: -

#### ✅ zakupki.gov.ru (Federal Laws 44-FZ / 223-FZ) (`zakupki`) - P2

https://zakupki.gov.ru · geo ru · role evaluation · freshness daily · stage groups s0 · stage `ru_zakupki`

Signals:
- number and sum of procurements by keyword -> public-sector demand for Russian B2B

Feeds: `data/out/ru_b2b_zakupki.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=... | none | $0 | open, with pauses | 200 2026-09-17 - works |

Plan: -

#### ✅ Bitrix24 Market (`bitrix24_market`) - P3

https://www.bitrix24.ru/apps/ · geo ru · role evaluation · freshness daily · stage groups s0 · stage `ru_bitrix`

Signals:
- apps per category, installs -> Russian supply in the Bitrix24 ecosystem

Feeds: `data/out/ru_b2b_bitrix.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.bitrix24.ru/apps/?category=... | none | $0 | open | 200 2026-09-17 - works |

Plan: -

#### ⛔ Startpack (`startpack`) - none

https://startpack.ru · geo ru · role evaluation · freshness weekly · stage groups s0 · stage not implemented

Signals:
- Russian SaaS catalogue by category - the Russian analogue of Capterra

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://startpack.ru/category/... | none | $0 | 403 | 403 2026-09-17 - closed |

Plan: Not worth implementing

