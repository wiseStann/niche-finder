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

Daily or realtime without keys: Hacker News (archive since 2007, so a series exists immediately), the Product Hunt Atom feed, Launching Next RSS, Remote OK (latest 100, needs daily accumulation), Empire Flippers (listing dates and days on marketplace give a series). Monthly snapshots that accumulate into a series: Kickstarter dumps (history since 2014), BetaList, Product Radar, VC portfolios. Quarterly: YC batches, NVCA. This complements the App Store and Google Play snapshot stages: next to "supply over time" you get "entries and exits over time".

## What was deliberately judged not worth doing

- Buying Crunchbase, Dealroom, PitchBook or Tracxn: "capital in a niche" works as a veto flag, which is free from VC portfolios plus YC.
- Headless-browser parsers for JavaScript-only sites (Sequoia, live Kickstarter, Indiegogo, Acquire, Indie Hackers) while server-rendered sources and dumps are enough.
- Searching patents for ideas in software.

## Probe journal (2026-09-20, curl, no keys, one network)

- Open (200, no key, parseable): Product Hunt leaderboard / feed / topics, Product Radar categories, BetaList home and topics, Launching Next RSS, HN Algolia and Firebase, Empire Flippers API, Quiet Light, Microns, FE International, Google Patents XHR, Web Robots Kickstarter dumps, Wellfound `/jobs`, `/role`, `/startups`, Remote OK API, a16z / Index / NEA / Greylock / Accel, Crunchbase News RSS, NVCA, SEC `form.idx`, USPTO bulk catalogue, FIPS registers (forms).
- Key needed (401): Product Hunt GraphQL (free), Crunchbase API (paid), USPTO Open Data Portal (free), Lens (free for non-commercial), Rospatent API (by request).
- Closed from the probing network (403, 429, 406, 000): Crunchbase site, Dealroom, PitchBook (including RSS), SEC full-text search (geo), Kickstarter live, Indiegogo, Wellfound company pages, Work at a Startup, BizBuySell, BusinessesForSale, Avito, Biboss, Tiny Acquisitions, PatentsView (connection), EPO OPS (fair use), Growjo, Tracxn.
- Changed paths (404 / 500): Bessemer, Kleiner, Point Nine, Initialized, Calm Fund, Altera Invest, Boomstarter, Planeta (307).

Re-checked 2026-11-17/20: the Product Hunt leaderboards and Flippa now answer with a Cloudflare challenge (403); Product Hunt moved to its GraphQL API with a token, Flippa was dropped. The Empire Flippers API is still open (2,871 listings).

The generated registry follows.

---

# Registry of idea sources (v2026-09-20)

Generated from [`idea-sources.yaml`](idea-sources.yaml) by `scripts/render_idea_sources.py`. Edit only the YAML.

**87 sources, 131 access methods:** ✅ in_pipeline - 46, 🛠 planned - 12, ✋ manual - 7, ⛔ blocked - 17, 💰 paid - 5.  
Priorities: P1 - 11, P2 - 31, P3 - 30, none - 15.

Legend. **Status:** ✅ a pipeline stage exists · 🛠 no stage yet (not implemented) · ✋ by hand / browser only · ⛔ closed from the probing network · 💰 paid only. **Probe:** the HTTP code of a keyless curl probe (date). **Role:** discovery = entities for the universe, evaluation = a metric for a niche, voice = buyer voice, trend = dynamics over time.

## Implementation queue (planned, by priority)

| P | Source | Group | Stage | Stage groups | What it would give |
|---|---|---|---|---|---|
| P2 | Wellfound (AngelList Talent) | hiring | not implemented | s8, s0 | Walk /role/l/<role>/<location> for 10 roles x 5 locations monthly -> JSON from the HTML -> a company table with high_concept; match to niches. Low priority: HN hiring gives the same more cheaply |
| P2 | Launching Next | launch | not implemented | s0 | Collect the RSS daily into a cache (accumulate), merge into the universe once a month; use as a third 'launch density' counter (PH + BetaList + LN) |
| P2 | Quiet Light Brokerage | m_and_a | not implemented | s5, s6 | The same fetcher as Empire Flippers: page -> CSV; multiples by type feed the ceiling stage |
| P2 | Google Patents (XHR) | patents | not implemented | s5, s6 | For shortlisted niches: total over 24 months and over the 24 months before (YoY), top-3 assignees; an IP:bigtech flag if the top 3 include Google / Apple / Microsoft / Amazon / Meta / Salesforce / Intuit. On demand only - not part of a mandatory run |
| P2 | Portfolios of top funds (a16z, Sequoia, Accel, Index, NEA, Greylock, ...) | vc_portfolio | not implemented | s0, s6 | A stage for the 5 SSR funds (a16z JSON, Index, NEA, Greylock, Accel) -> a CSV (fund, name, one_liner, category, url); a snapshot every quarter; a VC:crowded flag at >= 3 portfolio companies in a niche goes into the passport |
| P3 | Otvety Mail.ru (Q&A) | community | not implemented | s10 | Not worth a stage for now: Russian B2C voice is covered by app reviews (thousands per niche), and Otvety is nearly empty for B2B. Revisit only as a qualitative block (questions, recommended products) for B2C or info-product topics |
| P3 | vc.ru (Osnova) | community | not implemented | s10 | Not a buyer-voice source; maybe a supply signal (vendor content intensity, indie builders posting launches) |
| P3 | Pikabu | community | not implemented | s10 | Reuse the YouTube-comments classifier if Russian voice stays thin |
| P3 | Remote OK (API) | hiring | not implemented | s8 | A daily accumulator into a cache folder; match monthly |
| P3 | Etsy (digital downloads) | info_market | not implemented | s8 | Add an ETSY_API_KEY and extend info_paid |
| none | Gumroad (digital products) | info_market | not implemented | info | Not a stage: revisit only for an English info product, as supply count + ratings per keyword |
| none | Plati.market / Digiseller (digital goods) | info_market | not implemented | info | Not worth a stage |

## Summary table

