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
SourceType = Literal["api", "csv", "bulk_download", "report", "pdf", "html", "commercial"]
MetricGroup = Literal[
    "supply",
    "demand",
    "stocks",
    "area_yield",
    "trade",
    "metadata",
    "quality",
]
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
VALID_SOURCE_TYPES = {"api", "csv", "bulk_download", "report", "pdf", "html", "commercial"}
VALID_METRIC_GROUPS = {
    "supply",
    "demand",
    "stocks",
    "area_yield",
    "trade",
    "metadata",
    "quality",
}
VALID_RELEVANCE = {"direct", "context", "later"}
OUTPUT_DIR = Path("diagnostics/supply_demand_source_audit")


@dataclass(frozen=True)
class MetricTaxonomyItem:
    metric_name: str
    metric_group: MetricGroup
    frequency: str
    ml_value: str
    as_of_risk: str

    def __post_init__(self) -> None:
        if self.metric_group not in VALID_METRIC_GROUPS:
            raise ValueError(f"invalid metric_group: {self.metric_group}")
        if not self.metric_name:
            raise ValueError("metric_name must not be empty")
        if not self.frequency:
            raise ValueError("frequency must not be empty")


@dataclass(frozen=True)
class CommodityMetricMapping:
    commodity_family: str
    product_code: str | None
    official_commodity_name: str
    official_metric: str
    relevance: Relevance
    frequency: str
    notes: str

    def __post_init__(self) -> None:
        if self.relevance not in VALID_RELEVANCE:
            raise ValueError(f"invalid relevance: {self.relevance}")
        if not self.commodity_family:
            raise ValueError("commodity_family must not be empty")
        if not self.official_commodity_name:
            raise ValueError("official_commodity_name must not be empty")
        if not self.official_metric:
            raise ValueError("official_metric must not be empty")


@dataclass(frozen=True)
class SupplyDemandSourceCandidate:
    source_name: str
    source_url: str
    candidate_status: CandidateStatus
    source_type: SourceType
    auth_required: bool
    format: str
    frequency: str
    historical_depth: str
    commodity_coverage: str
    geography_coverage: str
    metrics_available: tuple[str, ...]
    revisions_available: str
    publication_date_available: str
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
        if not self.metrics_available:
            raise ValueError("metrics_available must not be empty")


@dataclass(frozen=True)
class SupplyDemandSourceAudit:
    generated_at: str
    mode: str
    live_probing: str
    recommended_first_source: str
    recommended_first_prototype_scope: str
    metric_taxonomy: tuple[MetricTaxonomyItem, ...]
    commodity_metric_mappings: tuple[CommodityMetricMapping, ...]
    candidates: tuple[SupplyDemandSourceCandidate, ...]
    future_schema_proposal: tuple[str, ...]
    recommendations: tuple[str, ...]
    non_goals: tuple[str, ...]


def build_audit(*, generated_at: datetime | None = None, live_probe: bool = False) -> SupplyDemandSourceAudit:
    generated_at = generated_at or datetime.now(timezone.utc)
    candidates = source_candidates()
    first_source = recommended_first_source(candidates)
    return SupplyDemandSourceAudit(
        generated_at=generated_at.isoformat(),
        mode="inventory",
        live_probing="not_run_static_registry" if not live_probe else "not_supported_static_registry_only",
        recommended_first_source=first_source.source_name,
        recommended_first_prototype_scope=recommended_first_prototype_scope(),
        metric_taxonomy=metric_taxonomy(),
        commodity_metric_mappings=commodity_metric_mappings(),
        candidates=candidates,
        future_schema_proposal=future_schema_proposal(),
        recommendations=recommendations(),
        non_goals=non_goals(),
    )


