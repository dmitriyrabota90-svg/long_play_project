# News Events Design

## Executive Summary

Phase 6.4B is a design-only step for a future news/events layer. It does not add
an Alembic migration, does not change SQLAlchemy models, does not write
PostgreSQL rows, does not implement a collector, does not change schedulers,
does not add ML targets, and does not add an NLP or LLM classifier.

The proposed layer has three future tables:

- `news_articles`: source-backed article/release metadata with raw lineage.
- `commodity_events`: normalized event rows derived from articles, official
  report releases, or future controlled extraction rules.
- `daily_news_features`: precomputed product-level daily news/event aggregates.

Phase 6.4C should implement the reviewed schema only. Phase 6.4D should add the
first controlled GDELT/report collector. Phase 6.4E should add rule-based event
extraction. Phase 6.4F should integrate daily news/event features and export
columns only after as-of rules are reviewed.

Phase 6.4C implements schema-only support for the news/events layer:
SQLAlchemy metadata, Alembic revision `0014_news_events_schema`, idempotent
source seeds for GDELT 2.1, USDA reports, FAO releases, and World Bank
commodity releases, and operational report counts for empty news/event tables.
It still does not implement a collector, does not write news rows, does not
register a scheduler, does not add ML targets, and does not add an NLP/LLM
classifier.

Phase 6.4D implements the first controlled GDELT DOC article metadata collector
named `gdelt_news`. It is manual-only, bounded to small date windows, stores raw
evidence through `RawStore`, writes `raw_responses`, and inserts normalized rows
into `news_articles`. It intentionally does not write `commodity_events`, does
not build `daily_news_features`, does not register a scheduler, and does not add
ML/NLP/LLM classification.

Phase 6.4E implements deterministic rule-based event extraction from stored
`news_articles` into `commodity_events`. It does not call external news APIs,
does not fetch article bodies, does not build `daily_news_features`, does not
register a scheduler, and does not add an NLP/LLM/ML classifier. The extractor
is intentionally transparent: all event categories and commodity-family mappings
live in versioned local rules.

## Why News/Events Matter For Agricultural Commodity Price Forecasting

News and official releases can change price expectations before slower monthly
datasets update. Export restrictions, import policies, Black Sea disruptions,
weather disasters, crop reports, biofuel mandates, energy shocks, currency
shocks, demand changes, and supply chain disruption are all plausible drivers
for oilseed, vegetable oil, meal/feed, grain, fertilizer, and energy markets.

The layer must be leakage-safe. A future dataset row for a given feature date
must know whether an article was published and whether this system had fetched
it by that date.

## Current Commodity/Product Families

The current dataset motivates the first event design around:

- `soybean`: `soybean_oil`, `soybean_meal`;
- `rapeseed/canola`: `rapeseed_oil`, `rapeseed_meal`;
- `vegetable_oils`: soybean oil, rapeseed oil, palm/sunflower substitutes later;
- `grains`: maize/corn, wheat, and related feed/biofuel context;
- `fertilizer/energy linkage`: crude oil, gas, diesel, and fertilizer cost
  pressure.

## First Source Decision

The first broad news/event prototype should use GDELT 2.1 DOC/Event APIs.

Reasons:

- public global metadata-oriented source;
- no project secret is needed for the first bounded prototype;
- suitable for narrow commodity/event keyword windows;
- can cover policy, conflict, logistics, disasters, macro shocks, and demand
  shocks across regions;
- Phase 6.4A classified it as the recommended first broad source.

GDELT is noisy. The first prototype must use small date windows, explicit
keyword/event filters, request limits, and measured false-positive rates. It
should store metadata and source URLs first, not republished article bodies.

## First Official Report/Release Layer

The first low-noise report layer should cover official release metadata:

- USDA WASDE and PSD report pages;
- FAO news and Food Price Index releases;
- World Bank commodity market releases and blogs.

