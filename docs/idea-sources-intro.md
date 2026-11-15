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