def metric_taxonomy() -> tuple[MetricTaxonomyItem, ...]:
    return (
        MetricTaxonomyItem(
            metric_name="production",
            metric_group="supply",
            frequency="monthly forecast / annual marketing year",
            ml_value="High as a physical supply anchor for oilseed, oil, and meal price regimes.",
            as_of_risk="medium; forecasts and actuals are revised and must be gated by publication/fetched dates.",
        ),
        MetricTaxonomyItem(
            metric_name="production_volume",
            metric_group="supply",
            frequency="monthly forecast / annual marketing year",
            ml_value="High as the normalized feature-facing production measure.",
            as_of_risk="medium; should reference the release/vintage used to derive the feature.",
        ),
        MetricTaxonomyItem(
            metric_name="consumption",
            metric_group="demand",
            frequency="monthly forecast / annual marketing year",
            ml_value="High for domestic use, feed demand, food/industrial use, and disappearance proxies.",
            as_of_risk="medium; source revisions and forecast months must be tracked.",
        ),
        MetricTaxonomyItem(
            metric_name="domestic_consumption",
            metric_group="demand",
            frequency="monthly forecast / annual marketing year",
            ml_value="High as a direct demand balance feature for oil and meal products.",
            as_of_risk="medium; report publication and revision dates must be modeled.",
        ),
        MetricTaxonomyItem(
            metric_name="food_use",
            metric_group="demand",
            frequency="monthly forecast / annual marketing year",
            ml_value="Medium for oil consumption composition where sources provide it.",
            as_of_risk="medium; often appears in balance tables with release lag.",
        ),
        MetricTaxonomyItem(
            metric_name="feed_use",
            metric_group="demand",
            frequency="monthly forecast / annual marketing year",
            ml_value="High for meal demand and livestock/feed substitution context.",
            as_of_risk="medium; estimates can revise as feed demand changes.",
        ),
        MetricTaxonomyItem(
            metric_name="beginning_stocks",
            metric_group="stocks",
            frequency="monthly forecast / annual marketing year",
            ml_value="Medium as the carry-in side of supply availability.",
            as_of_risk="medium; older carry-in values can be revised by later reports.",
        ),
        MetricTaxonomyItem(
            metric_name="ending_stocks",
            metric_group="stocks",
            frequency="monthly forecast / annual marketing year",
            ml_value="High as a tightness indicator and direct input for stock-to-use ratios.",
            as_of_risk="medium; revisions can change historical marketing-year values.",
        ),
        MetricTaxonomyItem(
            metric_name="stock_to_use",
            metric_group="stocks",
            frequency="derived monthly forecast / annual marketing year",
            ml_value="High; normalized tightness feature across commodities and countries.",
            as_of_risk="medium; derived value must use only as-of-safe production, use, and stock inputs.",
        ),
        MetricTaxonomyItem(
            metric_name="planted_area",
            metric_group="area_yield",
            frequency="seasonal / annual",
            ml_value="Medium to high as an early supply potential signal.",
            as_of_risk="high; estimates arrive before harvest and are revised.",
        ),
        MetricTaxonomyItem(
            metric_name="harvested_area",
            metric_group="area_yield",
            frequency="seasonal / annual",
            ml_value="Medium to high as a realized production denominator.",
            as_of_risk="high; final acreage can be known much later than price dates.",
        ),
        MetricTaxonomyItem(
            metric_name="yield",
            metric_group="area_yield",
            frequency="seasonal / annual",
            ml_value="High for production expectation shifts and supply shocks.",
            as_of_risk="high; yield estimates are frequently revised during the crop cycle.",
        ),
        MetricTaxonomyItem(
            metric_name="crush",
            metric_group="demand",
            frequency="monthly / marketing year",
            ml_value="High for oil/meal supply generation and processor demand.",
            as_of_risk="medium; release lag and revisions must be modeled.",
        ),
        MetricTaxonomyItem(
            metric_name="exports",
            metric_group="trade",
            frequency="monthly / marketing year",
            ml_value="High as a demand and availability signal for major exporters.",
            as_of_risk="medium; export forecasts, actuals, and trade rows have different release lags.",
        ),
        MetricTaxonomyItem(
            metric_name="imports",
            metric_group="trade",
            frequency="monthly / marketing year",
            ml_value="High for China/import demand and regional availability proxies.",
            as_of_risk="medium; must not be mixed with later-released trade actuals without as-of cutoffs.",
        ),
        MetricTaxonomyItem(
            metric_name="revisions",
            metric_group="metadata",
            frequency="per release",
            ml_value="Medium; source revision magnitude can be a stability and uncertainty signal.",
            as_of_risk="low if versioned correctly; high if old values are overwritten silently.",
        ),
        MetricTaxonomyItem(
            metric_name="production_forecast_revision",
            metric_group="metadata",
            frequency="per release",
            ml_value="Medium to high as a feature for changing supply expectations.",
            as_of_risk="low when calculated between release vintages available by the feature date.",
        ),
        MetricTaxonomyItem(
            metric_name="ending_stocks_revision",
            metric_group="metadata",
            frequency="per release",
            ml_value="High as a direct signal of revised tightness expectations.",
            as_of_risk="low when derived from as-of-safe release history.",
        ),
        MetricTaxonomyItem(
            metric_name="stock_to_use_revision",
            metric_group="metadata",
            frequency="per release",
            ml_value="High as a normalized revised-tightness feature.",
            as_of_risk="low when derived from as-of-safe release history.",
        ),
        MetricTaxonomyItem(
            metric_name="forecast_month",
            metric_group="metadata",
            frequency="monthly",
            ml_value="Medium; identifies which forecast vintage produced a row.",
            as_of_risk="low if stored directly from the source release.",
        ),
        MetricTaxonomyItem(
            metric_name="marketing_year",
            metric_group="metadata",
            frequency="annual",
            ml_value="High as the natural time grain for official supply-demand balances.",
            as_of_risk="low, but must be separated from calendar-year feature dates.",
        ),
        MetricTaxonomyItem(
            metric_name="report_publication_date",
            metric_group="metadata",
            frequency="per release",
            ml_value="High for leakage-safe availability rules.",
            as_of_risk="low if captured from source metadata; unknown dates must be flagged.",
        ),
        MetricTaxonomyItem(
            metric_name="reporting_lag",
            metric_group="metadata",
            frequency="derived per row",
            ml_value="Medium as a data freshness and uncertainty feature.",
            as_of_risk="low when derived from publication date and feature date.",
        ),
        MetricTaxonomyItem(
            metric_name="supply_demand_as_of_date",
            metric_group="metadata",
            frequency="derived per feature row",
            ml_value="High as the feature-side cutoff explaining which vintage was used.",
            as_of_risk="low when enforced by builder queries.",
        ),
        MetricTaxonomyItem(
            metric_name="missing_flags",
            metric_group="quality",
            frequency="daily/monthly derived",
            ml_value="Medium; prevents silent imputation and helps model missingness explicitly.",
            as_of_risk="low when flags are generated with the same cutoff as features.",
        ),
    )