These sources are better starting points for structured `crop_report`,
`energy_shock`, `currency_macro`, and global market-context events because
publication cadence, source identity, and business meaning are clearer than
generic web search results.

## Why Not Start With High-Risk Scraping Or Commercial Pages

Google News RSS-style search feeds and commercial commodity news pages can be
useful for manual discovery, but they are not good first production sources.

Reasons:

- search results are dynamic and not stable historical evidence;
- article licensing and body storage are risky;
- commercial pages often require explicit API contracts;
- broad scraping would increase operational and policy risk;
- noisy syndicated articles can flood a small dataset.

The first collectors should be bounded, auditable, and easy to turn off.

## Event Taxonomy

Initial event categories:

| category | direction hint | lag bucket | notes |
| --- | --- | --- | --- |
| `export_restriction` | bullish | `same_day` or `1_7d` | Export bans, duties, quotas, licensing, and sanctions that tighten tradable supply. |
| `import_policy` | mixed | `1_7d` or `7_30d` | Import duties, quotas, phytosanitary changes, and destination-market access. |
| `war_logistics_disruption` | bullish | `same_day` or `1_7d` | Ports, Black Sea routes, sanctions, infrastructure attacks, and route closures. |
| `weather_disaster` | bullish | `7_30d` | Drought, flood, frost, heat, hurricane, fire, and crop-region disaster impacts. |
| `crop_report` | mixed | `same_day` or `1_7d` | WASDE/PSD, stocks, acreage, production, use, and supply/demand revisions. |
| `biofuel_policy` | mixed | `7_30d` | Biodiesel, ethanol, renewable fuel mandates, blending requirements. |
| `energy_shock` | mixed | `same_day` or `1_7d` | Crude oil, gas, diesel, and fertilizer-linked energy shocks. |
| `currency_macro` | mixed | `same_day` or `1_7d` | FX moves, inflation, rate shocks, macro policy changes. |
| `demand_shock` | mixed | `1_7d` or `7_30d` | China imports, crush demand, livestock feed demand, palm/soy substitution. |
| `supply_chain` | bullish | `same_day` or `1_7d` | Freight, rail, ports, containers, labor stoppages, logistics bottlenecks. |

Allowed `direction_hint` values should be:

- `bullish`
- `bearish`
- `mixed`
- `unknown`

Allowed `lag_bucket` values should be:

- `same_day`
- `1_7d`
- `7_30d`
- `30d_plus`
- `unknown`

Allowed `extraction_method` values should be:

- `manual_rule`
- `keyword_rule`
- `official_report_mapping`
- `future_nlp`
- `future_llm`

`future_nlp` and `future_llm` are reserved enum-like values for later work. No
NLP classifier and no LLM classifier are implemented in Phase 6.4B.

## Proposed Tables

| table | purpose |
| --- | --- |
| `news_articles` | Source-backed article/report/release metadata and optional short text fields. |
| `commodity_events` | Event rows derived from articles or official report mappings. |
| `daily_news_features` | Product-level daily aggregates for later joins into `daily_product_features`. |

The design keeps raw article/release metadata, normalized events, and daily
features separate.

## Article Model

Table: `news_articles`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `source_id` | FK to `sources.id` | no | Source registry entry, e.g. `gdelt_2_1`. |
| `raw_response_id` | FK to `raw_responses.id` | no | Raw response evidence for the payload containing this article. |
| `collector_run_id` | FK to `collector_runs.id` | no | Collector run that fetched the payload. |
| `external_id` | string(255) | yes | Source-specific article/document ID when provided. |
| `url` | text | no | Source URL or API URL for the item. |
| `canonical_url` | text | yes | Normalized article URL if canonicalization is possible. |
| `title` | text | no | Article/report/release title. |
| `summary` | text | yes | Short summary or snippet if licensing permits storage. |
| `body_text` | text | yes | Optional body/excerpt; should be empty unless licensing is reviewed. |
| `language` | string(32) | no | Source language code/name. |
| `source_name` | string(255) | no | Publisher/source name from the feed/API. |
| `country` | string(100) | yes | Source or event country if known. |
| `region` | string(100) | yes | Region/subregion when known. |
| `published_at` | timestamptz | no | Source publication timestamp. |
| `fetched_at` | timestamptz | no | UTC time this system fetched the source payload. |
| `article_hash` | string(64) | no | Stable identity hash. |
| `source_record_hash` | string(64) | no | Hash of normalized mutable metadata/content fields. |
| `source_payload_hash` | string(64) | no | Raw response SHA-256 copied from `raw_responses.sha256`. |
| `metadata_json` | JSONB | yes | Themes, locations, query metadata, parser version, license notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended uniqueness:

