from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


CandidateStatus = Literal[
    "ready_to_prototype",
    "ready_to_probe",
    "needs_manual_check",
    "high_risk",
    "paid_later",
    "reject",
]
SourceType = Literal["rss", "api", "report_page", "search_feed", "commercial"]
DirectionHint = Literal["bullish", "bearish", "mixed", "unknown"]

VALID_CANDIDATE_STATUSES = {
    "ready_to_prototype",
    "ready_to_probe",
    "needs_manual_check",
    "high_risk",
    "paid_later",
    "reject",
}
VALID_SOURCE_TYPES = {"rss", "api", "report_page", "search_feed", "commercial"}
VALID_DIRECTION_HINTS = {"bullish", "bearish", "mixed", "unknown"}
OUTPUT_DIR = Path("diagnostics/news_source_audit")


@dataclass(frozen=True)
class EventTaxonomyItem:
    event_category: str
    affected_commodity_family: tuple[str, ...]
    expected_direction_hint: DirectionHint
    expected_lag_days: str
    useful_text_fields: tuple[str, ...]
    why_useful_for_ml: str

    def __post_init__(self) -> None:
        if self.expected_direction_hint not in VALID_DIRECTION_HINTS:
            raise ValueError(f"invalid expected_direction_hint: {self.expected_direction_hint}")
        if not self.affected_commodity_family:
            raise ValueError("affected_commodity_family must not be empty")


@dataclass(frozen=True)
class NewsSourceCandidate:
    source_name: str
    source_url: str
    candidate_status: CandidateStatus
    source_type: SourceType
    auth_required: bool
    format: str
    expected_fields: tuple[str, ...]
    historical_depth: str
    rate_limits: str
    license_notes: str
    operational_risk: str
    noise_risk: str
    language: str
    regions_covered: tuple[str, ...]
    commodity_relevance: str
    recommended_next_action: str

    def __post_init__(self) -> None:
        if self.candidate_status not in VALID_CANDIDATE_STATUSES:
            raise ValueError(f"invalid candidate_status: {self.candidate_status}")
        if self.source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"invalid source_type: {self.source_type}")
        if not self.expected_fields:
            raise ValueError("expected_fields must not be empty")


@dataclass(frozen=True)
class NewsSourceAudit:
    generated_at: str
    mode: str
    live_probing: str
    recommended_first_source: str
    recommended_first_event_layer: str
    event_taxonomy: tuple[EventTaxonomyItem, ...]
    candidates: tuple[NewsSourceCandidate, ...]
    data_model_proposal: tuple[str, ...]
    recommendations: tuple[str, ...]
    non_goals: tuple[str, ...]


def build_audit(*, generated_at: datetime | None = None, live_probe: bool = False) -> NewsSourceAudit:
    generated_at = generated_at or datetime.now(timezone.utc)
    candidates = source_candidates()
    first_source = recommended_first_source(candidates)
    return NewsSourceAudit(
        generated_at=generated_at.isoformat(),
        mode="inventory",
        live_probing="not_run_static_registry" if not live_probe else "not_supported_static_registry_only",
        recommended_first_source=first_source.source_name,
        recommended_first_event_layer=recommended_first_event_layer(),
        event_taxonomy=event_taxonomy(),
        candidates=candidates,
        data_model_proposal=data_model_proposal(),
        recommendations=recommendations(),
        non_goals=non_goals(),
    )