def commodity_metric_mappings() -> tuple[CommodityMetricMapping, ...]:
    return (
        CommodityMetricMapping(
            commodity_family="soybean",
            product_code=None,
            official_commodity_name="Soybeans",
            official_metric="production, crush, exports, imports, ending stocks, stock-to-use",
            relevance="context",
            frequency="monthly forecast / marketing year",
            notes="Seed balance is the upstream driver for soybean oil and soybean meal supply through crush.",
        ),
        CommodityMetricMapping(
            commodity_family="soybean_oil",
            product_code="soybean_oil",
            official_commodity_name="Soybean Oil",
            official_metric="production, domestic consumption, exports, imports, ending stocks",
            relevance="direct",
            frequency="monthly forecast / marketing year",
            notes="Direct balance item for the current product; first PSD prototype should include it.",
        ),
        CommodityMetricMapping(
            commodity_family="soybean_meal",
            product_code="soybean_meal",
            official_commodity_name="Soybean Meal",
            official_metric="production, feed use/consumption, exports, imports, ending stocks",
            relevance="direct",
            frequency="monthly forecast / marketing year",
            notes="Direct meal balance item; important for feed-demand and crush-product spreads.",
        ),
        CommodityMetricMapping(
            commodity_family="rapeseed_canola",
            product_code=None,
            official_commodity_name="Rapeseed / Canola",
            official_metric="production, crush, exports, imports, ending stocks, stock-to-use",
            relevance="context",
            frequency="monthly forecast / marketing year",
            notes="Seed balance provides upstream context for rapeseed oil and meal.",
        ),
        CommodityMetricMapping(
            commodity_family="rapeseed_oil",
            product_code="rapeseed_oil",
            official_commodity_name="Rapeseed Oil / Canola Oil",
            official_metric="production, domestic consumption, exports, imports, ending stocks",
            relevance="direct",
            frequency="monthly forecast / marketing year",
            notes="Direct oil balance item; source names vary between rapeseed and canola.",
        ),
        CommodityMetricMapping(
            commodity_family="rapeseed_meal",
            product_code="rapeseed_meal",
            official_commodity_name="Rapeseed Meal / Canola Meal",
            official_metric="production, feed use/consumption, exports, imports, ending stocks",
            relevance="direct",
            frequency="monthly forecast / marketing year",
            notes="Direct meal balance item; source naming and country coverage need manual mapping.",
        ),
        CommodityMetricMapping(
            commodity_family="palm_oil",
            product_code=None,
            official_commodity_name="Palm Oil",
            official_metric="production, consumption, exports, imports, ending stocks",
            relevance="context",
            frequency="monthly forecast / marketing year",
            notes="Major substitute vegetable oil; useful context after core oilseed products are proven.",
        ),
        CommodityMetricMapping(
            commodity_family="sunflowerseed_oil",
            product_code=None,
            official_commodity_name="Sunflowerseed Oil",
            official_metric="production, consumption, exports, imports, ending stocks",
            relevance="later",
            frequency="monthly forecast / marketing year",
            notes="Useful later, but sunflower production price instruments are not confirmed in the current collector.",
        ),
        CommodityMetricMapping(
            commodity_family="corn",
            product_code=None,
            official_commodity_name="Corn",
            official_metric="production, feed use, exports, imports, ending stocks",
            relevance="context",
            frequency="monthly forecast / marketing year",
            notes="Feed and biofuel context, especially for meal demand and oilseed acreage competition.",
        ),
    )