- unique `source_id, external_id` where `external_id IS NOT NULL`;
- unique `source_id, article_hash` as fallback identity.

`source_record_hash` is not part of uniqueness. It detects changed title,
summary, body, source metadata, or canonical URL for an already-known identity.

Recommended indexes:

- `source_id, published_at`;
- `published_at`;
- `language`;
- `country`;
- `article_hash`;
- `raw_response_id`;
- `collector_run_id`;
- `source_record_hash`.

## Article Identity Policy

Article identity should prefer stable source IDs, then canonical URL, then a
normalized title/published-at hash.

Suggested `article_hash` inputs:

- canonical URL if available;
- else normalized URL;
- else normalized title plus `published_at` plus source name.

`article_hash` should not include mutable summary/body text. Changed article
metadata should produce a changed `source_record_hash`, not a new identity.

## Event Model

Table: `commodity_events`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `news_article_id` | FK to `news_articles.id` | no | Article/report/release that produced the event. |
| `source_id` | FK to `sources.id` | no | Duplicated source key for faster filtering. |
| `event_category` | string(100) | no | One taxonomy category. |
| `commodity_family` | string(100) | no | `soybean`, `rapeseed`, `vegetable_oils`, `grains`, `energy`, etc. |
| `affected_products` | JSONB | yes | Product codes or family/product mapping evidence. |
| `country` | string(100) | yes | Event country. |
| `region` | string(100) | yes | Event region. |
| `event_date` | date | no | Date to which the event belongs. |
| `published_at` | timestamptz | no | Publication timestamp copied from the article. |
| `direction_hint` | string(32) | no | `bullish`, `bearish`, `mixed`, or `unknown`. |
| `severity` | numeric(18, 8) | yes | Optional rule score or future normalized severity. |
| `confidence` | numeric(18, 8) | no | Rule/extraction confidence from 0 to 1. |
| `lag_bucket` | string(32) | no | Expected lag bucket. |
| `extraction_method` | string(64) | no | `manual_rule`, `keyword_rule`, `official_report_mapping`, `future_nlp`, `future_llm`. |
| `extraction_version` | string(64) | no | Version of rules/mapping that produced the event. |
| `source_text_hash` | string(64) | no | Hash of title/summary/text used for extraction. |
| `metadata_json` | JSONB | yes | Matched keywords, rule names, entities, and review notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(news_article_id, event_category, commodity_family, country, region, event_date, extraction_method)
```

Recommended indexes:

- `event_category, event_date`;
- `commodity_family, event_date`;
- `country, event_date`;
- `published_at`;
- `direction_hint`;
- `confidence`;
- `news_article_id`.

## Event Extraction Policy

The first version should use transparent, reviewable extraction:

- official report mapping for USDA/WASDE/PSD, FAO, and World Bank releases;
- keyword/rule tagging for narrow GDELT prototypes;
- source/category mapping when a feed is already event-specific.

No ML classifier and no LLM classifier are part of Phase 6.4B. Future NLP/LLM
methods can write `extraction_method = future_nlp` or `future_llm` only after
separate review, tests, and leakage controls.

## Daily News Feature Model

Table: `daily_news_features`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `product_id` | FK to `products.id` | no | Product receiving product-level aggregate features. |
| `commodity_family` | string(100) | no | Product family used for event mapping. |
| `feature_date` | date | no | Feature date. |
| `news_count_1d` | integer | no | Article count in 1-day lookback. |
| `news_count_7d` | integer | no | Article count in 7-day lookback. |
| `news_count_30d` | integer | no | Article count in 30-day lookback. |
| `event_count_1d` | integer | no | Event count in 1-day lookback. |
| `event_count_7d` | integer | no | Event count in 7-day lookback. |
| `event_count_30d` | integer | no | Event count in 30-day lookback. |
| `bullish_event_count_7d` | integer | no | Bullish event count in 7-day lookback. |
| `bearish_event_count_7d` | integer | no | Bearish event count in 7-day lookback. |
| `mixed_event_count_7d` | integer | no | Mixed event count in 7-day lookback. |
| `export_restriction_count_30d` | integer | no | 30-day export restriction event count. |
| `import_policy_count_30d` | integer | no | 30-day import policy event count. |
| `war_logistics_count_30d` | integer | no | 30-day war/logistics event count. |
| `weather_disaster_count_30d` | integer | no | 30-day weather disaster event count. |
| `crop_report_count_30d` | integer | no | 30-day crop report event count. |
| `biofuel_policy_count_30d` | integer | no | 30-day biofuel policy event count. |
| `energy_shock_count_30d` | integer | no | 30-day energy shock event count. |
| `demand_shock_count_30d` | integer | no | 30-day demand shock event count. |
| `supply_chain_count_30d` | integer | no | 30-day supply chain event count. |
| `sentiment_proxy_7d` | numeric(18, 8) | yes | Simple rule proxy from direction counts, not ML sentiment. |
| `news_as_of_date` | date | yes | Latest publication date included in the aggregate. |
| `missing_flags` | JSONB | yes | Missing source/category coverage flags. |
| `metadata_json` | JSONB | yes | Rule versions, source coverage, and aggregation notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(product_id, feature_date)
```

