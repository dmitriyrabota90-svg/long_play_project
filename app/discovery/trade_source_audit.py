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
    "high_complexity",
    "paid_later",
    "high_risk",
    "reject",
]
SourceType = Literal["api", "csv", "bulk_download", "report", "commercial"]
Relevance = Literal["direct", "context", "later"]

VALID_CANDIDATE_STATUSES = {
    "ready_to_prototype",
    "ready_to_probe",
    "needs_manual_check",
    "high_complexity",
    "paid_later",
    "high_risk",
    "reject",
}
VALID_SOURCE_TYPES = {"api", "csv", "bulk_download", "report", "commercial"}
VALID_RELEVANCE = {"direct", "context", "later"}
OUTPUT_DIR = Path("diagnostics/trade_source_audit")


@dataclass(frozen=True)
class HSCodeMapping:
    commodity_family: str
    product_code: str | None
    hs_code: str
    hs_description: str
    relevance: Relevance
    notes: str

    def __post_init__(self) -> None:
        if self.relevance not in VALID_RELEVANCE:
            raise ValueError(f"invalid relevance: {self.relevance}")
        if not self.hs_code:
            raise ValueError("hs_code must not be empty")
        if not self.commodity_family:
            raise ValueError("commodity_family must not be empty")


@dataclass(frozen=True)
class TradeSourceCandidate:
    source_name: str
    source_url: str
    candidate_status: CandidateStatus
    source_type: SourceType
    auth_required: bool
    format: str
    frequency: str
    historical_depth: str
    commodity_granularity: str
    country_partner_support: str
    rate_limits: str
    license_notes: str
    operational_risk: str
    storage_risk: str
    as_of_risk: str
    ml_value: str
    recommended_next_action: str

    def __post_init__(self) -> None:
        if self.candidate_status not in VALID_CANDIDATE_STATUSES:
            raise ValueError(f"invalid candidate_status: {self.candidate_status}")
        if self.source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"invalid source_type: {self.source_type}")
        if not self.source_name:
            raise ValueError("source_name must not be empty")
        if not self.source_url:
            raise ValueError("source_url must not be empty")


@dataclass(frozen=True)
class TradeSourceAudit:
    generated_at: str
    mode: str
    live_probing: str
    recommended_first_source: str
    recommended_first_prototype_scope: str
    hs_code_mappings: tuple[HSCodeMapping, ...]
    candidates: tuple[TradeSourceCandidate, ...]
    feature_candidates: tuple[str, ...]
    data_model_proposal: tuple[str, ...]
    recommendations: tuple[str, ...]
    non_goals: tuple[str, ...]


def build_audit(*, generated_at: datetime | None = None, live_probe: bool = False) -> TradeSourceAudit:
    generated_at = generated_at or datetime.now(timezone.utc)
    candidates = source_candidates()
    first_source = recommended_first_source(candidates)
    return TradeSourceAudit(
        generated_at=generated_at.isoformat(),
        mode="inventory",
        live_probing="not_run_static_registry" if not live_probe else "not_supported_static_registry_only",
        recommended_first_source=first_source.source_name,
        recommended_first_prototype_scope=recommended_first_prototype_scope(),
        hs_code_mappings=hs_code_mappings(),
        candidates=candidates,
        feature_candidates=feature_candidates(),
        data_model_proposal=data_model_proposal(),
        recommendations=recommendations(),
        non_goals=non_goals(),
    )


