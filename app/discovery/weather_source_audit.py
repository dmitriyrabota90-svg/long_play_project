from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


CandidateStatus = Literal["ready_to_prototype", "needs_manual_check", "high_complexity", "high_risk", "reject"]
Priority = Literal["high", "medium", "later"]

VALID_CANDIDATE_STATUSES = {
    "ready_to_prototype",
    "needs_manual_check",
    "high_complexity",
    "high_risk",
    "reject",
}
VALID_PRIORITIES = {"high", "medium", "later"}
OUTPUT_DIR = Path("diagnostics/weather_source_audit")


@dataclass(frozen=True)
class WeatherRegion:
    region_code: str
    region_name: str
    country: str
    crop: str
    commodity_family: str
    role: str
    latitude: float
    longitude: float
    aggregation_strategy: str
    priority: Priority
    reason_for_ml: str

    def __post_init__(self) -> None:
        if self.priority not in VALID_PRIORITIES:
            raise ValueError(f"invalid priority: {self.priority}")
        if not -90 <= self.latitude <= 90:
            raise ValueError(f"invalid latitude: {self.latitude}")
        if not -180 <= self.longitude <= 180:
            raise ValueError(f"invalid longitude: {self.longitude}")


@dataclass(frozen=True)
class WeatherSourceCandidate:
    source_name: str
    source_url: str
    candidate_status: CandidateStatus
    auth_required: bool
    format: str
    spatial_model: str
    variables_available: tuple[str, ...]
    historical_depth: str
    frequency: str
    rate_limits: str
    license_notes: str
    operational_risk: str
    storage_risk: str
    ml_value: str
    recommended_next_action: str

    def __post_init__(self) -> None:
        if self.candidate_status not in VALID_CANDIDATE_STATUSES:
            raise ValueError(f"invalid candidate_status: {self.candidate_status}")


@dataclass(frozen=True)
class WeatherSourceAudit:
    generated_at: str
    mode: str
    live_probing: str
    recommended_first_source: str
    recommended_regions: tuple[WeatherRegion, ...]
    candidates: tuple[WeatherSourceCandidate, ...]
    daily_raw_variables: tuple[str, ...]
    derived_feature_candidates: tuple[str, ...]
    recommendations: tuple[str, ...]
    non_goals: tuple[str, ...]


def build_audit(*, generated_at: datetime | None = None, live_probe: bool = False) -> WeatherSourceAudit:
    generated_at = generated_at or datetime.now(timezone.utc)
    candidates = source_candidates()
    first_source = recommended_first_source(candidates)
    return WeatherSourceAudit(
        generated_at=generated_at.isoformat(),
        mode="inventory",
        live_probing="not_run_static_registry" if not live_probe else "not_supported_static_registry_only",
        recommended_first_source=first_source.source_name,
        recommended_regions=recommended_regions(),
        candidates=candidates,
        daily_raw_variables=daily_raw_variables(),
        derived_feature_candidates=derived_feature_candidates(),
        recommendations=recommendations(),
        non_goals=non_goals(),
    )