def event_taxonomy() -> tuple[EventTaxonomyItem, ...]:
    fields = ("title", "summary", "body", "source", "published_at", "country/region", "entities")
    return (
        EventTaxonomyItem(
            event_category="export_restriction",
            affected_commodity_family=("soybean", "rapeseed", "vegetable_oils", "grains"),
            expected_direction_hint="bullish",
            expected_lag_days="0-7",
            useful_text_fields=fields,
            why_useful_for_ml="Export duties, quotas, bans, or licensing can tighten tradable supply and move prices quickly.",
        ),
        EventTaxonomyItem(
            event_category="import_policy",
            affected_commodity_family=("soybean", "rapeseed", "vegetable_oils", "feed"),
            expected_direction_hint="mixed",
            expected_lag_days="1-30",
            useful_text_fields=fields,
            why_useful_for_ml="Import duties, quotas, and phytosanitary rules affect destination demand and substitution flows.",
        ),
        EventTaxonomyItem(
            event_category="war_logistics_disruption",
            affected_commodity_family=("rapeseed", "vegetable_oils", "grains", "fertilizer"),
            expected_direction_hint="bullish",
            expected_lag_days="0-7",
            useful_text_fields=fields,
            why_useful_for_ml="Port closures, Black Sea disruption, sanctions, or infrastructure attacks can affect supply chains immediately.",
        ),
        EventTaxonomyItem(
            event_category="weather_disaster",
            affected_commodity_family=("soybean", "rapeseed", "grains", "vegetable_oils"),
            expected_direction_hint="bullish",
            expected_lag_days="7-30",
            useful_text_fields=fields,
            why_useful_for_ml="Drought, flood, frost, heat, hurricane, or fire events can change crop expectations before official reports.",
        ),
        EventTaxonomyItem(
            event_category="crop_report",
            affected_commodity_family=("soybean", "rapeseed", "grains", "feed"),
            expected_direction_hint="mixed",
            expected_lag_days="0-7",
            useful_text_fields=fields,
            why_useful_for_ml="USDA/WASDE, PSD, production, stocks, and acreage revisions directly update supply/demand priors.",
        ),
        EventTaxonomyItem(
            event_category="biofuel_policy",
            affected_commodity_family=("soybean_oil", "vegetable_oils", "grains", "energy"),
            expected_direction_hint="mixed",
            expected_lag_days="7-30",
            useful_text_fields=fields,
            why_useful_for_ml="Biodiesel, ethanol, and renewable fuel mandates can shift vegetable oil and grain demand.",
        ),
        EventTaxonomyItem(
            event_category="energy_shock",
            affected_commodity_family=("vegetable_oils", "fertilizer", "logistics", "energy"),
            expected_direction_hint="mixed",
            expected_lag_days="0-7",
            useful_text_fields=fields,
            why_useful_for_ml="Oil, gas, diesel, and fertilizer shocks affect biofuel parity, transport costs, and crop input economics.",
        ),
        EventTaxonomyItem(
            event_category="currency_macro",
            affected_commodity_family=("soybean", "rapeseed", "vegetable_oils", "grains"),
            expected_direction_hint="mixed",
            expected_lag_days="0-7",
            useful_text_fields=fields,
            why_useful_for_ml="Currency moves, inflation, rates, and macro shocks change export competitiveness and import demand.",
        ),
        EventTaxonomyItem(
            event_category="demand_shock",
            affected_commodity_family=("soybean", "meal", "vegetable_oils", "feed"),
            expected_direction_hint="mixed",
            expected_lag_days="1-30",
            useful_text_fields=fields,
            why_useful_for_ml="China import swings, crush margins, livestock feed demand, and palm/soy substitution can move oilseed spreads.",
        ),
        EventTaxonomyItem(
            event_category="supply_chain",
            affected_commodity_family=("soybean", "rapeseed", "vegetable_oils", "grains", "fertilizer"),
            expected_direction_hint="bullish",
            expected_lag_days="0-7",
            useful_text_fields=fields,
            why_useful_for_ml="Freight, rail, port, container, or logistics disruptions change physical availability and basis pressure.",
        ),
    )