def hs_code_mappings() -> tuple[HSCodeMapping, ...]:
    return (
        HSCodeMapping(
            commodity_family="soybean",
            product_code=None,
            hs_code="1201",
            hs_description="Soya beans, whether or not broken",
            relevance="direct",
            notes="Primary soybean seed trade code; useful for China import demand and Brazil/US/Argentina export proxy.",
        ),
        HSCodeMapping(
            commodity_family="soybean_oil",
            product_code="soybean_oil",
            hs_code="1507",
            hs_description="Soya-bean oil and its fractions",
            relevance="direct",
            notes="Direct oil product family mapping; subcodes may separate crude and refined oil by source.",
        ),
        HSCodeMapping(
            commodity_family="soybean_meal",
            product_code="soybean_meal",
            hs_code="2304",
            hs_description="Oilcake and other solid residues resulting from extraction of soya-bean oil",
            relevance="direct",
            notes="Direct meal/oilcake mapping; important for feed demand and crush-product exports.",
        ),
        HSCodeMapping(
            commodity_family="rapeseed_canola",
            product_code=None,
            hs_code="1205",
            hs_description="Rape or colza seeds, whether or not broken",
            relevance="direct",
            notes="Primary rapeseed/canola seed trade code; useful for Canada, EU, Ukraine, and China flows.",
        ),
        HSCodeMapping(
            commodity_family="rapeseed_oil",
            product_code="rapeseed_oil",
            hs_code="1514",
            hs_description="Rape, colza or mustard oil and fractions thereof",
            relevance="direct",
            notes="Direct rapeseed/canola oil mapping; subcodes and mustard oil inclusion need source-specific review.",
        ),
        HSCodeMapping(
            commodity_family="rapeseed_meal",
            product_code="rapeseed_meal",
            hs_code="2306",
            hs_description="Oilcake and other solid residues from vegetable fats or oils, other than soya-bean",
            relevance="direct",
            notes="Rapeseed/canola meal can appear under HS 2306 subcodes; exact subcode granularity must be verified per source.",
        ),
        HSCodeMapping(
            commodity_family="palm_oil",
            product_code=None,
            hs_code="1511",
            hs_description="Palm oil and its fractions",
            relevance="context",
            notes="Major substitute vegetable oil; useful for broader oil spread and substitution features.",
        ),
        HSCodeMapping(
            commodity_family="sunflower_oil",
            product_code=None,
            hs_code="1512",
            hs_description="Sunflower-seed, safflower or cotton-seed oil and fractions thereof",
            relevance="context",
            notes="Useful vegetable oil context even though sunflower production instruments are not in the current collector.",
        ),
        HSCodeMapping(
            commodity_family="wheat",
            product_code=None,
            hs_code="1001",
            hs_description="Wheat and meslin",
            relevance="context",
            notes="Broad grain/feed and Black Sea trade context.",
        ),
        HSCodeMapping(
            commodity_family="maize_corn",
            product_code=None,
            hs_code="1005",
            hs_description="Maize (corn)",
            relevance="context",
            notes="Feed and biofuel cross-market context.",
        ),
        HSCodeMapping(
            commodity_family="fertilizer",
            product_code=None,
            hs_code="3102/3103/3104/3105",
            hs_description="Nitrogen, phosphatic, potassic, and mixed fertilizers",
            relevance="later",
            notes="Input-cost and availability context; defer until trade layer is proven for core oilseed products.",
        ),
    )


def feature_candidates() -> tuple[str, ...]:
    return (
        "export_volume_monthly",
        "import_volume_monthly",
        "net_export_volume_monthly",
        "export_value_usd_monthly",
        "import_value_usd_monthly",
        "average_export_unit_value",
        "average_import_unit_value",
        "major_exporter_share",
        "major_importer_share",
        "china_import_demand_proxy",
        "brazil_usa_argentina_soybean_export_proxy",
        "canada_eu_ukraine_rapeseed_export_proxy",
        "export_import_3m_rolling_average",
        "export_import_yoy_change",
        "trade_balance_proxy",
        "reporting_lag_days",
        "trade_as_of_date",
        "missing_flags",
    )