| Source | Group | Geo | Role | Freshness | Best access | Probe | Status | P | Stage groups |
|---|---|---|---|---|---|---|---|---|---|
| **Product Hunt** (`product_hunt`) | launch | global | discovery, evaluation | daily | atom · none · $0 | 200 (2026-09-20) | ✅ in_pipeline | P2 | s0, s5 |
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
| **Otvety Mail.ru (Q&A)** (`otvet_mail_ru`) | community | ru | voice | daily | api · none · $0 | 200 (2026-11-20) | 🛠 planned | P3 | s10 |
| **X (Twitter) API v2** (`x_twitter`) | community | global | voice, trend | realtime | api · bearer token of an X developer app; prepaid credits in the Developer Console · $0.010 per request (Counts: All), $0.005 per request (Counts: Recent) | 401 (2026-11-21) | 💰 paid | none | s4, s10 |
| **Threads (Meta Threads API)** (`threads`) | community | both | voice | realtime | manual · a Threads account (Instagram login); in Russia only through a VPN · $0 | 200 (2026-11-21) | ✋ manual | P3 | s10 |
| **vc.ru (Osnova)** (`vc_ru`) | community | ru | voice | daily | api · none · $0 | 200 (2026-11-20) | 🛠 planned | P3 | s10 |
| **VK API (groups and walls)** (`vk_api`) | community | ru | voice, evaluation | daily | api · service key of a VK mini app (dev.vk.com, new panel; no business verification): wall.get, wall.search, wall.getComments, groups.getById (members_count), board.getTopics, newsfeed.search work; groups.search does not (error 15) · $0 | 200 (2026-11-23) | ✅ in_pipeline | P3 | s8 |
| **Telegram group chats (own session)** (`telegram_chats`) | community | ru | voice | daily | api · TG_API_ID / TG_API_HASH from my.telegram.org and a session file (`nf setup telegram`: QR login; login codes for new API applications often never arrive) · $0 | 200 (2026-11-23) | ✅ in_pipeline | P1 | s10 |
| **TikTok Creative Center** (`tiktok_creative_center`) | community | global | trend | daily | html · none · $0 | 200 (2026-11-21) | ⛔ blocked | P3 | s4 |
| **Pikabu** (`pikabu`) | community | ru | voice | daily | html · none · $0 | 200 (2026-11-21) | 🛠 planned | P3 | s10 |
| **YouTube comments (YouTube Data API v3)** (`youtube_comments`) | community | both | voice | daily | api · API key (YOUTUBE_API_KEY) in the X-Goog-Api-Key header · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | s10 |
| **Kickstarter (Web Robots dumps)** (`kickstarter`) | crowdfunding | global | discovery, evaluation | monthly | bulk_dump · none · $0 | 200 (2026-09-20) | ✅ in_pipeline | P2 | s0, s5 |
| **Indiegogo** (`indiegogo`) | crowdfunding | global | discovery | daily | html · none · $0 | 403 (2026-09-20) | ⛔ blocked | none | s0 |
| **Planeta.ru / Boomstarter (RU)** (`ru_crowdfunding`) | crowdfunding | ru | discovery | daily | html · none · $0 | 307 (2026-09-20) | ✋ manual | none | s0 |
| **HN 'Who is hiring?' (monthly threads)** (`hn_who_is_hiring`) | hiring | global | evaluation, trend | monthly | api · none · $0 | 200 (2026-09-20) | ✅ in_pipeline | P1 | s8 |
| **Wellfound (AngelList Talent)** (`wellfound`) | hiring | global | evaluation, discovery | daily | html_ssr · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s8, s0 |
| **Remote OK (API)** (`remoteok`) | hiring | global | evaluation | daily | api · none · $0 | 200 (2026-09-20) | 🛠 planned | P3 | s8 |
| **YC Work at a Startup** (`yc_jobs`) | hiring | global | evaluation | daily | html · none · $0 | 406 (2026-09-20) | ⛔ blocked | none | s8 |
| **hh.ru (API, needs a Russian IP)** (`hh_ru`) | hiring | ru | evaluation | daily | api · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s8 |
| **Upwork** (`upwork`) | hiring | global | evaluation | daily | html · none · $0 | 403 (2026-11-21) | ⛔ blocked | P3 | s8 |
| **Fiverr** (`fiverr`) | hiring | global | evaluation | daily | html · none · $0 | 403 (2026-11-21) | ⛔ blocked | P3 | s8 |
| **Kwork (buyer requests)** (`kwork`) | hiring | ru | evaluation | daily | html · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P3 | s8 |
| **FL.ru (projects)** (`fl_ru`) | hiring | ru | evaluation | daily | html · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P3 | s8 |
| **Portfolios of top funds (a16z, Sequoia, Accel, Index, NEA, Greylock, ...)** (`vc_portfolios`) | vc_portfolio | global | discovery, evaluation | monthly | html_json · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s0, s6 |
| **Google Patents (XHR)** (`google_patents`) | patents | global | evaluation, trend | weekly | xhr_json · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s5, s6 |
| **USPTO PatentsView API** (`patentsview`) | patents | global | evaluation | quarterly | api · a free API key (a form on patentsview.org) · $0 | 000 (2026-09-20) | ⛔ blocked | P3 | s5 |
| **USPTO Open Data / Bulk (PEDS, maintenance fees)** (`uspto_bulk`) | patents | global | evaluation | weekly | bulk · none · $0 | 200 (2026-09-20) | ⛔ blocked | P3 | s5 |
| **Lens.org** (`lens_org`) | patents | global | evaluation | weekly | api · a token (free for non-commercial use, by request) · $0 | 401 (2026-09-20) | ⛔ blocked | none | s5 |
| **EPO OPS (Espacenet)** (`epo_ops`) | patents | global | evaluation | weekly | api · registration, an OAuth key; 4 GB/week free · $0 | 403 (2026-09-20) | ⛔ blocked | none | s5 |
| **FIPS / Rospatent / Yandex.Patents (RU)** (`fips_rospatent`) | patents | ru | evaluation | weekly | html_form · none · $0 | 200 (2026-09-20) | ✋ manual | P3 | s5 |
| **Flippa (SaaS listings)** (`flippa`) | m_and_a | global | discovery, evaluation | daily | html_ssr · none · $0 | 403 (2026-11-17) | ⛔ blocked | none | s0, s5 |
| **Empire Flippers (API)** (`empire_flippers`) | m_and_a | global | discovery, evaluation | daily | api · none · $0 | 200 (2026-11-20) | ✅ in_pipeline | P2 | s0, s5, s6 |
| **Quiet Light Brokerage** (`quiet_light`) | m_and_a | global | evaluation | weekly | html_ssr · none · $0 | 200 (2026-09-20) | 🛠 planned | P2 | s5, s6 |
| **Acquire.com (MicroAcquire)** (`acquire_com`) | m_and_a | global | discovery, evaluation | daily | html · a buyer account (free, but with verification); listings are visible after login · $0 | 404 (2026-09-20) | ✋ manual | P3 | s0, s5 |
| **FE International / Microns / Tiny Acquisitions / SideProjectors** (`fe_microns_tiny`) | m_and_a | global | discovery | daily | html · none · $0 | 200 (2026-09-20) | ✋ manual | P3 | s0 |
| **BizBuySell / BusinessesForSale.com** (`bizbuysell`) | m_and_a | global | discovery, evaluation | daily | html · none · $0 | 403 (2026-09-20) | ⛔ blocked | P3 | s6 |
| **RU 'ready business': Avito / Biboss / Altera Invest / business-asset** (`ru_business_sale`) | m_and_a | ru | discovery, evaluation | daily | html · none · $0 | 429 (2026-09-20) | ⛔ blocked | P3 | s6 |
| **TrustMRR** (`trustmrr`) | m_and_a | global | discovery, evaluation | daily | html_ssr · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | s0, s5 |
| **App Store (iTunes Search / RSS / pages)** (`appstore`) | store | both | discovery, evaluation, trend, voice | daily | api · none · $0 | 200 (2026-09-16) | ✅ in_pipeline | P2 | s0, s5, s8, s9, s10 |
| **Google Play (google-play-scraper)** (`google_play`) | store | both | discovery, evaluation, trend, voice | daily | scraper · none · $0 | 200 (2026-09-16) | ✅ in_pipeline | P2 | s0, s5, s8, s9, s10 |
| **Shopify App Store** (`shopify_app_store`) | store | global | discovery, evaluation | daily | html_ssr · none · $0 | 200 (2026-09-16) | ✅ in_pipeline | P2 | s0, s5 |
| **WordPress.org plugins** (`wordpress_org`) | store | global | discovery | daily | api · none · $0 | 200 (2026-09-16) | ✅ in_pipeline | P3 | s0 |
| **Capterra / GetApp (Gartner Digital Markets)** (`capterra_getapp`) | store | global | evaluation | weekly | html_ssr · none · $0 | 200 (2026-09-15) | ✅ in_pipeline | P2 | s5 |
| **G2** (`g2`) | store | global | evaluation | weekly | html · none · $0 | 403 (2026-09-15) | ⛔ blocked | none | s0 |
| **Chrome Web Store** (`chrome_web_store`) | store | global | evaluation | daily | api · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | s5 |
| **Atlassian Marketplace** (`atlassian_marketplace`) | store | global | evaluation | daily | api · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P3 | s5 |
| **DataForSEO (Google Ads search_volume)** (`dataforseo`) | search | global | evaluation, trend | monthly | api · DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD · $0.09/call up to 1,000 keywords | 200 (2026-11-23) | ✅ in_pipeline | P1 | s3, s4 |
| **Yandex Wordstat API v2** (`wordstat`) | search | ru | evaluation, trend | monthly | api · YANDEX_API_KEY · $0 | 200 (2026-09-16) | ✅ in_pipeline | P1 | s2, s3, s4 |
| **Google Trends (trendspy) + YouTube (gprop=youtube)** (`google_trends`) | search | global | trend | weekly | scraper · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s4, s8 |
| **Google / Yandex autocomplete** (`suggest`) | search | both | evaluation | daily | api · none · $0 | 200 (2026-09-15) | ✅ in_pipeline | P3 | s2 |
| **DataForSEO SERP + Labs keyword difficulty** (`dataforseo_serp`) | search | global | evaluation | daily | api · DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD · about $0.002 per SERP page; $0.01 per difficulty task + $0.0001 per keyword; the 74 shortlisted niches x 3 queries = about $0.48 | 200 (2026-11-23) | ✅ in_pipeline | P1 | s5 |
| **Register of Russian software (Ministry of Digital Development)** (`reestr_mincifry`) | ru_registry | ru | evaluation | daily | html_ssr · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s0 |
| **zakupki.gov.ru (Federal Laws 44-FZ / 223-FZ)** (`zakupki`) | ru_registry | ru | evaluation | daily | html · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P2 | s0 |
| **Bitrix24 Market** (`bitrix24_market`) | ru_registry | ru | evaluation | daily | html · none · $0 | 200 (2026-09-17) | ✅ in_pipeline | P3 | s0 |
| **Startpack** (`startpack`) | ru_registry | ru | voice, evaluation | daily | html · none · $0 | 200 (2026-11-20) | ✅ in_pipeline | P1 | s10 |
| **FNS register of small and medium businesses (open data dump)** (`fns_rmsp`) | ru_registry | ru | evaluation, trend | monthly | bulk · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P1 | s8, s6 |
| **FNS open data - income and expenses from financial statements** (`fns_revexp`) | ru_registry | ru | evaluation, trend | quarterly | bulk · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | s6 |
| **GIR BO - state resource of financial statements (bo.nalog.ru)** (`gir_bo`) | ru_registry | ru | evaluation | quarterly | html · none · $0 | 200 (2026-11-21) | ⛔ blocked | none | s6 |
| **MoySklad integrations catalog** (`moysklad_apps`) | ru_registry | ru | evaluation | monthly | html · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P3 | s5 |
| **amoCRM widgets (public showcase)** (`amocrm_extensions`) | ru_registry | ru | evaluation | static | html · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | none | s5 |
| **YCLIENTS marketplace** (`yclients_marketplace`) | ru_registry | ru | evaluation | monthly | api · partner token · $0 | 404 (2026-11-21) | ⛔ blocked | none | s5 |
| **US Census County Business Patterns + Nonemployer Statistics (bulk files)** (`us_census_cbp`) | gov_stats | global | evaluation | static | bulk · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P1 | s8, s6 |
| **Wayback Machine CDX API** (`wayback_machine`) | web | global | trend | daily | api · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | s9 |
| **Similarweb** (`similarweb`) | web | global | evaluation | monthly | api · paid API key (a Similarweb MCP connector is also offered in Claude Code, unauthorised here) · subscription | 401 (2026-11-21) | 💰 paid | P3 | s5 |
| **Meta Ad Library** (`meta_ad_library`) | ads | global | evaluation | daily | html · none · $0 | 403 (2026-11-21) | ✋ manual | P2 | s5 |
| **Google Ads Transparency Center (through DataForSEO)** (`google_ads_transparency`) | ads | global | evaluation | daily | html · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P1 | s5 |
| **Yandex Direct budget forecast (API v4 Live)** (`yandex_direct_forecast`) | ads | ru | evaluation | monthly | api · OAuth token (direct:api) of an app registered at oauth.yandex.ru ('for API access') and an approved access request in Direct Pro (Tools > API > My requests; up to 7 working days; the simplified Direct interface has no API settings, and switching to Direct Pro cannot be undone) · $0 | 200 (2026-11-23) | ✅ in_pipeline | P2 | s8 |
| **GitHub repository search** (`github_search`) | oss | global | evaluation | daily | api · optional GITHUB_TOKEN (Bearer) · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | s5 |
| **Federal Register (API)** (`federal_register`) | regulation | global | discovery | daily | api · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | s0 |
| **regulation.gov.ru (federal portal of draft regulations, open-data API)** (`regulation_gov_ru`) | regulation | ru | discovery | daily | api · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | s0 |
| **Etsy (digital downloads)** (`etsy`) | info_market | global | evaluation | daily | html · none · $0 | 403 (2026-11-21) | 🛠 planned | P3 | s8 |
| **Stepik (online courses)** (`stepik`) | info_market | ru | evaluation | daily | api · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | info |
| **Litres (ebook store)** (`litres`) | info_market | ru | evaluation | daily | api · none · $0 | 200 (2026-11-21) | ✅ in_pipeline | P2 | info |
| **Gumroad (digital products)** (`gumroad`) | info_market | global | evaluation | daily | api · none · $0 | 200 (2026-11-21) | 🛠 planned | none | info |
| **Plati.market / Digiseller (digital goods)** (`plati_market`) | info_market | ru | evaluation | daily | api · none · $0 | 200 (2026-11-21) | 🛠 planned | none | info |
| **Boosty (paid subscriptions of authors)** (`boosty`) | info_market | ru | evaluation | daily | api · none · $0 | 200 (2026-11-21) | ⛔ blocked | P3 | info |

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
| graphql | https://api.producthunt.com/v2/api/graphql  posts(featured: true, order: VOTES, postedAfter, postedBefore, first: 20) | developer token PRODUCTHUNT_TOKEN (free, register an application at producthunt.com/v2/oauth/applications) | $0 | query complexity <= 6,250 / 15 min; s0_producthunt waits for the reset on a rate-limit answer; the API terms restrict commercial use without permission from Product Hunt | 200 2026-11-20 - first run of s0_producthunt: 1,056 unique featured posts over 12 months (votes 213-1,496, all with topics); one rate-limit wait of ~8 min |
| html_ssr | https://www.producthunt.com/leaderboard/{monthly\|weekly}/{y}/{m}/all | none | $0 | Cloudflare JavaScript challenge; a browser User-Agent does not help, only a real browser would | 403 2026-11-17 - 'Just a moment...' on every page; 200 on 2026-09-20 |
| atom | https://www.producthunt.com/feed  (?category=<topic-slug>) | none | $0 | 50 latest posts; has title, tagline, published, link; no votes and no topics | 200 2026-09-20 - 44 KB, 50 entries, the freshest - a daily pulse |
| html_ssr | https://www.producthunt.com/topics/<slug> | none | $0 | topic page: number of followers and products of the topic - the size of the category audience | 200 2026-09-20 - 606 KB SSR |