def source_candidates() -> tuple[SupplyDemandSourceCandidate, ...]:
    return (
        SupplyDemandSourceCandidate(
            source_name="USDA PSD / FAS PSD Online",
            source_url="https://apps.fas.usda.gov/psdonline/app/index.html#/app/home",
            candidate_status="ready_to_probe",
            source_type="api",
            auth_required=False,
            format="Web-backed API/download routes need bounded prototype verification",
            frequency="monthly releases with marketing-year balance tables",
            historical_depth="Deep official global PSD history; exact API/backfile depth must be verified.",
            commodity_coverage="Oilseeds, meals, vegetable oils, grains, and country/global balances.",
            geography_coverage="Global countries and world aggregates depending on commodity/table.",
            metrics_available=(
                "production",
                "consumption",
                "crush",
                "exports",
                "imports",
                "ending_stocks",
                "area",
                "yield",
            ),
            revisions_available="Likely through repeated monthly releases/vintages; exact vintage access needs prototype.",
            publication_date_available="Release dates are public, but row-level publication metadata must be captured by collector.",
            rate_limits="Use small commodity/country windows, explicit timeout, cache raw responses, and no broad scraping.",
            license_notes="Official US government source; preserve source URL, release/vintage metadata, and citation.",
            operational_risk="medium",
            storage_risk="low_to_medium for narrow oilseed prototype; higher if all commodities/countries are pulled.",
            as_of_risk="medium_to_high because forecasts and historical rows revise by monthly vintage.",
            ml_value="High; best first candidate for supply-demand fundamentals across current oil/meal products.",
            recommended_next_action="Phase 6.7B should design PSD balance/vintage schema, then probe a narrow soybean/rapeseed oilseed scope.",
        ),
        SupplyDemandSourceCandidate(
            source_name="USDA WASDE",
            source_url="https://www.usda.gov/oce/commodity/wasde",
            candidate_status="needs_manual_check",
            source_type="pdf",
            auth_required=False,
            format="PDF/text reports and historical report archive",
            frequency="monthly",
            historical_depth="Long report archive, but machine-readable table extraction reliability needs checking.",
            commodity_coverage="Major crops, oilseeds, meals, oils, and global balance commentary.",
            geography_coverage="US and world/selected-country aggregates depending on table.",
            metrics_available=("production", "consumption", "exports", "imports", "ending_stocks", "stock_to_use"),
            revisions_available="Report vintages are naturally archived; parsing stable tables is the hard part.",
            publication_date_available="Yes at report level.",
            rate_limits="Download only selected reports; avoid parsing broad archives until schema is settled.",
            license_notes="Official US government report; retain report date, page/table metadata, and citation.",
            operational_risk="medium_to_high",
            storage_risk="medium for PDF archive; low for a single current report.",
            as_of_risk="medium; report publication date is clear, but table extraction must preserve vintage.",
            ml_value="High later as official monthly forecast context, but not the first machine-readable source.",
            recommended_next_action="Manual-check table extraction only after PSD route is evaluated.",
        ),
        SupplyDemandSourceCandidate(
            source_name="USDA NASS Quick Stats",
            source_url="https://quickstats.nass.usda.gov/",
            candidate_status="needs_manual_check",
            source_type="api",
            auth_required=True,
            format="JSON/CSV API",
            frequency="survey/census-specific; annual and seasonal series",
            historical_depth="Long US acreage, production, yield, and stocks history.",
            commodity_coverage="US crop production, acreage, yield, and stocks; weaker for global balances.",
            geography_coverage="United States national/state/county levels.",
            metrics_available=("production", "planted_area", "harvested_area", "yield", "stocks"),
            revisions_available="Survey revisions and release timing must be inferred from metadata/release calendars.",
            publication_date_available="Release metadata exists, but as-of implementation needs source-specific review.",
            rate_limits="API key and request limits apply; use narrow commodity/statistic/year windows.",
            license_notes="Official US government data; preserve source and parameter metadata.",
            operational_risk="medium",
            storage_risk="low_to_medium for narrow US crop rows.",
            as_of_risk="high because survey timing and revisions differ by statistic.",
            ml_value="Medium to high for US soybean/canola/corn acreage and yield context.",
            recommended_next_action="Manual-check after PSD because it is US-focused and not a complete oil/meal balance source.",
        ),
        SupplyDemandSourceCandidate(
            source_name="FAOSTAT Crops and Livestock Products / Food Balances",
            source_url="https://www.fao.org/faostat/",
            candidate_status="ready_to_prototype",
            source_type="bulk_download",
            auth_required=False,
            format="API/CSV bulk downloads",
            frequency="annual",
            historical_depth="Long official annual history across countries and commodities.",
            commodity_coverage="Crops, livestock products, food balances, production, area, yield, supply utilization.",
            geography_coverage="Global country coverage with FAOSTAT item codes.",
            metrics_available=("production", "area", "yield", "food_supply", "imports", "exports", "stocks"),
            revisions_available="Annual datasets are revised; vintage tracking may require fetched/raw snapshots.",
            publication_date_available="Dataset release/update metadata needs manual verification.",
            rate_limits="Use bounded API/downloads; bulk files can be large but manageable if cached once.",
            license_notes="Review FAOSTAT terms and attribution before redistribution in exports.",
            operational_risk="low_to_medium",
            storage_risk="medium for bulk domains; low for narrow item/country prototypes.",
            as_of_risk="medium because annual publication lag is large and updates can replace rows.",
            ml_value="Medium; strong slow-moving structural context, weaker short-horizon timing signal.",
            recommended_next_action="Prototype as annual context after PSD schema decisions, not as first daily/monthly signal.",
        ),
        SupplyDemandSourceCandidate(
            source_name="AMIS Market Database / Monitor",
            source_url="https://www.amis-outlook.org/",
            candidate_status="needs_manual_check",
            source_type="html",
            auth_required=False,
            format="Web tables/reports; machine-readable routes need manual verification",
            frequency="monthly/periodic",
            historical_depth="Useful market monitor history, but structured download depth is unclear.",
            commodity_coverage="Major grains and oilseeds context; exact oil/meal coverage needs review.",
            geography_coverage="AMIS member countries and global aggregates.",
            metrics_available=("production", "utilization", "trade", "ending_stocks", "market_monitor"),
            revisions_available="Unclear; reports may be archived but row-level revisions need manual design.",
            publication_date_available="Report-level dates likely available.",
            rate_limits="Do not crawl; manually identify official download/API routes first.",
            license_notes="Review AMIS/FAO reuse terms and attribution requirements.",
            operational_risk="medium_to_high",
            storage_risk="low for reports, medium if historical tables are bulk-downloaded.",
            as_of_risk="medium; report vintage and table dates must be separated.",
            ml_value="Medium as cross-market narrative and balance context.",
            recommended_next_action="Manual-check only after PSD/FAOSTAT because routes are less obvious.",
        ),
        SupplyDemandSourceCandidate(
            source_name="International Grains Council / IGC",
            source_url="https://www.igc.int/",
            candidate_status="paid_later",
            source_type="commercial",
            auth_required=True,
            format="Subscription tables/reports and public summaries",
            frequency="monthly/periodic",
            historical_depth="Potentially rich grains/oilseeds history under subscription.",
            commodity_coverage="Grains, oilseeds, meals/oils depending on access level.",
            geography_coverage="Global and country/regional balances depending on subscription.",
            metrics_available=("production", "consumption", "trade", "stocks", "forecasts"),
            revisions_available="Likely by report vintage, but licensing/access decides feasibility.",
            publication_date_available="Report-level dates likely available.",
            rate_limits="Commercial access controls; no scraping.",
            license_notes="Do not automate or redistribute without an approved license/subscription.",
            operational_risk="high",
            storage_risk="medium",
            as_of_risk="medium; valuable only if vintages and dates are contractually available.",
            ml_value="High if licensed, but not suitable for first open-source collector.",
            recommended_next_action="Defer until budget/licensing is explicitly approved.",
        ),
        SupplyDemandSourceCandidate(
            source_name="Statistics Canada / Agriculture Canada",
            source_url="https://www.statcan.gc.ca/",
            candidate_status="high_complexity",
            source_type="api",
            auth_required=False,
            format="StatCan tables/API/CSV downloads plus agriculture reports",
            frequency="monthly/annual/table-specific",
            historical_depth="Deep Canadian crop, stocks, acreage, and export context.",
            commodity_coverage="Canola/rapeseed, soybeans, grains, acreage, yield, stocks, processing context.",
            geography_coverage="Canada national/provincial tables.",
            metrics_available=("production", "stocks", "area", "yield", "crush", "exports"),
            revisions_available="Table updates/revisions likely; vintage handling needs design.",
            publication_date_available="Table release/update metadata needs manual verification.",
            rate_limits="Use documented API/downloads and narrow table IDs.",
            license_notes="Review Statistics Canada open license and attribution.",
            operational_risk="high",
            storage_risk="medium because table IDs and dimensions vary.",
            as_of_risk="medium_to_high because release calendars differ by table.",
            ml_value="High later for canola/rapeseed supply context.",
            recommended_next_action="Defer until a shared supply-demand schema is proven with PSD.",
        ),
        SupplyDemandSourceCandidate(
            source_name="CONAB Brazil",
            source_url="https://www.conab.gov.br/",
            candidate_status="high_complexity",
            source_type="report",
            auth_required=False,
            format="Portuguese reports, spreadsheets, and web pages by program",
            frequency="monthly/seasonal",
            historical_depth="Important Brazil soybean/corn crop estimates; structured depth varies.",
            commodity_coverage="Soybeans, corn, grains, acreage, production, yield, and market commentary.",
            geography_coverage="Brazil national/state/region.",
            metrics_available=("production", "area", "yield", "stocks", "forecasts"),
            revisions_available="Report vintages exist, but automated extraction requires source-specific work.",
            publication_date_available="Report-level dates likely available.",
            rate_limits="Manual source mapping first; avoid broad crawling and PDF scraping.",
            license_notes="Review CONAB reuse/citation terms; preserve Portuguese source metadata.",
            operational_risk="high",
            storage_risk="medium_to_high if report archives are downloaded.",
            as_of_risk="high because crop estimate vintages drive the value.",
            ml_value="High later for Brazil soybean supply shocks.",
            recommended_next_action="Defer until PSD prototype and schema prove value; then design a Brazil-specific adapter.",
        ),
        SupplyDemandSourceCandidate(
            source_name="Argentina official agriculture/statistics sources",
            source_url="https://www.magyp.gob.ar/",
            candidate_status="high_complexity",
            source_type="html",
            auth_required=False,
            format="Spanish web pages, reports, spreadsheets, and possibly APIs",
            frequency="monthly/seasonal/source-specific",
            historical_depth="Potentially strong for Argentina soybean/corn/wheat crop and supply context.",
            commodity_coverage="Soybeans, soybean meal/oil exports/context, grains, acreage, production.",
            geography_coverage="Argentina national/province depending on dataset.",
            metrics_available=("production", "area", "yield", "crush", "exports", "stocks"),
            revisions_available="Unclear; source-specific vintage design required.",
            publication_date_available="Report/table dates likely but need manual verification.",
            rate_limits="Manual mapping only; no broad crawling across ministry pages.",
            license_notes="Review official reuse terms and preserve Spanish source metadata.",
            operational_risk="high",
            storage_risk="medium_to_high due heterogeneous file/page formats.",
            as_of_risk="high because publication lag and revisions may be hard to normalize.",
            ml_value="High later for soybean meal/oil export and crop context.",
            recommended_next_action="Defer until shared schema and one global source are production-proven.",
        ),
        SupplyDemandSourceCandidate(
            source_name="Eurostat Agriculture",
            source_url="https://ec.europa.eu/eurostat/",
            candidate_status="needs_manual_check",
            source_type="api",
            auth_required=False,
            format="API/SDMX/TSV downloads",
            frequency="annual/seasonal/table-specific",
            historical_depth="Deep EU agricultural history, depending on dataset code.",
            commodity_coverage="Crop production, area, yield, balances, and related agriculture indicators.",
            geography_coverage="EU member states and aggregates.",
            metrics_available=("production", "area", "yield", "stocks", "trade_context"),
            revisions_available="Eurostat table revisions occur; fetched_at and source hashes are required.",
            publication_date_available="Dataset update metadata needs manual verification.",
            rate_limits="Use official API/download guidance and bounded dataset/table codes.",
            license_notes="Review Eurostat reuse rules and preserve table metadata.",
            operational_risk="medium",
            storage_risk="medium if many member states/tables are pulled.",
            as_of_risk="medium because annual/seasonal publication lag can be substantial.",
            ml_value="Medium to high for EU rapeseed/canola context.",
            recommended_next_action="Manual-check dataset codes after PSD/FAOSTAT decisions.",
        ),
    )