def source_candidates() -> tuple[TradeSourceCandidate, ...]:
    return (
        TradeSourceCandidate(
            source_name="UN Comtrade",
            source_url="https://comtradeplus.un.org/",
            candidate_status="ready_to_probe",
            source_type="api",
            auth_required=True,
            format="JSON/CSV API and downloads",
            frequency="monthly and annual routes depending on endpoint/access",
            historical_depth="Deep global trade history; exact monthly depth should be checked during a bounded prototype.",
            commodity_granularity="HS commodity codes with reporter, partner, flow, quantity, and value fields.",
            country_partner_support="Global reporter/partner coverage; suitable for China import demand and major exporter proxies.",
            rate_limits="API subscription/key and rate limits may apply; prototype must use small reporter/partner/code windows.",
            license_notes="Review UN Comtrade terms, citation, and redistribution limits before exported dataset packaging.",
            operational_risk="medium",
            storage_risk="medium if broad country/code windows are downloaded; low for first narrow prototype.",
            as_of_risk="medium because trade revisions and publication lags require published/fetched timestamps.",
            ml_value="High; best first candidate for monthly bilateral commodity trade signals.",
            recommended_next_action="Phase 6.5B should design schema, then Phase 6.5D can prototype a narrow monthly query for HS 1201/1507/2304/1205/1514/2306 and selected countries.",
        ),
        TradeSourceCandidate(
            source_name="FAOSTAT trade and commodity domains",
            source_url="https://www.fao.org/faostat/",
            candidate_status="ready_to_prototype",
            source_type="api",
            auth_required=False,
            format="API/CSV bulk downloads",
            frequency="annual and domain-specific",
            historical_depth="Long official agricultural series; trade and production routes vary by domain.",
            commodity_granularity="FAOSTAT item codes rather than HS-only; mapping to product families needs manual review.",
            country_partner_support="Country coverage is strong, but partner/bilateral support depends on chosen domain.",
            rate_limits="Use bounded API/download calls and cache raw files.",
            license_notes="Review FAOSTAT terms and attribution; official data is useful but export redistribution policy must be preserved.",
            operational_risk="low_to_medium",
            storage_risk="low for annual narrow commodities; medium for broad bulk domains.",
            as_of_risk="medium because annual publication lag is large and revisions can occur.",
            ml_value="Medium to high as slower annual agricultural/trade context, weaker for short-term monthly movement.",
            recommended_next_action="Use as a stable annual context prototype after schema design, not as the first short-horizon monthly trade signal.",
        ),
        TradeSourceCandidate(
            source_name="USDA FAS / GATS / PSD",
            source_url="https://apps.fas.usda.gov/",
            candidate_status="needs_manual_check",
            source_type="api",
            auth_required=False,
            format="API, CSV, report, or database exports depending on route",
            frequency="monthly/annual/report-specific",
            historical_depth="Strong official agricultural history, especially oilseeds, grains, export sales, and PSD tables.",
            commodity_granularity="USDA commodity/product codes; HS/report code mapping needs source-specific design.",
            country_partner_support="Strong US and global agriculture coverage; exact partner support differs between GATS, PSD, and reports.",
            rate_limits="Use low-volume controlled requests; route-specific limits and file formats need manual verification.",
            license_notes="Official US government data, but preserve source URLs, release dates, and table metadata.",
            operational_risk="medium",
            storage_risk="medium because report/table formats differ.",
            as_of_risk="medium because report release schedules and revisions must be modeled.",
            ml_value="High later for soybean/corn/wheat/oilseed fundamentals and export context.",
            recommended_next_action="Manual-check stable machine-readable routes before choosing between GATS trade rows and PSD fundamentals.",
        ),
        TradeSourceCandidate(
            source_name="World Bank WITS",
            source_url="https://wits.worldbank.org/",
            candidate_status="needs_manual_check",
            source_type="api",
            auth_required=False,
            format="API/CSV depending on route",
            frequency="annual and source-dependent",
            historical_depth="Trade history available through WITS/Comtrade-linked routes; exact API behavior needs review.",
            commodity_granularity="HS codes and country/partner dimensions are available in WITS data models.",
            country_partner_support="Strong country/partner support, but query shape and documentation are more complex.",
            rate_limits="API and query limits need manual verification; use narrow code/country probes.",
            license_notes="Review World Bank/WITS and upstream trade-data licensing before redistribution.",
            operational_risk="medium_to_high",
            storage_risk="medium",
            as_of_risk="medium because upstream revisions/publication lag must be tracked.",
            ml_value="Medium to high as an alternative or supplement to UN Comtrade.",
            recommended_next_action="Manual-check API documentation after UN Comtrade prototype decision.",
        ),
        TradeSourceCandidate(
            source_name="ITC Trade Map",
            source_url="https://www.trademap.org/",
            candidate_status="paid_later",
            source_type="commercial",
            auth_required=True,
            format="Web/API/export depending on subscription",
            frequency="monthly/annual depending on access",
            historical_depth="Potentially rich trade data, but plan/access dependent.",
            commodity_granularity="HS and country/partner trade views likely available under license.",
            country_partner_support="High if licensed.",
            rate_limits="Commercial terms and access controls apply.",
            license_notes="High licensing risk; do not scrape or collect without approved subscription/API terms.",
            operational_risk="high",
            storage_risk="medium",
            as_of_risk="medium; publication/update dates must be captured if access is approved.",
            ml_value="High if licensed, but not suitable for the first open/controlled collector.",
            recommended_next_action="Defer until budget/licensing are explicitly approved; reject scraping.",
        ),
        TradeSourceCandidate(
            source_name="Eurostat Comext / international trade in goods",
            source_url="https://ec.europa.eu/eurostat/",
            candidate_status="needs_manual_check",
            source_type="api",
            auth_required=False,
            format="API/SDMX/TSV downloads",
            frequency="monthly and annual EU trade datasets",
            historical_depth="Deep EU trade history; exact dataset codes and dimensions need manual mapping.",
            commodity_granularity="CN/HS-like product codes with EU member state reporter/partner dimensions.",
            country_partner_support="Excellent EU coverage; weaker for non-EU global flows.",
            rate_limits="Use official API/download guidance and bounded product/country windows.",
            license_notes="Review Eurostat reuse requirements and metadata attribution.",
            operational_risk="medium",
            storage_risk="medium if many CN codes/member states are pulled.",
            as_of_risk="medium because monthly revisions and release calendars must be tracked.",
            ml_value="Medium to high for EU rapeseed/canola and vegetable oil trade context.",
            recommended_next_action="Manual-check dataset codes after the global first-source decision.",
        ),
        TradeSourceCandidate(
            source_name="National customs and statistics agencies",
            source_url="https://www.gov.br/mdic/; https://www.indec.gob.ar/; https://ised-isde.canada.ca/; customs/statistics portals",
            candidate_status="high_complexity",
            source_type="bulk_download",
            auth_required=False,
            format="CSV/XLS/API/report pages by country",
            frequency="monthly and country-specific",
            historical_depth="Potentially deep for Brazil, Argentina, Canada, China, EU/Ukraine, but heterogeneous.",
            commodity_granularity="HS or national tariff codes; mappings and language differ by country.",
            country_partner_support="High for individual reporter countries, but not harmonized globally.",
            rate_limits="Country-specific; use manual source-by-source design and avoid broad crawling.",
            license_notes="Country-specific reuse and attribution rules must be reviewed.",
            operational_risk="high",
            storage_risk="medium_to_high because formats and backfiles vary.",
            as_of_risk="high because publication calendars, revisions, and file replacement behavior vary by agency.",
            ml_value="High later for major exporters/importers, especially Brazil, Argentina, Canada, China, Ukraine, and EU.",
            recommended_next_action="Defer until the shared trade schema is proven with one global source.",
        ),
        TradeSourceCandidate(
            source_name="OECD / World Bank / IMF macro trade datasets",
            source_url="https://data-explorer.oecd.org/; https://data.worldbank.org/; https://www.imf.org/en/Data",
            candidate_status="needs_manual_check",
            source_type="api",
            auth_required=False,
            format="API/CSV/SDMX depending on source",
            frequency="monthly/quarterly/annual",
            historical_depth="Long macro series depending on dataset.",
            commodity_granularity="Usually macro trade aggregates, less commodity-specific than HS data.",
            country_partner_support="Country coverage is broad, but commodity detail is limited.",
            rate_limits="Source-specific; keep small requests and cache.",
            license_notes="Review each institution's terms and attribution.",
            operational_risk="medium",
            storage_risk="low_to_medium",
            as_of_risk="medium because release calendars and revisions matter.",
            ml_value="Medium as broad trade/macro context, not a direct oilseed import/export layer.",
            recommended_next_action="Use later for macro context after commodity-specific trade flows are implemented.",
        ),
    )