Traps:
- Votes are bought or inflated; the signal is the number of launches and repeats, not votes
- Biased toward AI wrappers and dev tools; SMB B2B verticals are poorly represented
- Up to 4 topics per post, labelled by the authors - matching to a niche needs regexes (deal_keywords.yaml)
- Since November 2026 the web pages answer automated clients with a Cloudflare challenge (leaderboards checked; the feed and topic pages are likely the same): use the API

Plan: Done (2026-11-20): s0_producthunt reads the GraphQL API (top 60 featured posts a month and top 20 a week, 12 months). Next: a per-topic slice (posts(topic: ...)) for shortlisted niches

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
- Reddit is US / English; Russian-language voice: app reviews of the RU App Store and Google Play (s10_ru_reviews_*), Otvety Mail.ru probed and thin (otvet_mail_ru); otzovik / VK / Telegram / 4PDA by hand

Plan: Add 'buyer' subreddits (r/smallbusiness, r/Entrepreneur, r/SaaS) to the markers of 'which tool do you use for X' - partly present in the reddit term list already

#### 🛠 Otvety Mail.ru (Q&A) (`otvet_mail_ru`) - P3

https://otvet.mail.ru · geo ru · role voice · freshness daily · stage groups s10 · stage not implemented

Signals:
- s10: Russian 'which app / program for X' questions and their answers - seeking, complaints, products named; mass B2C audience

Feeds: `planned: Russian Q&A documents for the S10 corpus`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://otvet.mail.ru/api/topic/question/<id> ; /api/topic/answers/<id> (the site's own JSON, used by its Nuxt front end) | none | $0 | unofficial, may change without notice; old questions are served too (id 45.7 M = 2010, 230 M = 2022, 270 M = November 2026) | 200 2026-11-20 - question and answers (replies, best_replies) as JSON without a key |
| api | https://otvet.mail.ru/api/topic/search?text=...&sort=rel&limit=20&offset=N | none | $0 | without sort=rel the results are recent posts barely related to the query; with it the first 2 pages are relevant, deeper pages fall back to recent noise | 200 2026-11-20 - 'prilozhenie dlya ucheta raskhodov' -> 'Posovetuyte prilozhenie dlya vedeniya ucheta dokhodov i raskhodov' (2024) and similar |
| serp | DataForSEO Google SERP 'site:otvet.mail.ru <query>' | DataForSEO login | not needed: sort=rel finds the same questions for free | Google in DataForSEO rejects location_code 2643 (Russia) | 200 2026-11-20 - 40501 Invalid Field: 'location_code' |

Traps:
- Relaunched by VK in May 2025, 38.6 M monthly users (Mediascope, January 2025); a young mass audience
- Thin recent signal (probe 2026-11-20, 6 niches, RU category/problem queries, first 3 pages, query words in the title): 36-128 relevant questions per niche over all years, mostly 2008-2020; since 2023 - budgeting 20, calories 30, workout log 16, shift scheduling 10, landlords 3, auto repair 2
- Yandex Q is read-only since June 2023: an archive, no fresh voice

Plan: Not worth a stage for now: Russian B2C voice is covered by app reviews (thousands per niche), and Otvety is nearly empty for B2B. Revisit only as a qualitative block (questions, recommended products) for B2C or info-product topics

#### 💰 X (Twitter) API v2 (`x_twitter`) - none

https://x.com · geo global · role voice, trend · freshness realtime · stage groups s4, s10 · stage not implemented

Signals:
- Counts: All - the number of posts that match a query per day or hour over the full archive (since 2006) -> a possible third trend source next to Google Trends and YouTube (s4)
- 'is there a tool for / can anyone recommend X' posts -> buyer voice (s10)

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.x.com/2/tweets/counts/all?query=...&granularity=day (Counts: Recent = /counts/recent, last 7 days) | bearer token of an X developer app; prepaid credits in the Developer Console | $0.010 per request (Counts: All), $0.005 per request (Counts: Recent) | pay-per-use since 2026-02-06, no monthly fee; how many days one page of counts covers was not checked, so the cost of a multi-year series per query is unknown | 401 2026-11-21 - keyless: 'Unauthorized' |
| api | https://api.x.com/2/tweets/search/recent?query=... (search/all = full archive) | bearer token of an X developer app; prepaid credits | $0.005 per post read (a page of 100 posts = 100 reads) | 2 or 3 M post reads per monthly billing cycle (the official pages disagree) | 401 2026-11-21 - keyless: 'Unauthorized' |

Traps:
- Counts count every match of the query operators (exact phrase, lang:, -is:retweet); homonyms cannot be filtered out afterwards by a niche regex (on HN about 9 in 10 title hits were homonyms), and bots and news spikes add noise. Fit only for unambiguous phrases
- Buyer voice is weaker than Reddit, which is free and has long 'which tool do you use' threads; X posts are short, with much marketing. 500 posts per niche = about $2.5
- Blocked in Russia since March 2022; the Russian-speaking audience is small and leans to politics and crypto. No use for the RU market or the info cohort
- Prices from docs.x.com/x-api/getting-started/pricing as read on 2026-11-21; check the Developer Console before paying

Plan: Declined by the owner (2026-11-21). The only part worth a stage would be Counts: All as a third trend source for English software niches: a manual exp stage over the shortlist anchors, admitted to the score only if it agrees with Google Trends on the control niches

#### ✋ Threads (Meta Threads API) (`threads`) - P3

https://www.threads.com · geo both · role voice · freshness realtime · stage groups s10 · stage not implemented

Signals:
- keyword search of public posts (text, author, date) -> a sample of texts for buyer voice, or for info-topic supply: Russian-speaking authors who lead readers to Telegram

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://graph.threads.net/v1.0/keyword_search?q=...&search_type=TOP\|RECENT&search_mode=KEYWORD\|TAG&since=...&until=...&limit=100 | Threads user access token of a Meta app; public posts only after Meta app review grants threads_keyword_search, before that the search covers only the authenticated user's own posts | $0 | 2,200 queries per user per rolling 24 h, shared across apps (queries with no results do not count); limit <= 100 posts, no pagination cursor documented; since >= 2023-07-05; results carry no like, reply, repost or view counts (only has_replies) and there is no count or volume endpoint; an empty array for keywords Meta deems sensitive | 400 2026-11-21 - keyless: OAuthException 190 'Invalid OAuth 2.0 Access Token' |
| manual | https://www.threads.com/search?q=... | a Threads account (Instagram login); in Russia only through a VPN | $0 | by hand in a browser; reading results by script was not tried | 200 2026-11-21 - the search page loads (650 KB) |