def recommended_first_source(
    candidates: tuple[SupplyDemandSourceCandidate, ...] | None = None,
) -> SupplyDemandSourceCandidate:
    candidates = candidates or source_candidates()
    for candidate in candidates:
        if candidate.source_name == "USDA PSD / FAS PSD Online":
            return candidate
    raise ValueError("USDA PSD / FAS PSD Online candidate is missing")


def recommended_first_prototype_scope() -> str:
    return (
        "USDA PSD bounded static probe for soybeans, soybean oil, soybean meal, rapeseed/canola, "
        "rapeseed oil, and rapeseed meal; monthly/marketing-year balance metrics only, no DB writes, "
        "no scheduler, and publication/vintage metadata captured before any production collector."
    )


def future_schema_proposal() -> tuple[str, ...]:
    return (
        "supply_demand_sources: source code, source route, release calendar notes, license metadata, and active flag.",
        "supply_demand_commodities: mapping between product_code, official commodity names/codes, country groups, and relevance.",
        "supply_demand_releases: report/source vintage with publication_date, fetched_at, source_payload_hash, raw_response_id, and release label.",
        "supply_demand_observations: normalized production/consumption/stocks/trade rows by commodity, country/region, marketing_year, forecast_month, metric, value, unit, and source_record_hash.",
        "supply_demand_balances: optional wide or grouped balance view derived from normalized observations.",
        "supply_demand_revisions: audit rows for same identity with changed metric values across vintages.",
        "daily_supply_demand_features: optional as-of-safe daily view derived from release-aware balance rows.",
        "product_supply_demand_weights: optional product-to-official-commodity/metric weights for direct and context features.",
    )