def recommended_first_source(candidates: tuple[TradeSourceCandidate, ...] | None = None) -> TradeSourceCandidate:
    candidates = candidates or source_candidates()
    for candidate in candidates:
        if candidate.source_name == "UN Comtrade":
            return candidate
    raise ValueError("UN Comtrade candidate is missing")


def recommended_first_prototype_scope() -> str:
    return (
        "UN Comtrade narrow monthly prototype for HS 1201, 1507, 2304, 1205, 1514, and 2306; "
        "reporters/partners focused on China import demand and Brazil, United States, Argentina, "
        "Canada, EU, and Ukraine export proxies."
    )


def data_model_proposal() -> tuple[str, ...]:
    return (
        "trade_commodity_codes: source and HS/source-code mapping by product family, relevance, units, and validity dates.",
        "trade_flows: normalized import/export rows by reporter, partner, commodity code, flow, period, quantity, value, fetched_at, published_at, raw_response_id, and source_record_hash.",
        "monthly_trade_features: product-level monthly features such as import/export volume, net exports, unit values, rolling averages, YoY change, reporting lag, trade_as_of_date, and missing flags.",
        "daily_trade_features: optional forward-filled daily view derived from monthly_trade_features with strict as-of cutoffs.",
        "product_trade_code_weights: optional mapping from product_code to HS/source codes and country groups when a product needs multiple trade proxies.",
    )