Traps:
- The API cannot measure demand or reach: no engagement counts and no volume series, only a sample of texts
- Meta is designated extremist in Russia and Instagram is blocked there, so the Russian-speaking audience uses a VPN
- Facts from the Meta developer docs (keyword-search, retrieve-posts) as read on 2026-11-21

Plan: Not a stage for now. First search 5-10 topics from info_topics.yaml by hand in Threads; apply for threads_keyword_search only if that shows a signal YouTube (info_youtube) lacks

#### 🛠 vc.ru (Osnova) (`vc_ru`) - P3

https://vc.ru · geo ru · role voice · freshness daily · stage groups s10 · stage not implemented

Signals:
- entrepreneurs' posts and comments; in practice niche posts are mostly vendor SEO content - a supply signal, not buyer voice

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.vc.ru/v2.10/search/posts?q=... (anonymous; params sorting, dateFrom, editorial) | none | $0 | unofficial; loose matching ('total' in the thousands for a niche query) | 200 2026-11-20 - 'programma dlya fitnes kluba': 11 vendor posts from 2024 with 0 comments; long comment threads sit under general posts, not niche ones |

Traps:
- Niche-specific posts are vendor content marketing; buyer comments are few

Plan: Not a buyer-voice source; maybe a supply signal (vendor content intensity, indie builders posting launches)

#### ✅ VK API (groups and walls) (`vk_api`) - P3

https://dev.vk.com/ · geo ru · role voice, evaluation · freshness daily · stage groups s8 · stage `s8_vk_audience`

Signals:
- groups.search with members_count - size of communities per niche topic (a Russian analogue of subreddit sizes); wall posts and comments of open communities

Feeds: `data/out/vk_groups.csv, vk_audience.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.vk.com/method/<method>?v=5.199 (token in the POST body) | service key of a VK mini app (dev.vk.com, new panel; no business verification): wall.get, wall.search, wall.getComments, groups.getById (members_count), board.getTopics, newsfeed.search work; groups.search does not (error 15) | $0 | newsfeed.search with a service key sees only the ~60 newest posts, start_time / end_time windows return nothing, quotes do not make a phrase exact | 200 2026-11-23 - the service key reads whole community walls and comments |
| api | https://oauth.vk.com/authorize?client_id=<app>&scope=groups&response_type=token (implicit flow) -> groups.search | user token of the same mini app (scope groups; offline is an invalid scope for it, so the token lives about a day) | $0 | groups.search works; results are mostly single businesses' pages and personal blogs | 200 2026-11-23 - 'owners of auto services': 1,530 groups, nearly all single auto services; 'nail masters': 24,599 groups of single masters |

Traps:
- No small-business voice: the largest beauty communities (0.5-2.8 M members) are picture feeds that name YCLIENTS 0-1 times in their history; 'auto service business' finds vendor and franchise pages. In VK a business runs its own page for its clients; owners talk in Telegram (telegram_chats)
- Group names are noisy; member counts include bots

Plan: Done (2026-11-23): s8_vk_audience, an evidence block (members of the 10 largest LLM-checked communities) beside s8_subreddit_stats; not a voice source; a fresh user token for each discovery run

#### ✅ Telegram group chats (own session) (`telegram_chats`) - P1

https://core.telegram.org/api · geo ru · role voice · freshness daily · stage groups s10 · stage `s10_tg_fetch`

Signals:
- s10: messages in public group chats of a niche's users (owners, practitioners, users of its tools) that name tools: which app to use, switching, missing integrations, price - the Russian small-business voice that reviews and VK lack

Feeds: `data/out/tg_docs.jsonl, tg_chats.csv, tg_fetch.csv, tg_items.jsonl, tg_llm.csv, tg_themes.json, tg_voice.csv; reports/S10-telegram.md`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | MTProto through Telethon with the user's own session: contacts.search (public chats by keyword), channels.getFullChannel (a chat's description), messages.search inside a public chat | TG_API_ID / TG_API_HASH from my.telegram.org and a session file (`nf setup telegram`: QR login; login codes for new API applications often never arrive) | $0 | read-only, no chat joined; 1.5 s between live calls; FloodWait over 120 s stops live calls and a re-run resumes from the month cache; contacts.search returns only a handful of chats per phrase | 200 2026-11-23 - salon owners' chat 28.7 K members (DIKIDI vs YCLIENTS, Avito sync); auto service owners' chat 4 K (AvtoDiler, 1C, '5-bay shop software'); nail masters' chat 31 K ('a booking app other than YCLIENTS') |

Traps:
- The session file gives full access to the account: kept in the workspace, never copied
- Recall depends on the chat-title phrases; consumer niches seldom have chats of their own
- Vendor ads are common (96 of 248 labelled messages in the auto repair owners' chats on the trial): labelled `ad` and left out of the shares

Plan: Done (2026-11-23): s10_tg_fetch / s10_tg_classify / s10_tg_report; the labels and verdict rule of the YouTube comments; thresholds draft in config/tg_voice.yaml

#### ⛔ TikTok Creative Center (`tiktok_creative_center`) - P3

https://ads.tiktok.com/business/creativecenter/ · geo global · role trend · freshness daily · stage groups s4 · stage not implemented

Signals:
- trending hashtags, keyword insights and top ads - the short-video side the info cohort does not measure

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en | none | $0 | a 21 KB application shell; data comes from signed internal calls | 200 2026-11-21 - shell only |

Traps:
- -

Plan: By hand for shortlisted info topics

#### 🛠 Pikabu (`pikabu`) - P3

https://pikabu.ru · geo ru · role voice · freshness daily · stage groups s10 · stage not implemented

Signals:
- Russian posts and comments (the closest thing to Reddit in Russian): pains and recommendations in consumer niches

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://pikabu.ru/search?q=... | none | $0 | windows-1251 pages, server-rendered | 200 2026-11-21 - search works |

Traps:
- Entertainment-heavy: needs the same tiered sampling as Reddit

Plan: Reuse the YouTube-comments classifier if Russian voice stays thin

#### ✅ YouTube comments (YouTube Data API v3) (`youtube_comments`) - P2

https://www.youtube.com · geo both · role voice · freshness daily · stage groups s10 · stage `s10_yt_comments_fetch`, `s10_yt_comments_classify`, `s10_yt_comments_report`

Signals:
- s10: pains, unmet needs, price objections, 'which app?' requests and how-to questions in the comments under each niche's how-to and review videos; products named. Russian by default (the Russian B2C voice Reddit lacks), --lang en for US English

Feeds: `data/out/yt_comments_docs*.jsonl`; `data/out/yt_comments_videos*.csv`; `data/out/yt_comments_fetch*.csv`; `data/out/yt_comments_items*.jsonl`; `data/out/yt_comments_llm*.csv`; `data/out/yt_comments_voice*.csv`; `data/out/yt_comments_themes*.json`; `reports/S10-yt-comments*.md`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://www.googleapis.com/youtube/v3/search (q, relevanceLanguage, regionCode, publishedAfter) -> videos (statistics) -> commentThreads (part=snippet, order=relevance, textFormat=plainText, maxResults=100) | API key (YOUTUBE_API_KEY) in the X-Goog-Api-Key header | $0 | 10,000 units/day shared with info_youtube: search 100 units, videos 1 per 50 ids, commentThreads 1 per page of 100; a separate 'Search Queries per day' cap (about 100 calls) stops new searches while cached searches and comment pages still work; comments turned off -> 403 commentsDisabled | 200 2026-11-21 - 7 searches: 7 niches, 31 videos, 4,892 Russian comments for 768 units; the 8th search got 429 'Search Queries per day' (the day's searches were mostly spent by info_youtube) |

Traps:
- Commenters are viewers of popular videos, not a buyer sample: a review draws complaints, a tutorial draws questions, so the verdict compares niches with each other
- Comments under how-to videos mostly carry the voice of the task (training, cooking, budgeting), not of the products: a signal for info products more than for a software gap
- B2B buyers rarely comment on YouTube: B2B niches are often quiet
- LLM labels and themes are not hand-validated

Plan: All 47 niches fetched by 2026-11-23 (29,368 comments, 184 videos, 5,343 units on the second day; 4 niches without relevant videos). Draft verdicts: gap 10, mixed 10, quiet 9, pain 7, how-to 4, content 2, seeking 1. Calibration warning: 3 of 5 control niches came out gap (task manager, website builder, transcription), so the gap verdict does not separate crowded markets; fix the thresholds before trusting it

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

#### ⛔ Upwork (`upwork`) - P3

https://www.upwork.com · geo global · role evaluation · freshness daily · stage groups s8 · stage not implemented

Signals:
- job posts with budgets: people paying a person for the task

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.upwork.com/nx/search/jobs/?q=... | none | $0 | Cloudflare; the GraphQL API needs an approved application | 403 2026-11-21 - blocked |

Traps:
- -

Plan: -

#### ⛔ Fiverr (`fiverr`) - P3

https://www.fiverr.com · geo global · role evaluation · freshness daily · stage groups s8 · stage not implemented

Signals:
- gigs and their review counts per task - orders for a service a product could replace

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.fiverr.com/search/gigs?query=... | none | $0 | anti-bot challenge | 403 2026-11-21 - blocked |

Traps:
- -

Plan: -

#### ✅ Kwork (buyer requests) (`kwork`) - P3

https://kwork.ru/projects · geo ru · role evaluation · freshness daily · stage groups s8 · stage `s8_freelance`

Signals:
- s8: active buyer requests (title, text, budget RUB, accepted maximum, offers, buyer hire rate) matched to shortlisted niches; LLM label build (custom software for the niche's task) or service (the task done by hand) = paid demand

Feeds: `data/out/freelance.csv (kwork_*)`; `data/out/freelance_matches.csv`; `data/out/freelance_history.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://kwork.ru/projects?c=<subcategory> (page 1 of 54 subcategories; window.stateData JSON: wantsListData.wants, exchangeStats) | none | $0 | robots.txt disallows ?page= / &page= and /search: 12 newest requests per subcategory, ~3/4 of active requests per snapshot; requests stay open ~3 days, daily runs accumulate in the history; ?keyword= search is OR over words (whole words only) | 200 2026-11-21 - 331 active requests, 248 read; 30-day exchange stats 4,940 requests, 2,671 orders, 51.7M RUB |