def source_candidates() -> tuple[NewsSourceCandidate, ...]:
    common_fields = ("external_id", "url", "title", "summary", "published_at", "source_name", "language")
    return (
        NewsSourceCandidate(
            source_name="GDELT 2.1 DOC/Event APIs",
            source_url="https://www.gdeltproject.org/",
            candidate_status="ready_to_prototype",
            source_type="api",
            auth_required=False,
            format="JSON/CSV",
            expected_fields=common_fields + ("source_country", "themes", "locations"),
            historical_depth="Large global archive; exact query windows and API modes must be bounded in prototype.",
            rate_limits="Public API; use small date windows, strict query filters, caching, and low request volume.",
            license_notes="Review GDELT terms and downstream article licensing; store metadata and source URLs, not republished full articles.",
            operational_risk="medium",
            noise_risk="high",
            language="multilingual/global",
            regions_covered=("global", "Black Sea", "Americas", "Europe", "China"),
            commodity_relevance="Broad coverage for policy, conflict, disasters, logistics, and macro events with heavy filtering needs.",
            recommended_next_action="Prototype a narrow query set for event categories and commodity keywords; measure noise before schema implementation.",
        ),
        NewsSourceCandidate(
            source_name="USDA RSS and report release pages",
            source_url="https://www.usda.gov/media/agency-reports",
            candidate_status="ready_to_probe",
            source_type="rss",
            auth_required=False,
            format="RSS/XML and HTML report pages",
            expected_fields=common_fields + ("report_type",),
            historical_depth="Official releases and report pages; RSS depth may be limited, but report archives are available separately.",
            rate_limits="Low-frequency official pages; use polite bounded checks.",
            license_notes="Official US government content; preserve attribution and source URLs.",
            operational_risk="low",
            noise_risk="medium",
            language="English",
            regions_covered=("United States", "global"),
            commodity_relevance="High for crop_report, WASDE/PSD context, acreage, stocks, and export policy news.",
            recommended_next_action="Probe RSS/report feeds and design a report-page collector before generic news ingestion.",
        ),
        NewsSourceCandidate(
            source_name="USDA WASDE / PSD report pages",
            source_url="https://www.usda.gov/oce/commodity/wasde",
            candidate_status="ready_to_probe",
            source_type="report_page",
            auth_required=False,
            format="HTML/PDF/XLS links",
            expected_fields=common_fields + ("report_period", "file_url"),
            historical_depth="Regular official report history; PDF/XLS parsing should be a later controlled phase.",
            rate_limits="Monthly/low frequency; bounded manual collection is feasible.",
            license_notes="Official report data; preserve source URLs and publication dates.",
            operational_risk="medium",
            noise_risk="low",
            language="English",
            regions_covered=("global", "United States"),
            commodity_relevance="Very high for structured crop_report events and supply/demand revisions.",
            recommended_next_action="Design as first event/report layer alongside GDELT metadata, without NLP classifier.",
        ),
        NewsSourceCandidate(
            source_name="FAO news and Food Price Index releases",
            source_url="https://www.fao.org/newsroom/",
            candidate_status="needs_manual_check",
            source_type="rss",
            auth_required=False,
            format="RSS/XML or HTML",
            expected_fields=common_fields + ("topic",),
            historical_depth="News/release archive depth varies by feed/page.",
            rate_limits="Low-frequency official site; use polite bounded requests.",
            license_notes="Review FAO reuse and attribution terms.",
            operational_risk="low_to_medium",
            noise_risk="medium",
            language="multilingual/English",
            regions_covered=("global",),
            commodity_relevance="Useful for food price, crop condition, policy, and humanitarian/agricultural context.",
            recommended_next_action="Manual-check RSS availability and release archive structure.",
        ),
        NewsSourceCandidate(
            source_name="World Bank commodity market news/blogs",
            source_url="https://blogs.worldbank.org/",
            candidate_status="needs_manual_check",
            source_type="rss",
            auth_required=False,
            format="RSS/XML or HTML",
            expected_fields=common_fields + ("topic", "author"),
            historical_depth="Blog/news archive available, but topic filtering needs manual review.",
            rate_limits="Low-frequency; cache and avoid broad crawling.",
            license_notes="Review World Bank content reuse and attribution.",
            operational_risk="low_to_medium",
            noise_risk="medium",
            language="English",
            regions_covered=("global",),
            commodity_relevance="Useful for macro, commodity outlook, food security, energy/fertilizer linkage.",
            recommended_next_action="Manual-check feed URLs and commodity-market tags.",
        ),
        NewsSourceCandidate(
            source_name="ReliefWeb disasters and updates",
            source_url="https://reliefweb.int/",
            candidate_status="needs_manual_check",
            source_type="api",
            auth_required=False,
            format="JSON API/RSS",
            expected_fields=common_fields + ("disaster_type", "country", "source"),
            historical_depth="Disaster/event history available; agriculture-specific relevance must be filtered.",
            rate_limits="Public API; bounded keyword/country windows required.",
            license_notes="Content comes from many sources; preserve original source and review reuse terms.",
            operational_risk="medium",
            noise_risk="medium_to_high",
            language="multilingual/English",
            regions_covered=("global",),
            commodity_relevance="Useful for weather_disaster and logistics/humanitarian disruptions with crop-region filtering.",
            recommended_next_action="Prototype only after event taxonomy/schema design; start with drought/flood/frost keywords and crop regions.",
        ),
        NewsSourceCandidate(
            source_name="Google News RSS-style search feeds",
            source_url="https://news.google.com/rss/search",
            candidate_status="high_risk",
            source_type="search_feed",
            auth_required=False,
            format="RSS/XML",
            expected_fields=common_fields,
            historical_depth="Search results are dynamic and not a stable historical source.",
            rate_limits="Unofficial for systematic collection; avoid aggressive or production scraping.",
            license_notes="High policy and licensing risk; do not republish article content.",
            operational_risk="high",
            noise_risk="high",
            language="multilingual",
            regions_covered=("global",),
            commodity_relevance="Potential discovery aid, but not a preferred production data source.",
            recommended_next_action="Use only as manual discovery aid, not production collector, unless policy is reviewed.",
        ),
        NewsSourceCandidate(
            source_name="NewsAPI / paid news APIs",
            source_url="https://newsapi.org/",
            candidate_status="paid_later",
            source_type="api",
            auth_required=True,
            format="JSON API",
            expected_fields=common_fields + ("provider",),
            historical_depth="Depends on plan; often limited without paid access.",
            rate_limits="API-key and plan-specific.",
            license_notes="Commercial terms may restrict storage/export and derived datasets.",
            operational_risk="medium",
            noise_risk="medium",
            language="provider dependent",
            regions_covered=("global",),
            commodity_relevance="Useful if budget/licensing allow stable searchable news ingestion.",
            recommended_next_action="Defer until free official/GDELT/report routes are evaluated.",
        ),
        NewsSourceCandidate(
            source_name="TradingEconomics / commercial commodity news",
            source_url="https://tradingeconomics.com/",
            candidate_status="high_risk",
            source_type="commercial",
            auth_required=True,
            format="API/HTML depending on plan",
            expected_fields=common_fields + ("commodity",),
            historical_depth="Plan/license dependent.",
            rate_limits="Commercial plan dependent; scraping risk if no API contract.",
            license_notes="High licensing risk for redistribution and automated collection without contract.",
            operational_risk="high",
            noise_risk="medium",
            language="English",
            regions_covered=("global",),
            commodity_relevance="Potentially useful but not appropriate for first open-source-like collector without licensing.",
            recommended_next_action="Reject scraping; revisit only if an API/license is approved.",
        ),
    )