def recommended_regions() -> tuple[WeatherRegion, ...]:
    return (
        WeatherRegion(
            region_code="br_mt_soybean_belt",
            region_name="Mato Grosso soybean belt",
            country="Brazil",
            crop="soybean",
            commodity_family="soybean",
            role="production/export",
            latitude=-12.6,
            longitude=-55.7,
            aggregation_strategy="region centroid point proxy",
            priority="high",
            reason_for_ml="Largest Brazilian soybean production area; weather shocks can move soybean, soybean oil, and soybean meal supply expectations.",
        ),
        WeatherRegion(
            region_code="br_pr_soybean_belt",
            region_name="Parana soybean belt",
            country="Brazil",
            crop="soybean",
            commodity_family="soybean",
            role="production/export",
            latitude=-24.9,
            longitude=-51.6,
            aggregation_strategy="region centroid point proxy",
            priority="high",
            reason_for_ml="Major southern Brazil soybean region with drought/frost sensitivity and export relevance.",
        ),
        WeatherRegion(
            region_code="us_ia_soybean_belt",
            region_name="Iowa soybean belt",
            country="United States",
            crop="soybean",
            commodity_family="soybean",
            role="production/export",
            latitude=42.0,
            longitude=-93.5,
            aggregation_strategy="state centroid point proxy",
            priority="high",
            reason_for_ml="Core US soybean state; precipitation and heat stress influence global oilseed market expectations.",
        ),
        WeatherRegion(
            region_code="us_il_soybean_belt",
            region_name="Illinois soybean belt",
            country="United States",
            crop="soybean",
            commodity_family="soybean",
            role="production/export",
            latitude=40.0,
            longitude=-89.2,
            aggregation_strategy="state centroid point proxy",
            priority="high",
            reason_for_ml="Core US soybean processing and production state; useful alongside Iowa for US crop-weather signal.",
        ),
        WeatherRegion(
            region_code="ar_pampas_soybean_belt",
            region_name="Argentina Pampas soybean belt",
            country="Argentina",
            crop="soybean",
            commodity_family="soybean",
            role="production/export",
            latitude=-33.3,
            longitude=-61.6,
            aggregation_strategy="multi-province centroid point proxy",
            priority="high",
            reason_for_ml="Represents Buenos Aires/Cordoba/Santa Fe soybean area; drought and heat shocks affect meal/oil export supply.",
        ),
        WeatherRegion(
            region_code="ca_sk_canola_belt",
            region_name="Saskatchewan canola belt",
            country="Canada",
            crop="canola/rapeseed",
            commodity_family="rapeseed",
            role="production/export",
            latitude=52.1,
            longitude=-106.7,
            aggregation_strategy="province centroid point proxy",
            priority="high",
            reason_for_ml="Largest Canadian canola production province; weather risk is directly relevant to rapeseed oil/meal context.",
        ),
        WeatherRegion(
            region_code="ca_ab_canola_belt",
            region_name="Alberta canola belt",
            country="Canada",
            crop="canola/rapeseed",
            commodity_family="rapeseed",
            role="production/export",
            latitude=53.9,
            longitude=-113.5,
            aggregation_strategy="province centroid point proxy",
            priority="high",
            reason_for_ml="Major canola production area; complements Saskatchewan for Canadian supply-weather signal.",
        ),
        WeatherRegion(
            region_code="ca_mb_canola_belt",
            region_name="Manitoba canola belt",
            country="Canada",
            crop="canola/rapeseed",
            commodity_family="rapeseed",
            role="production/export",
            latitude=50.4,
            longitude=-98.7,
            aggregation_strategy="province centroid point proxy",
            priority="medium",
            reason_for_ml="Adds eastern prairie canola coverage and moisture/heat contrast versus Saskatchewan/Alberta.",
        ),
        WeatherRegion(
            region_code="fr_rapeseed_region",
            region_name="France rapeseed region",
            country="France",
            crop="rapeseed",
            commodity_family="rapeseed",
            role="production",
            latitude=47.4,
            longitude=2.4,
            aggregation_strategy="country crop-region centroid point proxy",
            priority="medium",
            reason_for_ml="Important EU rapeseed producer; weather contributes to European oilseed supply expectations.",
        ),
        WeatherRegion(
            region_code="de_rapeseed_region",
            region_name="Germany rapeseed region",
            country="Germany",
            crop="rapeseed",
            commodity_family="rapeseed",
            role="production/processing",
            latitude=51.2,
            longitude=10.4,
            aggregation_strategy="country centroid point proxy",
            priority="medium",
            reason_for_ml="Major EU rapeseed and processing region; useful for European crush and supply context.",
        ),
        WeatherRegion(
            region_code="pl_rapeseed_region",
            region_name="Poland rapeseed region",
            country="Poland",
            crop="rapeseed",
            commodity_family="rapeseed",
            role="production",
            latitude=52.1,
            longitude=19.4,
            aggregation_strategy="country centroid point proxy",
            priority="medium",
            reason_for_ml="EU/Black Sea adjacent rapeseed weather proxy with growing regional relevance.",
        ),
        WeatherRegion(
            region_code="ua_black_sea_rapeseed_region",
            region_name="Ukraine / Black Sea rapeseed region",
            country="Ukraine",
            crop="rapeseed",
            commodity_family="rapeseed",
            role="production/export",
            latitude=49.0,
            longitude=31.0,
            aggregation_strategy="country crop-region centroid point proxy",
            priority="high",
            reason_for_ml="Black Sea rapeseed export weather is relevant for regional oilseed supply and price pressure.",
        ),
        WeatherRegion(
            region_code="cn_hubei_rapeseed_region",
            region_name="Hubei rapeseed region",
            country="China",
            crop="rapeseed",
            commodity_family="rapeseed",
            role="production/demand",
            latitude=30.6,
            longitude=112.3,
            aggregation_strategy="province centroid point proxy",
            priority="later",
            reason_for_ml="China rapeseed weather may help domestic context, but production regions abroad are first priority.",
        ),
        WeatherRegion(
            region_code="cn_coastal_processing_demand_proxy",
            region_name="China coastal oilseed processing proxy",
            country="China",
            crop="soybean/rapeseed",
            commodity_family="oilseed",
            role="import/demand/processing",
            latitude=31.2,
            longitude=121.5,
            aggregation_strategy="point proxy",
            priority="later",
            reason_for_ml="Weather is secondary for demand/processing, but may later proxy logistics disruptions around import/processing hubs.",
        ),
    )