def recommendations() -> tuple[str, ...]:
    return (
        "Phase 6.5B should design trade_commodity_codes, trade_flows, and monthly/daily trade feature tables before any production writes.",
        "Use UN Comtrade as the first source to prototype if API access and rate limits are workable.",
        "Keep the first prototype narrow: six core HS codes, selected reporter/partner groups, monthly periods, and no broad country/code crawling.",
        "Use FAOSTAT as annual agricultural context, not as the first short-horizon monthly signal.",
        "Defer ITC Trade Map and national customs scraping until licensing and source-specific designs are approved.",
        "Store raw evidence and source hashes in future collectors; this phase writes diagnostics artifacts only.",
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
        "No live API probing.",
    )


def write_audit_outputs(audit: TradeSourceAudit, output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "trade_source_candidates.json").write_text(
        json.dumps(audit_to_dict(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "TRADE_SOURCE_AUDIT_REPORT.md").write_text(render_report(audit), encoding="utf-8")


def render_report(audit: TradeSourceAudit) -> str:
    counts = count_by_status(audit.candidates)
    lines = [
        "# Trade Import Export Source Audit",
        "",
        "## Executive Summary",
        "",
        "Phase 6.5A is local diagnostics/design-only. It does not write PostgreSQL rows, does not create collectors, does not use RawStore, does not change scheduler settings, does not add ML targets, and does not add dataset targets.",
        "",
        f"Live probing: `{audit.live_probing}`. This report uses a curated static registry and performs no HTTP requests.",
        "",
        f"Recommended first source: `{audit.recommended_first_source}`.",
        "",
        f"Recommended first prototype scope: {audit.recommended_first_prototype_scope}",
        "",
        "## Why Trade Import Export Matters For Agricultural Commodity Forecasting",
        "",
        "Trade flows describe physical availability, destination demand, export competition, and substitution pressure. Monthly import/export volume, trade values, and unit values can help explain soybean, rapeseed/canola, vegetable oil, and meal/feed price regimes after publication lag is handled correctly.",
        "",
        "## Current Product Families",
        "",
        "- soybean: `soybean_oil`, `soybean_meal`, and soybean seed context.",
        "- rapeseed/canola: `rapeseed_oil`, `rapeseed_meal`, and seed context.",
        "- broader vegetable oils, grains, and fertilizer are context or later layers.",
        "",
        "## HS Code Mapping Table",
        "",
        "| commodity_family | product_code | hs_code | relevance | hs_description | notes |",
        "|---|---|---|---|---|---|",
    ]
    for mapping in audit.hs_code_mappings:
        lines.append(
            "| {family} | {product} | {hs} | {relevance} | {description} | {notes} |".format(
                family=mapping.commodity_family,
                product=mapping.product_code or "",
                hs=mapping.hs_code,
                relevance=mapping.relevance,
                description=mapping.hs_description,
                notes=mapping.notes,
            )
        )

    lines.extend(
        [
            "",
            "## Candidate Source Table",
            "",
            "| source | status | type | auth | format | frequency | operational risk | storage risk | as-of risk |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for candidate in audit.candidates:
        lines.append(
            "| {source} | {status} | {source_type} | {auth} | {fmt} | {frequency} | {op} | {storage} | {asof} |".format(
                source=candidate.source_name,
                status=candidate.candidate_status,
                source_type=candidate.source_type,
                auth="yes" if candidate.auth_required else "no",
                fmt=candidate.format,
                frequency=candidate.frequency,
                op=candidate.operational_risk,
                storage=candidate.storage_risk,
                asof=candidate.as_of_risk,
            )
        )

    lines.extend(
        [
            "",
            "## Recommended First Source",
            "",
            "Use UN Comtrade as the first trade/import-export source to prototype if API access is workable. It is the most direct global HS-code source for bilateral import/export quantities and values, which fits product-family trade proxies better than broad macro trade aggregates.",
            "",
            "## Recommended First Prototype Scope",
            "",
            audit.recommended_first_prototype_scope,
            "",
            "The first prototype should be bounded: one small country group, six HS code groups, monthly frequency, strict timeout/rate limits, and raw-response caching in a later production collector. No broad country/code crawling should happen in this phase.",
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
                f"- Frequency: {candidate.frequency}",
                f"- Historical depth: {candidate.historical_depth}",
                f"- Commodity granularity: {candidate.commodity_granularity}",
                f"- Country/partner support: {candidate.country_partner_support}",
                f"- Rate limits: {candidate.rate_limits}",
                f"- License notes: {candidate.license_notes}",
                f"- Operational risk: {candidate.operational_risk}",
                f"- Storage risk: {candidate.storage_risk}",
                f"- As-of risk: {candidate.as_of_risk}",
                f"- ML value: {candidate.ml_value}",
                f"- Recommended next action: {candidate.recommended_next_action}",
                "",
            ]
        )

    lines.extend(["## Useful Future Features", ""])
    for item in audit.feature_candidates:
        lines.append(f"- `{item}`")

    lines.extend(["", "## Proposed Future Schema", ""])
    for item in audit.data_model_proposal:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Dedup And Idempotency Policy",
            "",
            "- Trade flow identity should include source, reporter, partner, flow direction, commodity/source code, period, unit, and frequency.",
            "- Store `source_record_hash` for each normalized row to detect source revisions.",
            "- Same identity and same hash should be skipped.",
            "- Same identity with a changed hash should create an explicit revision/warning policy rather than silently overwriting.",
            "- Store raw evidence in future production collectors through RawStore and link normalized rows through `raw_response_id`.",
            "",
            "## As-Of And Leakage Policy",
            "",
            "- Use only trade rows with `published_at <= feature_date` in publication-aware mode.",
            "- In strict `as_collected` mode, also require `fetched_at <= feature_date`.",
            "- Monthly and annual trade data has reporting lag and should not be treated as available at the start of the trade period.",
            "- Backfilled historical trade rows must not be treated as known on past feature dates unless `historical_backfill_allowed` mode is explicitly selected.",
            "- Trade revisions can happen; use `source_record_hash` for change detection.",
            "- Do not use future month trade data for earlier feature dates.",
            "",
            "## Storage And Rate-Limit Risks",
            "",
            "- UN Comtrade and WITS can become large if reporter/partner/code windows are broad; start narrow and cache raw responses.",
            "- National customs data is heterogeneous; do not build a broad crawler.",
            "- ITC Trade Map and commercial routes require explicit licensing before any automation.",
            "- Annual FAOSTAT data is lower storage risk but has weaker short-term timing value.",
            "",
            "## Licensing And Access Risks",
            "",
            "- Review source-specific terms before redistributing exported datasets.",
            "- Preserve source URL, source code, publication/fetch timestamps, and citation metadata.",
            "- Do not scrape paid portals or dynamic web pages without an approved API/license.",
            "",
            "## Proposed Future Phases",
            "",
            "- Phase 6.5B: trade/import-export schema design.",
            "- Phase 6.5C: trade schema implementation.",
            "- Phase 6.5D: first controlled trade collector.",
            "- Phase 6.5E: trade features/export integration.",
            "",
            "## Non-Goals",
            "",
        ]
    )
    for item in audit.non_goals:
        lines.append(f"- {item}")

    lines.extend(["", "## Candidate Counts", ""])
    for status in sorted(VALID_CANDIDATE_STATUSES):
        lines.append(f"- `{status}`: {counts.get(status, 0)}")

    lines.extend(["", "## Recommendations", ""])
    for item in audit.recommendations:
        lines.append(f"- {item}")

    lines.append("")
    return "\n".join(lines)


def audit_to_dict(audit: TradeSourceAudit) -> dict[str, Any]:
    return {
        "generated_at": audit.generated_at,
        "mode": audit.mode,
        "live_probing": audit.live_probing,
        "recommended_first_source": audit.recommended_first_source,
        "recommended_first_prototype_scope": audit.recommended_first_prototype_scope,
        "hs_code_mappings": [mapping_to_dict(mapping) for mapping in audit.hs_code_mappings],
        "candidates": [candidate_to_dict(candidate) for candidate in audit.candidates],
        "feature_candidates": list(audit.feature_candidates),
        "data_model_proposal": list(audit.data_model_proposal),
        "recommendations": list(audit.recommendations),
        "non_goals": list(audit.non_goals),
    }


def mapping_to_dict(mapping: HSCodeMapping) -> dict[str, Any]:
    return asdict(mapping)


def candidate_to_dict(candidate: TradeSourceCandidate) -> dict[str, Any]:
    return asdict(candidate)


def count_by_status(candidates: tuple[TradeSourceCandidate, ...] | None = None) -> dict[str, int]:
    candidates = candidates or source_candidates()
    counts = {status: 0 for status in VALID_CANDIDATE_STATUSES}
    for candidate in candidates:
        counts[candidate.candidate_status] = counts.get(candidate.candidate_status, 0) + 1
    return counts