Traps:
- A snapshot of open requests, not an archive: counts grow with the number of runs
- Small budgets (median 3,000 RUB); much of the board is lead generation and content work
- Coverage stems collide with common words in job posts: config/freelance.yaml match overrides plus the LLM check are needed

Plan: Done (2026-11-21): s8_freelance; LLM-labelled re-run: 58 of 142 keyword candidates are paid demand (build / service) in 13 niches

#### ✅ FL.ru (projects) (`fl_ru`) - P3

https://www.fl.ru/projects/ · geo ru · role evaluation · freshness daily · stage groups s8 · stage `s8_freelance`

Signals:
- s8: projects of the last ~2 months (title, cut text, budget, kind, responses) matched to shortlisted niches; build / service = paid demand

Feeds: `data/out/freelance.csv (fl_*)`; `data/out/freelance_matches.csv`; `data/out/freelance_history.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.fl.ru/projects/page-N/ (30 a page, ~56 pages = 2 months; ends with 404) | none | $0 | allowed by robots.txt; budget often 'by agreement'; ~40% of posts are vacancies (not counted) | 200 2026-11-21 - 56 pages, 1,656 projects 2026-09-21..2026-11-21; page-100 = 404 |
| html | https://www.fl.ru/search/projects/?q=<phrase> (window.searchResult JSON, whole archive since 2005, 1.39M projects, AND with word forms) | none | $0 | works, but robots.txt disallows /search/, */rss/* and /*?kind, so not used; /projects/?search= ignores the parameter | 200 2026-11-21 - one-word recipe query -> 1,352 projects; fields cost, currency, offers_count, published_at, kind_label |

Traps:
- List descriptions are cut; a post that describes the task in other words is missed

Plan: Done (2026-11-21): s8_freelance

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

#### ⛔ Flippa (SaaS listings) (`flippa`) - none

https://flippa.com · geo global · role discovery, evaluation · freshness daily · stage groups s0, s5 · stage not implemented

Signals:
- SaaS for sale with revenue / profit / price -> flippa_listings, flippa_with_revenue, max / median MRR per niche

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://flippa.com/search?filter[property_type]=saas&page[number]=N | none | $0 | Cloudflare JavaScript challenge; no official API | 403 2026-11-17 - 'Just a moment...'; 200 with SSR JSON (382 listings) on 2026-09-15 |

Traps:
- The low segment (MRR $100-5k), many 'built in a month, selling'; revenue is self-reported
- Was the 3x marketplace term of the deals score; dropped on 2026-11-20 together with that term (methodology section 7.2). s0_flippa was removed

Plan: Not worth a headless browser: passing the challenge breaks the terms of the site and breaks often. By hand for the top-5 niches, like Acquire.com

#### ✅ Empire Flippers (API) (`empire_flippers`) - P2

https://empireflippers.com/marketplace/ · geo global · role discovery, evaluation · freshness daily · stage groups s0, s5, s6 · stage `s0_empireflippers`

Signals:
- 2,878 listings (including sold) with a verified P&L: average_monthly_net_profit, revenue, listing_price, listing_multiple, monetizations (SaaS / Amazon FBA / eCommerce / Content / Apps), days_on_marketplace, net_profit_trend, risks / opportunities as text
- multiple and 'days on market' per monetization type -> liquidity and exit price (the revenue ceiling)
- listing_status For Sale / Sold / Under Offer -> deal speed per niche

Feeds: `data/raw/ef_listings.csv`; `data/out/universe.csv (source=ef:software|ef:digital, transactions)`; `data/out/deals.csv: ef_software, ef_software_sold, ef_median_profit, ef_median_multiple (passport, not scored)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.empireflippers.com/api/v1/listings/list?limit=100&page=N | none | $0 | public JSON without a key; 29 pages of 100, ~34 KB per listing with monthly metrics (s0_empireflippers caches trimmed pages); the monetizations filter did not work via the query - filter locally | 200 2026-11-20 - count=2871 (2,688 sold, 162 for sale, 21 pending); fields include monetizations[], niches[] tags, customer_type, listing_multiple, first_listed_at |

Traps:
- EF verifies the numbers - the best free source of real profit of small businesses; but software is a small minority: 79 SaaS / app listings of 2,871 over 2014-2026, about ten a year (2026-11-20)
- Matching all listings is noise: 196 Amazon FBA sellers matched marketplace-seller-analytics because their summaries mention Amazon selling - they are customers of the niche, not players. Only software listings are counted per niche, and only 9 of 98 niches with keywords get a match
- Too thin to replace the 3x Flippa term in the deals score; shown in passports only

Plan: Done (2026-11-20): s0_empireflippers -> software and digital listings into the universe, software matches per niche in deals.csv and passports (count, sold, median profit, median multiple). Next: the median SaaS multiple as the exit-price anchor of the ceiling stage

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

#### ✅ TrustMRR (`trustmrr`) - P2

https://trustmrr.com · geo global · role discovery, evaluation · freshness daily · stage groups s0, s5 · stage `s0_trustmrr`

Signals:
- startups whose revenue is read from the payment provider's API (Stripe, Lemon Squeezy, Paddle, RevenueCat...): revenue of the last 30 days, MRR, total, 30-day growth, category, founded date
- about a fifth listed for sale with an asking price and a revenue multiple -> what small software businesses sell for
- matched paying startups per niche -> proof that a niche pays at the indie end

Feeds: `data/raw/trustmrr.csv`; `data/out/deals.csv: trustmrr_n, trustmrr_mrr_sum, trustmrr_mrr_median, trustmrr_rev30_sum, trustmrr_for_sale (passport, not scored)`; `data/out/deals_matches.csv (source=trustmrr)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html_ssr | https://trustmrr.com/ and /category/<slug> (31 categories): startup objects in the Next.js RSC payload (self.__next_f.push) | none | $0 | home ~1.8 MB with ~470 top earners; a category page holds its 30 top earners, the rest only through client pagination; llms.txt asks automated clients not to scrape for full access, so s0_trustmrr reads only these first pages | 200 2026-11-21 - first run of s0_trustmrr (public mode): 35 requests, 985 startups (860 with revenue in 30 days, 417 with MRR >= $1k, 256 for sale) |
| api | https://trustmrr.com/api/ai/discovery (25 recently added + 25 fastest growing) ; https://trustmrr.com/api/ai (25 recently listed for sale + 25 best deals) | none | $0 | fixed cached snapshots, no search or pagination; money in dollars | 200 2026-11-21 - 50 + 50 startups with founded date, category, target audience, asking price |
| api | https://trustmrr.com/api/v1/startups?sort=revenue-desc&limit=10&page=N&minRevenue=<cents> | Bearer TRUSTMRR_API_KEY (tmrr_..., free with an account; the acceptable-use policy forbids cloning businesses and bulk republication) | $0 | 10 per page, 10 requests/min on a standard key (60 premium); money in USD cents; s0_trustmrr --mode api | 401 2026-11-21 - 'Missing or invalid API key' without a key; the public directory shows 13,078 startups; api mode written from the docs, not run yet |

Traps:
- Self-selected indie-hacker audience: AI, SaaS, developer and marketing tools over-represented, offline and enterprise B2B almost absent
- The keyless snapshot is the top ~1,000 earners: a match proves a niche pays, a zero proves nothing
- About 7% stealth listings ('Hidden Business'), matched on the description only; regex matches need review in deals_matches.csv

Plan: Done (2026-11-21): s0_trustmrr (public snapshot; API mode with TRUSTMRR_API_KEY) and TrustMRR columns in deals.csv / passports (not scored). Next: a free key for the full list (revenue >= $100); TrustMRR into universe.csv as source_type=proven

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

#### ✅ Chrome Web Store (`chrome_web_store`) - P2

https://chromewebstore.google.com · geo global · role evaluation · freshness daily · stage groups s5 · stage `s5_ecosystems`

Signals:
- extensions per niche: weekly users, ratings -> concentration of browser-channel niches (players >= 10k users, top-1 share, HHI)

Feeds: `data/out/ecosystems_metrics.csv`; `data/out/ecosystems_items.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | POST https://chromewebstore.google.com/_/ChromeWebStoreConsumerFeUi/data/batchexecute?rpcids=zTyKYc (the search page's own data call: query, page size 150, continuation token) | none | $0 | 150 results per page, continuation token, total match count; undocumented internal call, can change without notice | 200 2026-11-21 - 150 items with id, name, rating, ratings, users |
| html_ssr | https://chromewebstore.google.com/search/<query> | none | $0 | first 10 results only (AF_initDataCallback ds:1); the stage's fallback | 200 2026-11-21 - ~635 KB HTML, 10 results |

Traps:
- Users = weekly active installs, rounded, capped at 10,000,000+; no store price (payments retired 2020); many extensions are free companions of a paid web product

Plan: Done (2026-11-21): s5_ecosystems, 17 niches in config/ecosystems_map.yaml

#### ✅ Atlassian Marketplace (`atlassian_marketplace`) - P3

https://marketplace.atlassian.com · geo global · role evaluation · freshness daily · stage groups s5 · stage `s5_ecosystems`