Purpose:

- precompute product-level daily news/event aggregates;
- make later joins into `daily_product_features` explicit;
- keep source/event data separate from final export features.

`sentiment_proxy_7d` is only a simple rule proxy from direction counts. It is
not ML sentiment and it is not produced by an LLM classifier.

## Source/Raw Lineage

Future collectors must use the existing source and raw storage pattern:

- create a `collector_runs` row for every run;
- store every external response with `RawStore`;
- write `raw_responses` metadata and SHA-256 hashes;
- link `news_articles.raw_response_id` to raw evidence;
- copy `raw_responses.sha256` into `source_payload_hash`;
- keep `published_at` and `fetched_at` for as-of checks.

Diagnostics artifacts from Phase 6.4A are not production raw evidence.

## Future Source Seeding Design

Phase 6.4B does not modify seed data. Future source seeds should include:

| code | name | category/type | active |
| --- | --- | --- | --- |
| `gdelt_2_1` | GDELT 2.1 DOC/Event APIs | news/event | true |
| `usda_reports` | USDA Reports / WASDE / PSD | official_report | true |
| `fao_news_releases` | FAO News / Food Price Index Releases | official_release | true |
| `world_bank_commodity_releases` | World Bank Commodity Market Releases | official_release | true |

These seeds should be added only in a schema/collector phase that needs them.

## Deduplication Policy

Deduplication should use layered identity:

1. Exact `external_id` deduplication when the source provides a stable ID.
2. Canonical URL deduplication.
3. Normalized title plus `published_at` hash fallback.
4. Same article syndicated across multiple sources is not fully solved in the
   first version; future cross-source dedup can add a separate mapping layer.
5. Updated article with same identity and changed `source_record_hash` should
   create a quality warning. The first collector should not silently overwrite.
6. Raw evidence must be retained for every fetched payload.

## As-Of And Leakage Policy

For realistic simulation, use only articles/events with:

- `published_at <= feature_date`;
- and, in strict `as_collected` mode, `fetched_at <= feature_date` export
  cutoff.