def daily_raw_variables() -> tuple[str, ...]:
    return (
        "temperature_2m_mean",
        "temperature_2m_min",
        "temperature_2m_max",
        "precipitation_sum",
        "snowfall_sum",
        "relative_humidity_mean",
        "wind_speed_mean",
        "wind_speed_max",
        "soil_moisture",
        "evapotranspiration",
        "shortwave_radiation",
    )


def derived_feature_candidates() -> tuple[str, ...]:
    return (
        "precipitation_7d_sum",
        "precipitation_14d_sum",
        "precipitation_30d_sum",
        "temperature_7d_mean",
        "temperature_30d_mean",
        "heat_stress_days_7d",
        "heat_stress_days_30d",
        "frost_days_7d",
        "frost_days_30d",
        "drought_proxy_30d",
        "growing_degree_days",
        "anomaly_vs_historical_normal_later",
    )


def source_candidates() -> tuple[WeatherSourceCandidate, ...]:
    return (
        WeatherSourceCandidate(
            source_name="Open-Meteo Historical Weather API",
            source_url="https://open-meteo.com/en/docs/historical-weather-api",
            candidate_status="ready_to_prototype",
            auth_required=False,
            format="JSON or CSV",
            spatial_model="point",
            variables_available=(
                "temperature_2m_mean",
                "temperature_2m_min",
                "temperature_2m_max",
                "precipitation_sum",
                "snowfall_sum",
                "relative_humidity_2m_mean",
                "wind_speed_10m_mean",
                "wind_speed_10m_max",
                "shortwave_radiation_sum",
                "et0_fao_evapotranspiration",
            ),
            historical_depth="Historical daily archive by coordinate; exact model coverage varies by date and region.",
            frequency="daily and hourly options",
            rate_limits="Keyless public API; use small coordinate/date windows and cache raw responses.",
            license_notes="Review Open-Meteo terms and attribution before packaging exported datasets.",
            operational_risk="low",
            storage_risk="low for first centroid prototype",
            ml_value="High first prototype value because point daily weather can be aligned to commodity feature dates without secrets.",
            recommended_next_action="Use as first controlled prototype after weather schema design; start with high-priority centroid regions.",
        ),
        WeatherSourceCandidate(
            source_name="NASA POWER",
            source_url="https://power.larc.nasa.gov/",
            candidate_status="ready_to_prototype",
            auth_required=False,
            format="JSON/CSV API",
            spatial_model="point/grid-derived point",
            variables_available=(
                "temperature",
                "precipitation",
                "relative_humidity",
                "wind_speed",
                "soil_moisture_or_related_parameters",
                "solar_radiation",
                "evapotranspiration_related_parameters",
            ),
            historical_depth="Long agroclimatology-oriented daily history; parameter coverage should be verified per endpoint.",
            frequency="daily, monthly, climatology products",
            rate_limits="Keyless API; keep bounded coordinate/date requests and cache results.",
            license_notes="NASA data is generally open, but citation and parameter documentation should be preserved.",
            operational_risk="low_to_medium",
            storage_risk="low to medium depending on number of parameters and regions",
            ml_value="High for agricultural weather variables and radiation/evapotranspiration context.",
            recommended_next_action="Prototype after or alongside Open-Meteo if radiation/ET variables are needed early.",
        ),
        WeatherSourceCandidate(
            source_name="NOAA / NCEI",
            source_url="https://www.ncei.noaa.gov/",
            candidate_status="needs_manual_check",
            auth_required=False,
            format="API/CSV/station datasets",
            spatial_model="station and gridded products",
            variables_available=(
                "temperature",
                "precipitation",
                "snow",
                "wind",
                "station_metadata",
            ),
            historical_depth="Deep authoritative history, especially for US stations; global coverage and routes vary.",
            frequency="daily/hourly/product-specific",
            rate_limits="Dataset and endpoint specific; may require token for some APIs.",
            license_notes="Authoritative public data, but dataset-specific citation and access notes must be reviewed.",
            operational_risk="medium",
            storage_risk="medium because station selection and gaps need metadata handling",
            ml_value="High later for authoritative US crop-weather validation; not simplest first global prototype.",
            recommended_next_action="Manual-check station/grid route selection after first point-source prototype.",
        ),
        WeatherSourceCandidate(
            source_name="ERA5 / Copernicus Climate Data Store",
            source_url="https://cds.climate.copernicus.eu/",
            candidate_status="high_complexity",
            auth_required=True,
            format="NetCDF/GRIB/API downloads",
            spatial_model="grid",
            variables_available=(
                "temperature",
                "precipitation",
                "soil_moisture",
                "evaporation",
                "radiation",
                "wind",
                "many_reanalysis_variables",
            ),
            historical_depth="Rich reanalysis history over decades.",
            frequency="hourly/daily aggregates possible",
            rate_limits="Account/API workflow and large download management required.",
            license_notes="Copernicus license and attribution requirements must be reviewed.",
            operational_risk="high",
            storage_risk="high because gridded reanalysis volumes are large",
            ml_value="Very high later for robust gridded weather, but too heavy for first collector.",
            recommended_next_action="Defer until storage, account, gridding, and aggregation design are approved.",
        ),
        WeatherSourceCandidate(
            source_name="Meteostat",
            source_url="https://meteostat.net/",
            candidate_status="needs_manual_check",
            auth_required=False,
            format="Python library / API / station data",
            spatial_model="station",
            variables_available=(
                "temperature",
                "precipitation",
                "snow",
                "wind",
                "pressure",
                "station_metadata",
            ),
            historical_depth="Station history varies by location and station quality.",
            frequency="daily/hourly/monthly station observations",
            rate_limits="Library/API access and caching policy need review.",
            license_notes="License and redistribution terms need manual review before production export use.",
            operational_risk="medium",
            storage_risk="medium because station gaps and station selection must be modeled",
            ml_value="Medium as station-based fallback or validation source.",
            recommended_next_action="Manual-check license and station coverage for selected regions before prototype.",
        ),
    )