def recommended_first_source(candidates: tuple[NewsSourceCandidate, ...] | None = None) -> NewsSourceCandidate:
    candidates = candidates or source_candidates()
    for candidate in candidates:
        if candidate.source_name == "GDELT 2.1 DOC/Event APIs":
            return candidate
    return candidates[0]


def recommended_first_event_layer() -> str:
    return "official_report_events_usda_wasde_psd_plus_gdelt_metadata_prototype"


def data_model_proposal() -> tuple[str, ...]:
    return (
        "Use existing sources table for source registry; add news-specific tables only after schema design.",
        "news_articles: source/raw/run links, external_id, url, title, summary, body_text, language, published_at, fetched_at, region/country, hashes, metadata.",
        "commodity_events: article link, event_category, commodity_family, affected_products, country/region, event_date, published_at, confidence, direction_hint, severity, lag_bucket, extraction_method, metadata.",
        "daily_news_features: product or family/date aggregates such as counts over 1/7/30 days, category counts, direction counts, sentiment proxy, news_as_of_date, missing_flags.",
    )


def recommendations() -> tuple[str, ...]:
    return (
        "Phase 6.4B should design news/event schema before any production writes.",
        "Start with official report/release events and GDELT metadata; avoid broad article scraping.",
        "Do not implement an NLP/LLM classifier in the source discovery phase.",
        "Use published_at and fetched_at explicitly to avoid news backfill leakage.",
        "Treat Google News RSS and commercial pages as high-risk unless policy/licensing is reviewed.",
        "Store raw evidence in future production collectors; this phase writes diagnostics artifacts only.",
    )


def non_goals() -> tuple[str, ...]:
    return (
        "No production DB writes.",
        "No collectors.",
        "No scheduler changes.",
        "No migrations.",
        "No RawStore writes.",
        "No ML model.",
        "No targets.",
        "No LLM classifier.",
    )