Dataset/export modes should be explicit:

- `as_collected`: use only data fetched by the system by the feature cutoff;
- `publication_aware`: allow items by publication timestamp if raw evidence was
  backfilled later, with clear labeling;
- `historical_backfill_allowed`: offline analysis mode, not a real-time
  simulation.

Search/news APIs can change historical results. Backfilled articles must not be treated as known on past dates unless the selected mode explicitly allows it.
Article body updates after `feature_date` must not leak unless a future revision
policy records and gates those updates by time.

## Language/Translation Policy

English should be first. Russian, Chinese, Spanish, and Portuguese can be added
later if a source requires them.

Policy:

- store `language` per article;
- keep original title/summary where licensing allows;
- do not translate in the first schema/collector;
- future translation output should be separate metadata with versioning;
- event extraction should not depend on undocumented translation behavior.

## Noise/False-Positive Policy

The first GDELT/news prototype should measure and report false positives before
production scale-up.

Risks:

- commodity terms are ambiguous;
- syndicated stories can create repeated counts;
- search APIs can return loosely related articles;
- generic agriculture news can drown product-specific signals;
- source country and event country may differ.

Mitigations:

- start with official reports and narrow keyword rules;
- store extraction method/version;
- keep confidence explicit;
- use missing/noise flags in daily features;
- require review before adding broad crawling or paid/commercial feeds.

## Storage/Rate-Limit Policy

Future collectors must be bounded:

- small date windows;
- explicit keyword/source filters;
- request timeouts;
- response size limits;
- low retry counts;
- raw storage monitoring;
- no article body storage unless licensing allows it.

Paid/commercial APIs require separate license review before automated
collection.

## Phase 6.4D GDELT Collector Policy

The first implemented news collector uses GDELT 2.1 DOC `ArtList` responses via
`https://api.gdeltproject.org/api/v2/doc/doc`.

Supported query presets:

| query_key | commodity_family | affected products | notes |
| --- | --- | --- | --- |
| `soybean` | `soybean` | `soybean_oil`, `soybean_meal` | Soybean, soybean oil, and soybean meal context. |
| `rapeseed_canola` | `rapeseed` | `rapeseed_oil`, `rapeseed_meal` | Rapeseed/canola market context. |
| `vegetable_oils` | `vegetable_oils` | `soybean_oil`, `rapeseed_oil` | Palm/edible oil substitution context. |
| `grain_oilseed_policy` | `policy_context` | all current products | Policy, weather, logistics, Black Sea, and biofuel context. |

Limits:

- require `--query-key` or `--query`;
- require `--from-date` and `--to-date`;
- maximum inclusive date range: 7 days;
- maximum `maxrecords`: 100;
- explicit timeout and user agent;
- no scheduler.

Identity and dedup:

- use source stable IDs only when GDELT provides one;
- otherwise use normalized URL identity in `article_hash`;
- store changed title/summary/source metadata in `source_record_hash`;
- unchanged retries increment `skipped_existing`;
- changed existing identities create `news_existing_article_hash_changed`
  warnings and are not overwritten in Phase 6.4D.

The collector stores metadata only. It does not fetch or store article bodies
from publisher pages.

## Phase 6.4E Rule-Based Event Extraction

Phase 6.4E adds a local/manual extractor:

```bash
python scripts/extract_news_events.py --from-date 2026-06-01 --to-date 2026-06-03 --dry-run
python scripts/extract_news_events.py --from-date 2026-06-01 --to-date 2026-06-03 --source gdelt_2_1
python scripts/extract_news_events.py --from-date 2026-06-01 --to-date 2026-06-03 --article-id 123
```

It scans only existing `news_articles` rows in the requested `published_at`
date range. `--dry-run` reports candidates without writing `commodity_events`
or quality checks.

Implemented event categories:

- `export_restriction`
- `import_policy`
- `war_logistics_disruption`
- `weather_disaster`
- `crop_report`
- `biofuel_policy`
- `energy_shock`
- `currency_macro`
- `demand_shock`
- `supply_chain`