Signals:
- Jira/Confluence apps per niche: active installs, reviews, free vs paid -> concentration for team-tool niches

Feeds: `data/out/ecosystems_metrics.csv`; `data/out/ecosystems_items.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://marketplace.atlassian.com/rest/2/addons?text=<q>&limit=50&offset=N&hosting=cloud[&cost=free] | none | $0 | open JSON, 50 per page; distribution.totalInstalls (totalUsers = -1), reviews.count/averageStars; no per-app price in the list (cost=free filter) | 200 2026-11-21 - works; text search matches any word, so a relevance regex is needed |

Traps:
- One install = one site, not one user; only niches whose buyer lives in Jira/Confluence (one shortlisted niche on 2026-11-21)

Plan: Done (2026-11-21): s5_ecosystems

### search - Search demand - volumes, CPC, trend

#### ✅ DataForSEO (Google Ads search_volume) (`dataforseo`) - P1

https://dataforseo.com · geo global · role evaluation, trend · freshness monthly · stage groups s3, s4 · stage `s3_dataforseo`, `s3_switch_intent`

Signals:
- volume, CPC, competition_index, 48 months of history per keyword - the core of s3
- s3_switch_intent: '<brand> alternative(s)', 'apps like <brand>', 'cancel <brand>' and the Russian equivalents for every brand query - switching and churn intent relative to brand demand (evidence, not in the score)

Feeds: `data/out/dfs_*.csv`; `data/out/metrics_quick.csv`; `data/out/switch_intent.csv`; `data/out/switch_intent_kw.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | google_ads/search_volume/live | DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD | $0.09/call up to 1,000 keywords | a positive balance is required | 200 2026-11-23 - s3_switch_intent finished on a verified account: $0.09 per batch with 24 months of history; brands with brackets are rejected (40501) and are now cleaned; two earlier accounts were paused (40201) or unverified (40104) |

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

#### ✅ DataForSEO SERP + Labs keyword difficulty (`dataforseo_serp`) - P1

https://dataforseo.com/apis/serp-api · geo global · role evaluation · freshness daily · stage groups s5 · stage `s5_serp`

Signals:
- who owns Google's first page for category queries: review directories, media listicles, stores, forums, the niche's own brands; AI Overview and local pack presence; keyword difficulty 0-100 - how a newcomer gets found and whether Google answers by itself

Feeds: `data/out/serp_ownership.csv`; `data/out/serp_items.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | serp/google/organic/live/advanced (top 10, US); dataforseo_labs/google/bulk_keyword_difficulty/live (up to 1,000 keywords per task) | DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD | about $0.002 per SERP page; $0.01 per difficulty task + $0.0001 per keyword; the 74 shortlisted niches x 3 queries = about $0.48 | a positive balance is required; the stage stops before paying when the balance is below 1.5x the estimate | 200 2026-11-23 - first full run on a verified account: 222 SERPs and one difficulty task, ~$0.40; organic results now come as google.com/goto redirects (domain read from the breadcrumb); 2 keywords answered 20000 with an empty task list and were charged; a 40104 appeared once mid-run and cleared |

Traps:
- One snapshot of a page that changes daily and is personalised
- Brand match is by name in the domain: renamed or generic domains count as 'other'

Plan: Done (2026-11-23). R:ai-overview fires for 73 of 74 niches (AI Overview on 97% of queries) and no longer separates niches; a sharper test would be whether the overview cites the niche's brands

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

Traps:
- App pages carry no review texts (probe 2026-11-20): not a buyer-voice source

Plan: -

#### ✅ Startpack (`startpack`) - P1

https://startpack.ru · geo ru · role voice, evaluation · freshness daily · stage groups s10 · stage `s10_ru_reviews_fetch`

Signals:
- s10: Russian B2B reviews (rating, pros, cons, text) of the products listed per niche - unmet needs, quality complaints, switching; the voice app stores do not have for B2B

Feeds: `data/out/ru_reviews_*.csv|jsonl|json (store = startpack)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://startpack.ru/application/<code>/reviews?sort_by=date&sort_desc=desc&page=N (50 reviews a page, schema.org Review); /category/<slug>?page=N (products with review counts) | none | $0 | robots.txt allows these pages (it disallows /review/, /rest/, /goto/) and sets ai-input=yes, ai-train=no; the site is a JS front end, but these pages are rendered on the server; 1 request/s | 200 2026-11-20 - Bitrix24: 696 reviews, all 50 on page 1 from 2026; 2,228 products in the sitemap, 165 categories |
| html | https://startpack.ru/category/... | none | $0 | 403 at the earlier probe | 403 2026-09-17 - closed then |

Traps:
- Leans positive: vendors run review campaigns (bursts of same-day five-star reviews from new accounts); one product can be most of a niche's reviews
- Categories are broad and overlap, so products are mapped to niches by hand (config/startpack_map.yaml)
- B2B reviews accumulate slowly: the window is 36 months; in 24 months half of the B2B niches tried had fewer than 80 reviews

Plan: Done (2026-11-20): a third store in s10_ru_reviews_*; percentiles within the B2C and B2B segments

#### ✅ FNS register of small and medium businesses (open data dump) (`fns_rmsp`) - P1

https://www.nalog.gov.ru/opendata/7707329152-rsmp/ · geo ru · role evaluation, trend · freshness monthly · stage groups s8, s6 · stage `ru_msp_counts`

Signals:
- Russian small and medium businesses per main OKVED code (legal entities / entrepreneurs, micro / small / medium, 'newly created' flag) and the change over 12 months - the size and growth of the who of a Russian B2B niche

Feeds: `data/out/ru_msp_okved.csv`; `data/out/ru_msp_niches.csv`; `data/out/who_counts.csv (ru_* columns)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| bulk | https://file.nalog.ru/opendata/7707329152-rsmp/data-DDMMYYYY-structure-*.zip (monthly since 2016) | none | $0 | about 2.2 GB of zipped XML per month (~6.9 million records, 7,661 files); ~6 MB/s; counted while reading the zip, the zip is deleted afterwards | 200 2026-11-21 - 10.11.2026: 6,895,493 records, 2,658 codes |
| api | https://rmsp.nalog.ru/statistics-proc.json (type=chartokvedstat) | none | $0 | only the 30 most common codes per region, type and size: not usable for arbitrary niches | 200 2026-11-21 - 11.7 MB JSON, 537 codes in total |

Traps:
- The self-employed (NPD) are not in the register: trades dominated by them are undercounted
- The main OKVED code is self-declared and often generic
- Non-profit and religious organisations are not SMEs

Plan: Done (2026-11-21)

#### ✅ FNS open data - income and expenses from financial statements (`fns_revexp`) - P2

https://www.nalog.gov.ru/opendata/7707329152-revexp/ · geo ru · role evaluation, trend · freshness quarterly · stage groups s6 · stage `ru_vendor_revenue`

Signals:
- yearly income and expenses of every organisation that filed statements (legal name, INN) - matched to the right holders of the domestic software register: the money of a niche's vendors and its growth, independent of search

Feeds: `data/out/ru_vendor_revenue.csv`; `data/out/ru_vendor_revenue_vendors.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| bulk | https://file.nalog.ru/opendata/7707329152-revexp/data-YYYYMMDD-structure-20180110.zip | none | $0 | about 100 MB zip of XML per release; released yearly with revisions | 200 2026-11-21 - release 25.10.2026: statements for 2025 |

Traps:
- Income is the whole company's, not the product's: large groups are marked 'diversified' and left out of sums
- Matching by normalised legal name: shared names are 'ambiguous'; individual entrepreneurs file no statements

Plan: Done (2026-11-21); an INN in the register output would remove the name matching

#### ⛔ GIR BO - state resource of financial statements (bo.nalog.ru) (`gir_bo`) - none

https://bo.nalog.ru · geo ru · role evaluation · freshness quarterly · stage groups s6 · stage not implemented

Signals:
- full statements (revenue line 2110, profit) per company by INN

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://bo.nalog.ru/advanced-search/organizations/search?query=... | none | $0 | every path, the JS bundle included, returns the same 620-byte application shell to a script | 200 2026-11-21 - shell only; not worked around - fns_revexp gives income and expenses openly |

Traps:
- Use fns_revexp instead

Plan: -

#### ✅ MoySklad integrations catalog (`moysklad_apps`) - P3

https://www.moysklad.ru/integratsii/ · geo ru · role evaluation · freshness monthly · stage groups s5 · stage `ru_ecosystems`

Signals:
- apps per niche, distinct developers, paid share, popular flag -> Russian supply inside the retail / warehouse SMB platform

Feeds: `data/out/ru_ecosystems.csv`; `data/out/ru_ecosystems_apps.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.moysklad.ru/sitemap.xml (all /integratsii/apps/<slug>/) + app pages (name, paid/free, developer, upload date, description) + /integratsii/<category>/ page 1 | none | $0 | robots.txt disallows URLs with '?', so category 'show more' pages are not read; apps.moysklad.ru redirects here; no installs or ratings | 200 2026-11-21 - 589 apps, 33 categories; marketplace sellers 67 apps / 39 developers |

Traps:
- The upload date is an update date (409 of 589 in 2026)
- Retail and warehouse focus: service niches have ~0 apps

Plan: Done (2026-11-21): ru_ecosystems

#### ✅ amoCRM widgets (public showcase) (`amocrm_extensions`) - none

https://www.amocrm.ru/extensions/ · geo ru · role evaluation · freshness static · stage groups s5 · stage `ru_ecosystems`

Signals:
- widgets per niche in the public amoCRM showcase (groups phone, site, mail, chats, useful, recommended)

Feeds: `data/out/ru_ecosystems.csv`; `data/out/ru_ecosystems_apps.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.amocrm.ru/extensions/ and ?group=<g> (slug + one-line description) | none | $0 | the old /integrations/ and /marketplace are 404; the live amoMarket market.amocrm.ru needs a login | 200 2026-11-21 - 101 widgets; market.amocrm.ru 401, /integrations/ 404 |