def write_audit_outputs(audit: NewsSourceAudit, output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "news_source_candidates.json").write_text(
        json.dumps(audit_to_dict(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "NEWS_SOURCE_AUDIT_REPORT.md").write_text(render_report(audit), encoding="utf-8")


def render_report(audit: NewsSourceAudit) -> str:
    counts = count_by_status(audit.candidates)
    lines = [
        "# News And Event Source Audit",
        "",
        "## Executive Summary",
        "",
        "Phase 6.4A is local diagnostics/design-only. It does not write PostgreSQL rows, does not create collectors, does not use RawStore, does not change scheduler settings, does not add ML targets, and does not add an NLP/LLM classifier.",
        "",
        f"Live probing: `{audit.live_probing}`. This report uses a curated static registry and performs no HTTP requests.",
        "",
        f"Recommended first source: `{audit.recommended_first_source}`.",
        "",
        f"Recommended first event/report layer: `{audit.recommended_first_event_layer}`.",
        "",
        "## Why News And Events Matter",
        "",
        "News and official event releases can move agricultural commodity prices before slower monthly datasets update. Export restrictions, crop reports, Black Sea logistics, weather disasters, biofuel policy, energy shocks, currency moves, and demand shocks are all plausible drivers for soybean, rapeseed/canola, vegetable oil, meal/feed, grain, energy, and fertilizer context.",
        "",
        "## Product And Commodity Families Covered",
        "",
        "- soybean: soybean oil and soybean meal.",
        "- rapeseed/canola: rapeseed oil and rapeseed meal.",
        "- vegetable oils and meals/feed as substitution families.",
        "- grains, fertilizer, and energy as linked context families.",
        "",
        "## Event Taxonomy",
        "",
        "| category | families | direction | lag | why useful |",
        "|---|---|---|---|---|",
    ]
    for item in audit.event_taxonomy:
        lines.append(
            "| {category} | {families} | {direction} | {lag} | {why} |".format(
                category=item.event_category,
                families=", ".join(item.affected_commodity_family),
                direction=item.expected_direction_hint,
                lag=item.expected_lag_days,
                why=item.why_useful_for_ml,
            )
        )

    lines.extend(
        [
            "",
            "## Candidate Source Table",
            "",
            "| source | status | type | auth | format | operational risk | noise risk | next action |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for candidate in audit.candidates:
        lines.append(
            "| {source} | {status} | {source_type} | {auth} | {fmt} | {op} | {noise} | {action} |".format(
                source=candidate.source_name,
                status=candidate.candidate_status,
                source_type=candidate.source_type,
                auth="yes" if candidate.auth_required else "no",
                fmt=candidate.format,
                op=candidate.operational_risk,
                noise=candidate.noise_risk,
                action=candidate.recommended_next_action,
            )
        )

    lines.extend(
        [
            "",
            "## Recommended First Source",
            "",
            "Use GDELT 2.1 as the first broad metadata prototype because it is public, global, and event/news oriented. Keep the prototype narrow: bounded date windows, commodity/event keywords, no article body republishing, and strict noise measurement.",
            "",
            "## Recommended First Event/Report Layer",
            "",
            "Use official report/release events as the first low-noise event layer: USDA WASDE/PSD/release pages, FAO releases, and World Bank commodity outlook/release pages. This should be modeled as report/event metadata first, not as a generic web crawler.",
            "",
            "## Source-By-Source Analysis",
            "",
        ]
    )
    for candidate in audit.candidates:
        lines.extend(
            [
                f"### {candidate.source_name}",
                "",
                f"- URL: {candidate.source_url}",
                f"- Status: `{candidate.candidate_status}`",
                f"- Source type: {candidate.source_type}",
                f"- Auth required: {candidate.auth_required}",
                f"- Format: {candidate.format}",
                f"- Expected fields: {', '.join(candidate.expected_fields)}",
                f"- Historical depth: {candidate.historical_depth}",
                f"- Rate limits: {candidate.rate_limits}",
                f"- License notes: {candidate.license_notes}",
                f"- Operational risk: {candidate.operational_risk}",
                f"- Noise risk: {candidate.noise_risk}",
                f"- Language: {candidate.language}",
                f"- Regions covered: {', '.join(candidate.regions_covered)}",
                f"- Commodity relevance: {candidate.commodity_relevance}",
                f"- Recommended next action: {candidate.recommended_next_action}",
                "",
            ]
        )

    lines.extend(
        [
            "## Data Model Proposal",
            "",
        ]
    )
    for item in audit.data_model_proposal:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Deduplication Policy",
            "",
            "- Deduplicate articles by canonical URL when available.",
            "- Also store `external_id` and `source_record_hash` because feeds/search APIs can emit duplicate or rewritten URLs.",
            "- Event rows should dedupe by article/event category/commodity family/country/event date when confidence is high.",
            "- Search API results can change historically; future collectors must store raw evidence.",
            "",
            "## As-Of And Leakage Policy",
            "",
            "- Use only articles/events with `published_at <= feature_date`.",
            "- Use `fetched_at` for realistic `as_collected` dataset mode.",
            "- Backfilled news must not be used in realistic simulation before it was fetched.",
            "- Do not use article update time after `feature_date` unless an explicit policy allows it.",
            "- Store raw source responses for reproducibility and leakage audits.",
            "",
            "## Language And Translation Risks",
            "",
            "- GDELT and international sources are multilingual; translation can add noise and latency.",
            "- First collectors should keep original title/summary/language and avoid lossy translation-dependent labels.",
            "- Country/region/entity extraction should be explicit and auditable.",
            "",
            "## Noise And False-Positive Risks",
            "",
            "- Commodity terms are ambiguous; oil, meal, crush, and rapeseed/canola need careful keyword filtering.",
            "- Broad global news feeds can overcount repeated syndicated stories.",
            "- Event extraction should start rule-based and reviewable before any ML/LLM classifier.",
            "",
            "## Storage And Rate-Limit Risks",
            "",
            "- Store metadata and short excerpts/summary fields first; do not republish full article bodies unless licensing allows it.",
            "- Keep request windows bounded and cache raw feed/API responses in future production collectors.",
            "- Paid/commercial APIs require explicit license review before use.",
            "",
            "## Proposed Future Phases",
            "",
            "- Phase 6.4B: news/events schema design.",
            "- Phase 6.4C: schema implementation.",
            "- Phase 6.4D: first controlled news/report collector.",
            "- Phase 6.4E: event extraction/rule labeling.",
            "- Phase 6.4F: daily news/event features/export integration.",
            "",
            "## Recommendations",
            "",
        ]
    )
    for item in audit.recommendations:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Non-Goals",
            "",
        ]
    )
    for item in audit.non_goals:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Status Counts",
            "",
        ]
    )
    for status, count in sorted(counts.items()):
        lines.append(f"- `{status}`: {count}")

    return "\n".join(lines) + "\n"