Implemented commodity families:

- `soybean`
- `rapeseed`
- `vegetable_oils`
- `grains`
- `fertilizer_energy`

Each event stores:

- `extraction_method = keyword_rule`;
- `extraction_version = news_event_rules_v1`;
- `source_text_hash` from normalized title/summary/body text;
- matched keywords, matched rule names, affected product codes, and known
  limitations in `metadata_json`.

The first rule set is deliberately English-first and conservative. A candidate
requires at least one event-category rule and at least one commodity-family rule
to match the article title/summary/body fields that are already present in the
database. It is not sentiment analysis, not an NLP classifier, and not an LLM
classifier.

Idempotency policy:

- unchanged reruns increment `skipped_existing`;
- changed text/rule output for an existing event identity creates
  `commodity_event_existing_rule_hash_changed` with warning severity;
- existing events are not overwritten in Phase 6.4E.

Quality checks include article presence, text presence, category detection,
commodity-family detection, publication timestamp, event date, confidence,
source text hash, insert confirmation, and rule-hash conflict warnings. `skip`
checks for unrelated articles are expected and are not failures.

Known limitations:

- rules are keyword-based and can miss implicit events;
- country/region are copied from the article metadata and may represent source
  country rather than event country;
- language coverage is English-first;
- no cross-source article deduplication is attempted here;
- daily feature aggregation is intentionally deferred to Phase 6.4F.

## Phase 6.4F Daily News/Event Features

Phase 6.4F implements the first deterministic daily product-level news/event
feature builder:

```bash
python scripts/build_features.py news_daily
python scripts/build_features.py news_daily --from-date 2026-06-01 --to-date 2026-06-10
python scripts/build_features.py news_daily --product soybean_oil --from-date 2026-06-01 --to-date 2026-06-10
python scripts/build_features.py daily
```

The `news_daily` command writes `daily_news_features` from already stored
`news_articles` and `commodity_events`. It does not call GDELT, does not fetch
article bodies, does not run collectors, does not register a scheduler, and
does not add ML/NLP/LLM classification.

Computed fields:

- `news_count_1d`, `news_count_7d`, `news_count_30d`;
- `event_count_1d`, `event_count_7d`, `event_count_30d`;
- `bullish_event_count_7d`, `bearish_event_count_7d`,
  `mixed_event_count_7d`;
- 30-day category counts for export/import policy, war/logistics, weather,
  crop reports, biofuel, energy, demand, and supply-chain events;
- `sentiment_proxy_7d`;
- `news_as_of_date`;
- `missing_flags` and `metadata_json`.

Rolling windows are backward-looking only:

- 1d: `feature_date`;
- 7d: `feature_date - 6 days` through `feature_date`;
- 30d: `feature_date - 29 days` through `feature_date`.

Leakage policy:

- article counts use only `published_at.date() <= feature_date`;
- event counts use only `event_date <= feature_date` and
  `published_at.date() <= feature_date`;
- `news_as_of_date` must be `<= feature_date`;
- `daily_product_features` copies news fields only when that as-of rule holds.

Product mapping:

- soybean products use soybean events and article hints;
- rapeseed/canola products use rapeseed/canola events and article hints;
- `vegetable_oils` events apply to oil products;
- `fertilizer_energy` and broad policy context can apply to all current
  production products.

`sentiment_proxy_7d` is:

```text
(bullish_event_count_7d - bearish_event_count_7d) / max(event_count_7d, 1)
```

It is stored as `NULL` when there are no 7-day events, because zero should mean
a balanced bullish/bearish mix rather than missing event coverage.

Phase 6.4F also adds nullable product-level news/event columns to
`daily_product_features` through Alembic revision
`0015_product_news_features` and includes those columns in export v1.

## Future Feature Integration Into Daily Product Features

Phase 6.4F joins product-level news aggregates from `daily_news_features` into
nullable `daily_product_features` columns.