Traps:
- Stale curated subset (images from 2019); no prices, developers or installs

Plan: Done (2026-11-21): ru_ecosystems; the real amoMarket needs an account

#### ⛔ YCLIENTS marketplace (`yclients_marketplace`) - none

https://www.yclients.com/marketplace/ · geo ru · role evaluation · freshness monthly · stage groups s5 · stage not implemented

Signals:
- integrations for beauty, fitness and service businesses (would feed ru_ecosystems)

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://www.yclients.com/api/v1/marketplace/applications/country/RU (used by the front end) | partner token | $0 | robots.txt disallows /api/ and /marketplace_marketing/*; no server-rendered app pages, none in the sitemap | 404 2026-11-21 - page 200 is an empty JS shell; API without token 404; the token embedded in the page was not used |

Traps:
- Most relevant catalog for salons and studios, but not readable keylessly

Plan: Only with a YCLIENTS partner account

### gov_stats - Official business statistics - how many buyers of a kind exist (the who of a B2B niche)

#### ✅ US Census County Business Patterns + Nonemployer Statistics (bulk files) (`us_census_cbp`) - P1

https://www.census.gov/programs-surveys/cbp.html · geo global · role evaluation · freshness static · stage groups s8, s6 · stage `s8_who_counts`

Signals:
- establishments with employees per NAICS code (latest year and the year before), how many have under 20 employees, firms without employees (sole proprietors) - the real number of potential buyers for a one-industry B2B niche; passports turn 'payers needed' into a share of the industry

Feeds: `data/out/who_counts.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| bulk | https://www2.census.gov/programs-surveys/cbp/datasets/<year>/cbp<yy>us.zip; nonemployer-statistics/datasets/<year>/historical-datasets/nonemp<yy>us.zip | none | $0 | national files of under 1 MB; CBP 2023 is the latest (CBP 2024: 404 on 2026-11-21), Nonemployer 2024 | 200 2026-11-21 - CBP 2023 (NAICS 2017) and 2022, Nonemployer 2024 (NAICS 2022, 452 codes of mixed depth) |
| api | https://api.census.gov/data/2023/cbp?get=ESTAB&for=us:*&NAICS2017=... | a free key is now required | $0 | not used: the bulk files carry the same national numbers | 200 2026-11-21 - an HTML 'Missing Key' page |

Traps:
- Counts establishments (locations), not firms
- A NAICS code can be wider than the niche: config/who_counts.yaml says whether a number is a ceiling or a floor
- Nonemployer data use NAICS 2022, CBP 2023 uses NAICS 2017 (e-commerce 454110 and software 511210 have no nonemployer row)

Plan: Done (2026-11-21): 36 niches mapped by hand in config/who_counts.yaml

### web - Web footprint - how old competitors' sites are, who went quiet, how much traffic they get

#### ✅ Wayback Machine CDX API (`wayback_machine`) - P2

https://web.archive.org · geo global · role trend · freshness daily · stage groups s9 · stage `s9_wayback`

Signals:
- first capture (site age), last live capture and months with captures for the websites of the niche's top apps - how entrenched the leaders are, how many newcomers appeared on the web, how many competitors went quiet; no second snapshot needed

Feeds: `data/out/wayback.csv`; `data/out/wayback_domains.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://web.archive.org/cdx/search/cdx?url=<domain>&output=json&fl=timestamp,statuscode&collapse=timestamp:6 | none | $0 | slow and sometimes times out (a domain then stays unmeasured); 1 request/s; cached per month | 200 2026-11-21 - hallow.com: first capture 1998 (an earlier owner of the domain) |

Traps:
- A domain's history can predate the current business
- Rarely crawled small sites look 'quiet'
- Developer sites come from the iTunes sellerUrl field: web-only competitors are not covered

Plan: Done (2026-11-21); price-page history (price raises) is the next step

#### 💰 Similarweb (`similarweb`) - P3

https://www.similarweb.com · geo global · role evaluation · freshness monthly · stage groups s5 · stage not implemented

Signals:
- competitors' visits and traffic mix (search, paid, referral, social) - which channel acquires their customers

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.similarweb.com/v1/website/<domain>/total-traffic-and-engagement/visits | paid API key (a Similarweb MCP connector is also offered in Claude Code, unauthorised here) | subscription | - | 401 2026-11-21 - invalid API key |

Traps:
- Estimates are weak for small sites, which are most of a fragmented niche

Plan: Only if a subscription appears

### ads - Ad libraries and ad-account forecasts - acquisition cost and who pays for traffic

#### ✋ Meta Ad Library (`meta_ad_library`) - P2

https://www.facebook.com/ads/library/ · geo global · role evaluation · freshness daily · stage groups s5 · stage not implemented

Signals:
- active ads per advertiser and how long each runs - an advertiser who keeps one ad for months is profitable on paid traffic: acquisition pays back in the niche

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q=... | none | $0 | a JavaScript challenge for scripts | 403 2026-11-21 - challenge page |
| api | graph.facebook.com/<v>/ads_archive | identity-verified Meta developer token | $0 | non-political ads only for ads delivered in the EU (DSA) | 403 2026-11-21 - not probed with a token |

Traps:
- US coverage of commercial ads exists only in the web interface

Plan: By hand for the final 3-5 niches: count advertisers and ads older than 60 days

#### ✅ Google Ads Transparency Center (through DataForSEO) (`google_ads_transparency`) - P1

https://adstransparency.google.com · geo global · role evaluation · freshness daily · stage groups s5 · stage `s5_advertisers`

Signals:
- ads of each competitor's website shown in the US: total, running now, how long the running ones have run, format (text ~ Search) -> who pays for traffic in a niche and whether paid acquisition is sustained (a 90+ day ad pays back); the advertiser count the SERP paid blocks never gave