def recommendations() -> tuple[str, ...]:
    return (
        "Use USDA PSD / FAS PSD Online as the first source to probe because it is closest to official oilseed supply-demand balances for all four current products.",
        "Keep Phase 6.7B as schema/design only: define releases, balances, revisions, and daily feature availability before production writes.",
        "Prototype only a narrow oilseed/oil/meal scope first; do not crawl broad commodity/country catalogs.",
        "Capture publication date, fetched_at, forecast month, marketing year, and source_record_hash from the first prototype.",
        "Use FAOSTAT later for annual structural context and WASDE later for report-vintage context after PSD is proven.",
        "Defer IGC, CONAB, Argentina, Statistics Canada, and other national sources until one global model is production-proven.",
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
        "No broad crawling.",
    )


def write_audit_outputs(audit: SupplyDemandSourceAudit, output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "supply_demand_source_candidates.json").write_text(
        json.dumps(audit_to_dict(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SUPPLY_DEMAND_SOURCE_AUDIT_REPORT.md").write_text(render_report(audit), encoding="utf-8")


def render_report(audit: SupplyDemandSourceAudit) -> str:
    counts = count_by_status(audit.candidates)
    lines = [
        "# Supply Demand Production Stocks Source Audit",
        "",
        "## Executive Summary",
        "",
        "Phase 6.7A is local diagnostics/design-only. It does not write PostgreSQL rows, does not create collectors, does not use RawStore, does not change scheduler settings, does not add ML, and does not add targets.",
        "",
        f"Live probing: `{audit.live_probing}`. This report uses a curated static registry and performs no HTTP requests.",
        "",
        f"Recommended first source: `{audit.recommended_first_source}`.",
        "",
        f"Recommended first prototype scope: {audit.recommended_first_prototype_scope}",
        "",
        "## Why Supply-Demand / Production-Stocks Matter",
        "",
        "Official supply-demand balances explain physical availability, crop-size expectations, crush demand, export availability, and stock tightness. These signals are slower than current prices but valuable for regime and risk context once publication dates and revisions are handled explicitly.",
        "",
        "## Current Product Families",
        "",
        "- soybean: `soybean_oil`, `soybean_meal`, plus upstream soybean seed/crush context.",
        "- rapeseed/canola: `rapeseed_oil`, `rapeseed_meal`, plus upstream rapeseed/canola seed/crush context.",
        "- palm oil, sunflowerseed oil, grains, and fertilizer remain context/later layers.",
        "",
        "## Future Metric Taxonomy",
        "",
        "| metric_name | metric_group | frequency | ml_value | as_of_risk |",
        "|---|---|---|---|---|",
    ]
    for item in audit.metric_taxonomy:
        lines.append(
            "| {name} | {group} | {frequency} | {ml_value} | {as_of_risk} |".format(
                name=item.metric_name,
                group=item.metric_group,
                frequency=item.frequency,
                ml_value=item.ml_value,
                as_of_risk=item.as_of_risk,
            )
        )

    lines.extend(
        [
            "",
            "## Product-To-Official-Commodity Mapping",
            "",
            "| commodity_family | product_code | official_commodity_name | official_metric | relevance | frequency | notes |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for mapping in audit.commodity_metric_mappings:
        lines.append(
            "| {family} | {product} | {commodity} | {metric} | {relevance} | {frequency} | {notes} |".format(
                family=mapping.commodity_family,
                product=mapping.product_code or "",
                commodity=mapping.official_commodity_name,
                metric=mapping.official_metric,
                relevance=mapping.relevance,
                frequency=mapping.frequency,
                notes=mapping.notes,
            )
        )

    lines.extend(
        [
            "",
            "## Candidate Source Table",
            "",
            "| source | status | type | auth | format | frequency | metrics | operational risk | storage risk | as-of risk |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for candidate in audit.candidates:
        lines.append(
            "| {source} | {status} | {source_type} | {auth} | {fmt} | {frequency} | {metrics} | {op} | {storage} | {asof} |".format(
                source=candidate.source_name,
                status=candidate.candidate_status,
                source_type=candidate.source_type,
                auth="yes" if candidate.auth_required else "no",
                fmt=candidate.format,
                frequency=candidate.frequency,
                metrics=", ".join(candidate.metrics_available),
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
            "Use USDA PSD / FAS PSD Online as the first supply-demand source to probe. It is the closest official global balance source for soybeans, soybean oil, soybean meal, rapeseed/canola, rapeseed oil, and rapeseed meal, and it can support production, consumption, crush, trade, and stock features from a single model.",
            "",
            "## Recommended First Prototype Scope",
            "",
            audit.recommended_first_prototype_scope,
            "",
            "The first prototype should be bounded: current oilseed product families only, a small set of countries/world aggregates, explicit timeout/rate limits, and no writes outside diagnostics. It should verify publication/vintage metadata before any collector design.",
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
                f"- Commodity coverage: {candidate.commodity_coverage}",
                f"- Geography coverage: {candidate.geography_coverage}",
                f"- Metrics available: {', '.join(candidate.metrics_available)}",
                f"- Revisions available: {candidate.revisions_available}",
                f"- Publication date available: {candidate.publication_date_available}",
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

    lines.extend(["## Proposed Future Schema", ""])
    for item in audit.future_schema_proposal:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## Dedup/Idempotency Policy",
            "",
            "- Future balance-row identity should include source, commodity/source code, country/region, marketing year, forecast month/vintage, metric name, unit, and frequency.",
            "- Store `source_record_hash` for normalized rows and `source_payload_hash`/`raw_response_id` for raw evidence.",
            "- Same identity and same hash should be skipped.",
            "- Same identity with changed values should create explicit revision rows; no silent overwrite.",
            "- Diagnostics artifacts from this phase are not production raw evidence.",
            "",
            "## As-Of/Leakage Policy",
            "",
            "- Supply-demand data must be gated by `published_at <= feature_date` in publication-aware mode.",
            "- In strict `as_collected` mode, also require `fetched_at <= feature_date`.",
            "- A balance value for a past marketing year fetched today must not be used for past feature dates unless `historical_backfill_allowed` is explicitly selected.",
            "- Store `forecast_month`, `marketing_year`, `report_publication_date`, and `supply_demand_as_of_date` so future features can explain which vintage was used.",
            "- Do not use future report vintages for earlier feature dates.",
            "",
            "## Revision Policy",
            "",
            "- Official balance tables are revised; revisions are expected, not automatically errors.",
            "- Future collectors should preserve previous values in a revision/audit table when a row identity changes hash.",
            "- Feature builders should choose the latest release known as of the feature date, not the latest release known today.",
            "- Older revised rows need source-specific policy before any update of production features.",
            "",
            "## Storage/Rate-Limit Risks",
            "",
            "- PSD and FAOSTAT can grow quickly if all countries, commodities, and years are downloaded; start with narrow product/country windows.",
            "- Report/PDF sources such as WASDE, CONAB, and national agencies have higher parsing and storage risk.",
            "- No broad crawling should be used; future probes should be bounded by product, country, date range, timeout, and max bytes.",
            "",
            "## Licensing/Access Risks",
            "",
            "- Review each source's terms before redistribution in dataset exports.",
            "- Preserve source URLs, report names, release dates, and citation metadata.",
            "- Do not scrape paid portals such as IGC without approved subscription/API terms.",
            "",
            "## Proposed Future Phases",
            "",
            "- Phase 6.7B: supply-demand schema and as-of design.",
            "- Phase 6.7C: schema-only implementation and tests.",
            "- Phase 6.7D: first controlled USDA PSD probe/collector prototype.",
            "- Phase 6.7E: supply-demand daily feature/export integration after source policy is proven.",
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


def audit_to_dict(audit: SupplyDemandSourceAudit) -> dict[str, Any]:
    return {
        "generated_at": audit.generated_at,
        "live_probing": audit.live_probing,
        "recommended_first_source": audit.recommended_first_source,
        "recommended_first_prototype_scope": audit.recommended_first_prototype_scope,
        "metric_taxonomy": [metric_to_dict(item) for item in audit.metric_taxonomy],
        "commodity_metric_mappings": [mapping_to_dict(mapping) for mapping in audit.commodity_metric_mappings],
        "candidates": [candidate_to_dict(candidate) for candidate in audit.candidates],
        "future_schema_proposal": list(audit.future_schema_proposal),
        "recommendations": list(audit.recommendations),
        "non_goals": list(audit.non_goals),
    }


def metric_to_dict(item: MetricTaxonomyItem) -> dict[str, Any]:
    return asdict(item)


def mapping_to_dict(mapping: CommodityMetricMapping) -> dict[str, Any]:
    return asdict(mapping)


def candidate_to_dict(candidate: SupplyDemandSourceCandidate) -> dict[str, Any]:
    data = asdict(candidate)
    data["metrics_available"] = list(candidate.metrics_available)
    return data


def count_by_status(candidates: tuple[SupplyDemandSourceCandidate, ...] | None = None) -> dict[str, int]:
    candidates = candidates or source_candidates()
    counts = {status: 0 for status in VALID_CANDIDATE_STATUSES}
    for candidate in candidates:
        counts[candidate.candidate_status] = counts.get(candidate.candidate_status, 0) + 1
    return counts