def audit_to_dict(audit: NewsSourceAudit) -> dict[str, Any]:
    return {
        "generated_at": audit.generated_at,
        "mode": audit.mode,
        "live_probing": audit.live_probing,
        "recommended_first_source": audit.recommended_first_source,
        "recommended_first_event_layer": audit.recommended_first_event_layer,
        "event_taxonomy": [taxonomy_to_dict(item) for item in audit.event_taxonomy],
        "candidates": [candidate_to_dict(item) for item in audit.candidates],
        "data_model_proposal": list(audit.data_model_proposal),
        "recommendations": list(audit.recommendations),
        "non_goals": list(audit.non_goals),
    }


def taxonomy_to_dict(item: EventTaxonomyItem) -> dict[str, Any]:
    data = asdict(item)
    data["affected_commodity_family"] = list(item.affected_commodity_family)
    data["useful_text_fields"] = list(item.useful_text_fields)
    return data


def candidate_to_dict(candidate: NewsSourceCandidate) -> dict[str, Any]:
    data = asdict(candidate)
    data["expected_fields"] = list(candidate.expected_fields)
    data["regions_covered"] = list(candidate.regions_covered)
    return data


def count_by_status(candidates: tuple[NewsSourceCandidate, ...] | None = None) -> dict[str, int]:
    counts = {status: 0 for status in VALID_CANDIDATE_STATUSES}
    for candidate in candidates or source_candidates():
        counts[candidate.candidate_status] += 1
    return {status: count for status, count in counts.items() if count > 0}