def recommendations() -> tuple[str, ...]:
    return (
        "Phase 6.3B should design weather_regions and weather_observations before any production writes.",
        "First source candidate: Open-Meteo Historical Weather API because it is keyless, point-based, bounded, and easy to align with daily feature dates.",
        "Initial regions should cover Brazil, US, and Argentina soybean belts plus Canada and Black Sea/EU rapeseed/canola regions.",
        "Start with centroid point proxies; expand to multi-point/gridded aggregation only after schema and storage policy are reviewed.",
        "Use only weather observed on or before the commodity feature_date; rolling features must use past days only.",
        "Defer ERA5/Copernicus until storage and account complexity are justified.",
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
    )


def write_audit_outputs(audit: WeatherSourceAudit, output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "weather_source_candidates.json").write_text(
        json.dumps(audit_to_dict(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "WEATHER_SOURCE_AUDIT_REPORT.md").write_text(render_report(audit), encoding="utf-8")


def render_report(audit: WeatherSourceAudit) -> str:
    counts = count_by_status(audit.candidates)
    lines = [
        "# Weather Source And Region Audit",
        "",
        "## Executive Summary",
        "",
        "Phase 6.3A is local diagnostics/discovery-only. It does not write PostgreSQL rows, does not create collectors, does not use RawStore, does not change scheduler settings, and does not add ML targets.",
        "",
        f"Live probing: `{audit.live_probing}`. This report uses a curated static registry and performs no HTTP requests.",
        "",
        f"Recommended first source: `{audit.recommended_first_source}`. It is keyless, point-based, compact enough for a first centroid prototype, and can provide daily weather aligned to commodity feature dates.",
        "",
        "## Why Weather Matters For Agricultural Commodity Price Forecasting",
        "",
        "Weather drives yield expectations, harvest timing, crop stress, export supply risk, and crushing/input economics for oilseeds and meals. Soybean oil and soybean meal are sensitive to soybean crop conditions in Brazil, the United States, and Argentina. Rapeseed oil and rapeseed meal are sensitive to canola/rapeseed conditions in Canada, Europe, and the Black Sea region.",
        "",
        "## Current Product Families",
        "",
        "- `soybean`: `soybean_oil`, `soybean_meal`.",
        "- `rapeseed/canola`: `rapeseed_oil`, `rapeseed_meal`.",
        "",
        "## Recommended First Source",
        "",
        "Use Open-Meteo Historical Weather API for the first controlled prototype after schema design. It supports point-coordinate historical weather without API keys, which fits the initial centroid-region approach. NASA POWER is the strongest second candidate, especially for radiation and evapotranspiration.",
        "",
        "## Recommended First Regions",
        "",
        "Start with high-priority centroid proxies for Brazil, US, Argentina, Canada, and Ukraine/Black Sea. Medium-priority EU regions can be included if the first collector remains small. China production and processing/demand proxies are later candidates.",
        "",
        "## Region Table",
        "",
        "| region_code | region_name | country | crop | family | role | lat | lon | aggregation | priority | reason |",
        "|---|---|---|---|---|---|---:|---:|---|---|---|",
    ]
    for region in audit.recommended_regions:
        lines.append(
            "| {code} | {name} | {country} | {crop} | {family} | {role} | {lat:.4f} | {lon:.4f} | {agg} | {priority} | {reason} |".format(
                code=region.region_code,
                name=region.region_name,
                country=region.country,
                crop=region.crop,
                family=region.commodity_family,
                role=region.role,
                lat=region.latitude,
                lon=region.longitude,
                agg=region.aggregation_strategy,
                priority=region.priority,
                reason=region.reason_for_ml,
            )
        )

    lines.extend(
        [
            "",
            "## Weather Source Candidate Table",
            "",
            "| source | status | auth | format | spatial model | frequency | operational risk | storage risk |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for candidate in audit.candidates:
        lines.append(
            "| {source} | {status} | {auth} | {fmt} | {spatial} | {frequency} | {op_risk} | {storage_risk} |".format(
                source=candidate.source_name,
                status=candidate.candidate_status,
                auth="yes" if candidate.auth_required else "no",
                fmt=candidate.format,
                spatial=candidate.spatial_model,
                frequency=candidate.frequency,
                op_risk=candidate.operational_risk,
                storage_risk=candidate.storage_risk,
            )
        )

    lines.extend(["", "## Source-By-Source Analysis", ""])
    for candidate in audit.candidates:
        lines.extend(
            [
                f"### {candidate.source_name}",
                "",
                f"- URL: {candidate.source_url}",
                f"- Status: `{candidate.candidate_status}`",
                f"- Auth required: {candidate.auth_required}",
                f"- Format: {candidate.format}",
                f"- Spatial model: {candidate.spatial_model}",
                f"- Historical depth: {candidate.historical_depth}",
                f"- Frequency: {candidate.frequency}",
                f"- Rate limits: {candidate.rate_limits}",
                f"- License notes: {candidate.license_notes}",
                f"- Operational risk: {candidate.operational_risk}",
                f"- Storage risk: {candidate.storage_risk}",
                f"- ML value: {candidate.ml_value}",
                f"- Recommended next action: {candidate.recommended_next_action}",
                f"- Variables: {', '.join(candidate.variables_available)}",
                "",
            ]
        )

    lines.extend(
        [
            "## Weather Variable Design",
            "",
            "Daily raw variables:",
            "",
        ]
    )
    for item in audit.daily_raw_variables:
        lines.append(f"- `{item}`")
    lines.extend(["", "Derived future features:", ""])
    for item in audit.derived_feature_candidates:
        lines.append(f"- `{item}`")

    lines.extend(
        [
            "",
            "## Future Schema Proposal",
            "",
            "- `weather_regions`: stable region metadata, crop/family role, coordinates, priority, and aggregation strategy.",
            "- `weather_observations`: raw daily weather rows by region/source/date with raw response linkage and source hashes.",
            "- `weather_daily_features` or `weather_aggregates`: derived rolling/weather stress features built from observations after schema and as-of policy are reviewed.",
            "",
            "## As-Of And Leakage Policy",
            "",
            "- Weather features must be aligned by local feature date.",
            "- For a daily commodity `feature_date`, use weather observed on or before `feature_date` only.",
            "- Rolling windows must use past days only; no future weather values can enter precipitation, temperature, heat, frost, drought, or GDD features.",
            "- Store `observed_at`, `fetched_at`, and `published_at` when available. Historical backfill should not be treated as available before it was fetched in real-time simulation modes.",
            "",
            "## Storage And Rate-Limit Risks",
            "",
            "- Point-source Open-Meteo/NASA POWER prototypes are low storage risk for the initial region list.",
            "- Station sources need station metadata, gap handling, and station selection policy.",
            "- ERA5/Copernicus gridded data is high storage and operational complexity; defer until the value justifies account, download, and aggregation design.",
            "- Cache raw responses in future production collectors; this discovery step intentionally writes only diagnostics artifacts.",
            "",
            "## Proposed Future Phases",
            "",
            "- Phase 6.3B: weather schema design.",
            "- Phase 6.3C: weather schema implementation.",
            "- Phase 6.3D: first controlled weather collector.",
            "- Phase 6.3E: weather features/export integration.",
            "",
            "## Explicit Non-Goals",
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


def audit_to_dict(audit: WeatherSourceAudit) -> dict[str, Any]:
    return {
        "generated_at": audit.generated_at,
        "mode": audit.mode,
        "live_probing": audit.live_probing,
        "recommended_first_source": audit.recommended_first_source,
        "recommended_regions": [region_to_dict(region) for region in audit.recommended_regions],
        "candidates": [candidate_to_dict(candidate) for candidate in audit.candidates],
        "daily_raw_variables": list(audit.daily_raw_variables),
        "derived_feature_candidates": list(audit.derived_feature_candidates),
        "recommendations": list(audit.recommendations),
        "non_goals": list(audit.non_goals),
    }


def region_to_dict(region: WeatherRegion) -> dict[str, Any]:
    return asdict(region)


def candidate_to_dict(candidate: WeatherSourceCandidate) -> dict[str, Any]:
    data = asdict(candidate)
    data["variables_available"] = list(candidate.variables_available)
    return data


def count_by_status(candidates: tuple[WeatherSourceCandidate, ...] | None = None) -> dict[str, int]:
    candidates = candidates or source_candidates()
    counts = {status: 0 for status in VALID_CANDIDATE_STATUSES}
    for candidate in candidates:
        counts[candidate.candidate_status] = counts.get(candidate.candidate_status, 0) + 1
    return counts


def recommended_first_source(candidates: tuple[WeatherSourceCandidate, ...] | None = None) -> WeatherSourceCandidate:
    candidates = candidates or source_candidates()
    for candidate in candidates:
        if candidate.source_name == "Open-Meteo Historical Weather API":
            return candidate
    raise ValueError("Open-Meteo Historical Weather API candidate is missing")