Feeds: `data/out/advertisers.csv`; `data/out/advertisers_domains.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | DataForSEO serp/google/ads_search/task_post (target = domain, location_code 2840, depth 40) -> task_get/advanced/<id> (first_shown, last_shown, format, title, verified; se_results_count = total ads) | DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD | $0.0006 per task (one page of up to 40 ads); 157 brand domains = about $0.10 | asynchronous: results in ~10 s; up to 100 tasks per POST; ads_advertisers searches advertiser names, not topics, so domains come from s5_serp and s9_wayback | 200 2026-11-23 - hallow.com: 300 ads in total, 40 returned, text / image / video, first and last shown dates |
| html | https://adstransparency.google.com/?region=US | none | $0 | a JavaScript application; data comes from internal RPC calls | 200 2026-11-21 - 2.6 MB application page |

Traps:
- A domain shared by a company's other products counts all its ads
- Transparency covers Search, YouTube and Display together
- Competitors without their own site are missed; the live SERP shows paid blocks on only 2 of 223 vendor pages, so it cannot replace this

Plan: Done (2026-11-23): s5_advertisers on the niches' own brand domains (157 domains, 59 niches; 15 niches have no brand domain): A:ads-pay 20, A:no-ads 2 (screen-time focus apps, couples apps). A first pass on the top App Store sites flagged 40 of 74 niches because giants (eBay, AliExpress, Shop, Zoom) were among them - hence the brand-domain rule

#### ✅ Yandex Direct budget forecast (API v4 Live) (`yandex_direct_forecast`) - P2

https://yandex.ru/dev/direct/ · geo ru · role evaluation · freshness monthly · stage groups s8 · stage `s8_direct_forecast`

Signals:
- Yandex CPC and clicks per Wordstat phrase - the price of a click on the search engine Russians use (the Russian pool's CPC in S3 comes from Google Keyword Planner)

Feeds: `data/out/direct_forecast.csv, direct_niche.csv; a column in reports/S6-ru.md`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.direct.yandex.ru/live/v4/json/ (CreateNewForecast -> GetForecastList -> GetForecast -> DeleteForecastReport; JSON envelope with the token in the body) | OAuth token (direct:api) of an app registered at oauth.yandex.ru ('for API access') and an approved access request in Direct Pro (Tools > API > My requests; up to 7 working days; the simplified Direct interface has no API settings, and switching to Direct Pro cannot be undone) | $0 | up to 100 phrases per report, at most 5 stored reports (error 31), kept five hours; forecasts spend no API points; the Live 4 sandbox host does not resolve | 200 2026-11-23 - error 58 'No access' until the app's request is approved; the account's programmatic access is open with 32,000 points |

Traps:
- Overlapping phrases inside one report may have their forecast attributed to either of them: a niche's phrases share one report
- Evidence only: replacing the Google CPC in a score is a separate decision

Plan: Built (2026-11-23): s8_direct_forecast, tested on the documented format; the first real run waits for the access approval

### oss - Open source - free substitutes that cap willingness to pay

#### ✅ GitHub repository search (`github_search`) - P2

https://github.com/search · geo global · role evaluation · freshness daily · stage groups s5 · stage `s5_oss`

Signals:
- open-source substitutes per niche: repos with >= 100 / 1,000 stars, maintained (pushed < 12 months) -> flag O:oss-substitute

Feeds: `data/out/oss_substitutes.csv`; `data/out/oss_repos.csv`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.github.com/search/repositories?q="<phrase>" in:name,description,topics fork:false&sort=stars&per_page=100 | optional GITHUB_TOKEN (Bearer) | $0 | 10 search requests/min keyless, 30/min with GITHUB_TOKEN; 1,000 results max per query | 200 2026-11-21 - keyless works; 74 niches in 35 minutes without rate-limit hits; 27 flagged O:oss-substitute |

Traps:
- Stars = developer attention, not buyers, and can be bought (compare forks)
- Phrase search misses projects worded differently (Fider for feedback boards)

Plan: Done (2026-11-21): s5_oss

### regulation - Regulations - compliance deadlines that create demand before it shows in search

#### ✅ Federal Register (API) (`federal_register`) - P2

https://www.federalregister.gov/developers/documentation/api/v1 · geo global · role discovery · freshness daily · stage groups s0 · stage `s0_regulation`

Signals:
- US final and proposed rules of the last 12 months: title, abstract, action, dates, agencies, effective date, significant flag -> new recurring compliance tasks for small businesses (who must do what by when) before the demand shows in search

Feeds: `data/out/regulation_prefilter.csv`; `data/out/regulation_candidates.csv`; `reports/S0-regulation.md`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://www.federalregister.gov/api/v1/documents.json?per_page=1000&conditions[type][]=RULE\|PRORULE&conditions[publication_date][gte\|lte]=...&fields[]=... | none | $0 | 1,000 per page, next_page_url with a cursor; ~5 requests a year of history | 200 2026-11-21 - 2,931 final + 1,771 proposed rules in 12 months; 794 pass the prefilter (60% of final rules are airworthiness directives, safety zones, air plans) |

Traps:
- The LLM reads the abstract, not the rule text
- 2025-2026 rules often remove obligations
- Discovery for a human: never scored or written to niches.yaml

Plan: Done (2026-11-21): s0_regulation; first full run: 32 of 150 selected US documents create a task (16 with high confidence; most deadlines already passed, Section 1071 lending data from 2028)

#### ✅ regulation.gov.ru (federal portal of draft regulations, open-data API) (`regulation_gov_ru`) - P2

https://regulation.gov.ru · geo ru · role discovery · freshness daily · stage groups s0 · stage `s0_regulation`

Signals:
- Russian draft regulations of the last 12 months: kind, department, ORV procedure and impact degree, affected persons, problem, mandatory-requirements flag, planned entry into force -> compliance tasks for Russian small businesses before adoption

Feeds: `data/out/regulation_prefilter.csv`; `data/out/regulation_candidates.csv`; `reports/S0-regulation.md`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://regulation.gov.ru/api/npalist?limit=500&offset=N&sort=desc (XML; fields, search, id) | none | $0 | limit <= 500 (limit=1000 answers 200 with an error text); no date filter, walk newest first; directly reachable, NF_PROXY_RU timed out | 200 2026-11-21 - total 130,351 projects; 8,880 in 12 months (18 pages); 2,806 pass the prefilter; most list rows carry only a title |
| api | https://regulation.gov.ru/api/public/PublicProjects/Print/<id> (JSON passport); /api/public/Rss/ (RSS) | none | $0 | one request per draft, some answers take tens of seconds; the passport also holds officials' contacts (not read) | 200 2026-11-21 - 150 passports read: keywords, economic activity, 'mandatory requirements (KND)', affected persons, planned entry into force |
| api | http://publication.pravo.gov.ru/api/Documents?PageSize=10&Index=1&block=government (adopted acts) | none | $0 | PageSize must be one of the allowed values (5 -> 400); titles only ('on amendments to resolution No. N'), no abstract | 200 2026-11-21 - 58,872 government acts; not used, too little text for a classifier |

Traps:
- Drafts may never be adopted
- The ORV impact degree is the strongest prefilter signal (1,220 ORV drafts a year)
- Discovery for a human: never scored or written to niches.yaml

Plan: Done (2026-11-21): s0_regulation; first full run: 55 of 150 selected Russian drafts create a task (25 with high confidence: traceability, marking, EGAIS formats, lifting-equipment logs)

### info_market - Paid information products - whether people pay for knowledge on a topic

#### 🛠 Etsy (digital downloads) (`etsy`) - P3

https://www.etsy.com · geo global · role evaluation · freshness daily · stage groups s8 · stage not implemented

Signals:
- digital listings (planners, templates, guides) and shop sales counts - paid demand for a topic's information products

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| html | https://www.etsy.com/search?q=... | none | $0 | anti-bot challenge | 403 2026-11-21 - blocked |
| api | https://openapi.etsy.com/v3/application/listings/active?keywords=... | a free API key (developer application) | $0 | 10 requests/s | 403 2026-11-21 - not probed with a key |

Traps:
- English-speaking buyers

Plan: Add an ETSY_API_KEY and extend info_paid

#### ✅ Stepik (online courses) (`stepik`) - P2

https://stepik.org · geo ru · role evaluation · freshness daily · stage groups info · stage `info_paid`

Signals:
- info cohort: relevant paid courses per topic, learners in them, reviews, median price, paid courses published in 24 months - do people pay for knowledge on the subject

Feeds: `data/out/info_paid.csv: sp_*`; `data/out/info_paid_items.csv (source=stepik)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://stepik.org/api/search-results?query=...&type=course&page=N | none | $0 | 20 courses a page, at most 200 results; page 11 -> 404, and a page past the real end can answer 404 while has_next is true; ranks by popularity more than relevance (under 'английский язык' page 1 is Python courses), so every page is read and titles are filtered; language= and is_paid= are ignored | 200 2026-11-21 - 'английский язык': count 200, 21 English-language-learning titles over 10 pages; 'вязание спицами': no knitting course in the top 200 |
| api | https://stepik.org/api/courses?ids[]=..&ids[]=.. ; /api/course-review-summaries?ids[]=.. | none | $0 | 20 ids a call; learners_count, is_paid, price, currency_code, display_price, language, became_published_at, review_summary | 200 2026-11-21 - course 92015: 11,091 learners, 4,100 RUB, 388 reviews (avg 4.99) |

Traps:
- Mostly IT, school-exam and university courses: craft, beauty and lifestyle topics read empty although they sell elsewhere (first run: 1 paid knitting course, 0-2 learners)
- learners_count includes people who took only a free part of a paid course
- Connection resets under parallel load on 2026-11-21, through the proxy and directly; retries fix them

Plan: Done (2026-11-21): info_paid (Stepik + Litres), shown in info_score with the flags I:paid-market / I:no-paid; no effect on the score

#### ✅ Litres (ebook store) (`litres`) - P2

https://www.litres.ru · geo ru · role evaluation · freshness daily · stage groups info · stage `info_paid`

Signals:
- info cohort: relevant paid non-fiction ebooks per topic, their rating counts (a sales proxy), median price, books first on sale in 24 months, self-published books (the route open to a single author)

Feeds: `data/out/info_paid.csv: lr_*`; `data/out/info_paid_items.csv (source=litres)`

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.litres.ru/foundation/api/search?q=...&types=text_book&limit=100&offset=N | none | $0 | limit 100; relevance order; matches every word of the query ('пианино для начинающих' -> 0 books, 'пианино' finds them); covers fiction and offers no genre filter | 200 2026-11-21 - 'вязание спицами': 905 books, each with full_price, is_free, rated_total_count, available_from, persons (publisher role) |
| api | https://api.litres.ru/foundation/api/arts/<id> | none | $0 | one book a call (~0.2 s); the only endpoint with genres (is_main marks the main one); a withdrawn book -> 404 | 200 2026-11-21 - genres of a matched 'Право ...' novel = romance fantasy (main) |

Traps:
- A topic word is often a novel's title: under 'право' 73 matched books were fiction, so each counted book's main genre is checked
- Rating counts are lifetime, not a yearly rate; the ratio of ratings to sales is unknown
- Magazines and school workbooks count as paid info

Plan: Done (2026-11-21): info_paid

#### 🛠 Gumroad (digital products) (`gumroad`) - none

https://gumroad.com · geo global · role evaluation · freshness daily · stage groups info · stage not implemented

Signals:
- English info products per keyword: count, price, ratings (no sales counts)

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://gumroad.com/products/search?query=... | none | $0 | the discover page's own JSON: total, tags, products with price_cents, currency, ratings {count, average}, native_type; no sales counts | 200 2026-11-21 - 'notion': total 24,612; 'knitting': 295; Cyrillic query: 0 |

Traps:
- No Cyrillic catalogue and no Russian payments: useless for the Russian info cohort

Plan: Not a stage: revisit only for an English info product, as supply count + ratings per keyword

#### 🛠 Plati.market / Digiseller (digital goods) (`plati_market`) - none

https://plati.market · geo ru · role evaluation · freshness daily · stage groups info · stage not implemented

Signals:
- Russian digital goods per keyword with numsold (sales count), price, seller, reviews

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://plati.io/api/search.ashx?query=...&pagesize=50&pagenum=1&response=json | none | $0 | items with numsold, count_positiveresponses, price_rur, section_id | 200 2026-11-21 - knitting: 0 items; English: test packs, exam answers and essays; neural networks: subscription resale |

Traps:
- The catalogue is game keys, accounts, student work and leaked courses, not topic info products

Plan: Not worth a stage

#### ⛔ Boosty (paid subscriptions of authors) (`boosty`) - P3

https://boosty.to · geo ru · role evaluation · freshness daily · stage groups info · stage not implemented

Signals:
- paid author subscriptions by topic: tiers, prices, subscriber counts where shown

| Method | Endpoint | Auth | Cost | Limits / format | Probe |
|---|---|---|---|---|---|
| api | https://api.boosty.to/v1/blog/search?query=... | none | $0 | 'search' is read as a blog name: there is no open topic search | 200 2026-11-21 - no topic search |

Traps:
- Reachable only blog by blog, e.g. from the Telegram / YouTube links of info authors

Plan: Read the Boosty links that info_telegram finds behind teaching Shorts, if that proves useful