Candidate columns for later product features:

- `news_count_7d`
- `news_count_30d`
- `crop_report_count_30d`
- `export_restriction_count_30d`
- `weather_disaster_count_30d`
- `war_logistics_count_30d`
- `bullish_event_count_7d`
- `bearish_event_count_7d`
- `news_as_of_date`
- `news_missing_flags`

Rules:

- product mapping should use `product_id` and `commodity_family`;
- rolling windows must use past `published_at` only;
- no future leakage;
- missing/source coverage flags must be explicit;
- source coverage should be documented in export metadata.

## Future Export Integration

Export v1 includes news fields after Phase 6.4F:

- schema migration `0015_product_news_features`;
- controlled collector raw evidence in `news_articles`;
- versioned event extraction rules in `commodity_events`;
- `daily_news_features` product-level aggregates;
- leakage checks requiring `news_as_of_date <= feature_date`;
- manifest source coverage and limitations.

## Migration Plan For Next Phase

Phase 6.4C implements schema-only support:

- SQLAlchemy metadata for `news_articles`, `commodity_events`, and
  `daily_news_features`;
- Alembic revision `0014_news_events_schema`;
- idempotent source seeds for `gdelt_2_1`, `usda_reports`,
  `fao_news_releases`, and `world_bank_commodity_releases`;
- operational report counts that treat empty tables as normal.

Phase 6.4C must not implement collectors, run collectors, register schedulers,
write news rows, add ML targets, or add NLP/LLM classifiers.

Phase 6.4D implements only the GDELT metadata collector:

- collector config and parser under `app/collectors/news/`;
- CLI support through `python scripts/run_collector.py gdelt_news`;
- mocked tests for parsing, validation, idempotency, raw linkage, quality
  checks, and operational report visibility.

Phase 6.4D must not write `commodity_events`, must not build
`daily_news_features`, must not register a scheduler, must not add ML targets,
and must not add NLP/LLM classifiers.

Phase 6.4E implements only rule-based event extraction:

- local/manual CLI support through `python scripts/extract_news_events.py`;
- versioned rules in `app/features/news_event_rules.py`;
- deterministic extraction logic in `app/features/news_events.py`;
- mocked tests for taxonomy, matching, idempotency, conflict warnings, dry-run,
  CLI validation, and operational report visibility.

Phase 6.4E must not call external news APIs, must not run GDELT collection, must
not build `daily_news_features`, must not register a scheduler, must not add ML
targets, and must not add NLP/LLM classifiers.

Phase 6.4F implements only daily news/event feature aggregation and export
integration:

- builder in `app/features/news_daily.py`;
- CLI support through `python scripts/build_features.py news_daily`;
- nullable product-level columns on `daily_product_features`;
- export v1 news/event columns;
- tests for windows, mapping, leakage, idempotency, CLI, export, and reports.

Phase 6.4F must not call external news APIs, must not run GDELT collection, must
not register a scheduler, must not add ML targets, and must not add NLP/LLM
classifiers.

## Non-Goals

- No migration in Phase 6.4B.
- No SQLAlchemy model changes in Phase 6.4B.
- No collector in Phase 6.4B.
- No DB writes in Phase 6.4B.
- No scheduler changes in Phase 6.4B.
- No ML in Phase 6.4B.
- No targets in Phase 6.4B.
- No LLM classifier in Phase 6.4B.
- No event extraction in Phase 6.4D.
- No `commodity_events` writes in Phase 6.4D.
- No news scheduler in Phase 6.4D.
- No external news API calls in Phase 6.4E.
- No `daily_news_features` writes in Phase 6.4E.
- No news/event export integration in Phase 6.4E.
- No news scheduler in Phase 6.4E.
- No ML/NLP/LLM classifier in Phase 6.4E.
- No external news API calls in Phase 6.4F.
- No news scheduler in Phase 6.4F.
- No ML/NLP/LLM classifier in Phase 6.4F.
- No targets in Phase 6.4F.
