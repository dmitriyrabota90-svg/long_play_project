from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


CandidateStatus = Literal["ready_to_prototype", "needs_manual_check", "high_risk", "reject"]

VALID_CANDIDATE_STATUSES = {"ready_to_prototype", "needs_manual_check", "high_risk", "reject"}
OUTPUT_DIR = Path("diagnostics/commodity_benchmark_audit")


@dataclass(frozen=True)
class BenchmarkInstrumentCandidate:
    instrument_code: str
    title: str
    external_id: str
    unit: str
    frequency: str
    history_depth: str
    notes: str


@dataclass(frozen=True)
class CommodityBenchmarkSourceCandidate:
    source_name: str
    source_url: str
    candidate_status: CandidateStatus
    data_domain: str
    instruments: tuple[BenchmarkInstrumentCandidate, ...]
    format: str
    frequency: str
    history_depth: str
    auth_required: bool
    rate_limits: str
    license_notes: str
    operational_risk: str
    unit_notes: str
    publication_delay_notes: str
    ml_value: str
    recommended_next_action: str

    def __post_init__(self) -> None:
        if self.candidate_status not in VALID_CANDIDATE_STATUSES:
            raise ValueError(f"invalid candidate_status: {self.candidate_status}")


@dataclass(frozen=True)
class CommodityBenchmarkAudit:
    generated_at: str
    mode: str
    live_probing: str
    recommended_first_source: str
    candidates: tuple[CommodityBenchmarkSourceCandidate, ...]
    recommendations: tuple[str, ...]
    non_goals: tuple[str, ...]


def build_audit(*, generated_at: datetime | None = None, live_probe: bool = False) -> CommodityBenchmarkAudit:
    generated_at = generated_at or datetime.now(timezone.utc)
    candidates = source_candidates()
    first_source = recommended_first_source(candidates)
    return CommodityBenchmarkAudit(
        generated_at=generated_at.isoformat(),
        mode="inventory",
        live_probing="not_run_static_registry",
        recommended_first_source=first_source.source_name,
        candidates=candidates,
        recommendations=recommendations(),
        non_goals=non_goals(),
    )


def source_candidates() -> tuple[CommodityBenchmarkSourceCandidate, ...]:
    return (
        CommodityBenchmarkSourceCandidate(
            source_name="World Bank Pink Sheet",
            source_url="https://www.worldbank.org/en/research/commodity-markets",
            candidate_status="ready_to_prototype",
            data_domain="monthly_global_commodity_prices",
            instruments=(
                BenchmarkInstrumentCandidate(
                    instrument_code="worldbank_soybean_oil",
                    title="Soybean oil benchmark",
                    external_id="Pink Sheet soybean oil series",
                    unit="USD per metric ton",
                    frequency="monthly",
                    history_depth="Long monthly history in World Bank commodity price workbooks.",
                    notes="Exact workbook column name should be mapped in the collector prototype.",
                ),
                BenchmarkInstrumentCandidate(
                    instrument_code="worldbank_soybeans",
                    title="Soybeans benchmark",
                    external_id="Pink Sheet soybeans series",
                    unit="USD per metric ton",
                    frequency="monthly",
                    history_depth="Long monthly history in World Bank commodity price workbooks.",
                    notes="Useful anchor for soybean oil and soybean meal market context.",
                ),
                BenchmarkInstrumentCandidate(
                    instrument_code="worldbank_palm_oil",
                    title="Palm oil benchmark",
                    external_id="Pink Sheet palm oil series",
                    unit="USD per metric ton",
                    frequency="monthly",
                    history_depth="Long monthly history in World Bank commodity price workbooks.",
                    notes="Important substitute oil benchmark for vegetable oils.",
                ),
                BenchmarkInstrumentCandidate(
                    instrument_code="worldbank_maize",
                    title="Maize/corn benchmark",
                    external_id="Pink Sheet maize series",
                    unit="USD per metric ton",
                    frequency="monthly",
                    history_depth="Long monthly history in World Bank commodity price workbooks.",
                    notes="Relevant feed and biofuel cross-market indicator.",
                ),
                BenchmarkInstrumentCandidate(
                    instrument_code="worldbank_wheat",
                    title="Wheat benchmark",
                    external_id="Pink Sheet wheat series",
                    unit="USD per metric ton",
                    frequency="monthly",
                    history_depth="Long monthly history in World Bank commodity price workbooks.",
                    notes="Broad grain benchmark for agricultural market regime features.",
                ),
                BenchmarkInstrumentCandidate(
                    instrument_code="worldbank_fertilizer_index",
                    title="Fertilizer price index",
                    external_id="Pink Sheet fertilizer index",
                    unit="index",
                    frequency="monthly",
                    history_depth="Long monthly history in World Bank commodity price workbooks.",
                    notes="Input-cost proxy; unit/index normalization required before feature use.",
                ),
            ),
            format="XLS/XLSX",
            frequency="monthly",
            history_depth="Long monthly history, commonly used for commodity market analysis.",
            auth_required=False,
            rate_limits="Low-frequency workbook download only; cache raw workbook and avoid repeated large downloads.",
            license_notes="Verify World Bank citation and redistribution requirements before packaging exported datasets.",
            operational_risk="low",
            unit_notes="Mixed units and index values; store original units and normalized units explicitly.",
            publication_delay_notes="Monthly publication can lag current market prices; use published/fetched timestamps for as-of safety.",
            ml_value="High as broad global benchmark context for oils, grains, and input costs.",
            recommended_next_action="Phase 6.2B should design commodity_benchmarks schema around monthly benchmark bars; Phase 6.2D can prototype this first.",
        ),
        CommodityBenchmarkSourceCandidate(
            source_name="FAO Food Price Index",
            source_url="https://www.fao.org/worldfoodsituation/foodpricesindex/en/",
            candidate_status="ready_to_prototype",
            data_domain="monthly_food_and_agriculture_indices",
            instruments=(
                BenchmarkInstrumentCandidate(
                    instrument_code="fao_food_price_index",
                    title="FAO Food Price Index",
                    external_id="FAO Food Price Index",
                    unit="index",
                    frequency="monthly",
                    history_depth="Monthly index history; exact machine-readable endpoint needs prototype.",
                    notes="Broad food market pressure feature.",
                ),
                BenchmarkInstrumentCandidate(
                    instrument_code="fao_vegetable_oils_index",
                    title="FAO Vegetable Oils Price Index",
                    external_id="FAO vegetable oils index",
                    unit="index",
                    frequency="monthly",
                    history_depth="Monthly index history; exact endpoint needs prototype.",
                    notes="Directly relevant to soybean, rapeseed, and sunflower oil markets.",
                ),
                BenchmarkInstrumentCandidate(
                    instrument_code="fao_cereals_index",
                    title="FAO Cereals Price Index",
                    external_id="FAO cereals index",
                    unit="index",
                    frequency="monthly",
                    history_depth="Monthly index history; exact endpoint needs prototype.",
                    notes="Useful broad grain-market regime feature.",
                ),
            ),
            format="CSV/XLS/page-linked data",
            frequency="monthly",
            history_depth="Monthly historical indices; endpoint and revision notes need manual verification.",
            auth_required=False,
            rate_limits="Low-frequency download; avoid page crawling.",
            license_notes="Verify FAO reuse/citation requirements before distributing derived exports.",
            operational_risk="medium",
            unit_notes="Index values, not physical commodity prices; keep separate benchmark_type/frequency fields.",
            publication_delay_notes="Monthly publication delay; should use published_at or fetched_at for feature as-of cutoff.",
            ml_value="High for market-regime features, especially vegetable oils and cereals.",
            recommended_next_action="Prototype after World Bank or in parallel if a stable machine-readable file is confirmed.",
        ),
        CommodityBenchmarkSourceCandidate(
            source_name="FRED commodity proxies",
            source_url="https://fred.stlouisfed.org/",
            candidate_status="needs_manual_check",
            data_domain="macro_and_commodity_proxy_series",
            instruments=(
                BenchmarkInstrumentCandidate(
                    instrument_code="fred_grain_oilseed_candidates",
                    title="Possible grains/oilseeds/fertilizer proxy series",
                    external_id="series discovery required",
                    unit="series-specific",
                    frequency="daily/weekly/monthly",
                    history_depth="Series-specific, often long history if available.",
                    notes="Energy FRED series are already implemented separately; benchmark commodity candidates need exact series IDs.",
                ),
            ),
            format="CSV",
            frequency="series-specific",
            history_depth="Series-specific.",
            auth_required=False,
            rate_limits="Use bounded graph CSV requests; no API key for graph CSV.",
            license_notes="Review series source notes and citation requirements for every selected series.",
            operational_risk="medium",
            unit_notes="Series units vary; do not assume physical prices.",
            publication_delay_notes="Series-specific release delays.",
            ml_value="Medium; useful for selected macro/commodity proxies if stable series IDs are found.",
            recommended_next_action="Run a separate series-ID discovery pass before schema or collector work.",
        ),
        CommodityBenchmarkSourceCandidate(
            source_name="USDA WASDE / PSD / AMS sources",
            source_url="https://www.usda.gov/oce/commodity/wasde",
            candidate_status="needs_manual_check",
            data_domain="supply_demand_and_market_reports",
            instruments=(
                BenchmarkInstrumentCandidate(
                    instrument_code="usda_oilseed_supply_demand",
                    title="Oilseed supply-demand indicators",
                    external_id="WASDE/PSD oilseed tables",
                    unit="table-specific",
                    frequency="monthly",
                    history_depth="Deep official report history, but parsing model needs separate design.",
                    notes="Potentially valuable for stocks/use/production indicators, not simple price benchmark rows.",
                ),
                BenchmarkInstrumentCandidate(
                    instrument_code="usda_grain_supply_demand",
                    title="Grain supply-demand indicators",
                    external_id="WASDE/PSD grain tables",
                    unit="table-specific",
                    frequency="monthly",
                    history_depth="Deep official report history, but parsing model needs separate design.",
                    notes="Useful later for fundamentals; do not mix into commodity price benchmark collector.",
                ),
            ),
            format="PDF/CSV/API/table files depending on product",
            frequency="monthly and report-specific",
            history_depth="Long official history, but route and format vary.",
            auth_required=False,
            rate_limits="Low request volume; avoid report crawling.",
            license_notes="Public official data, but citation and redistribution notes should be reviewed.",
            operational_risk="medium",
            unit_notes="Often fundamentals, not price units; likely separate schema from commodity_benchmarks.",
            publication_delay_notes="Report release schedule must be modeled through published_at/fetched_at.",
            ml_value="High later, but better as fundamentals/supply-demand features rather than first benchmark collector.",
            recommended_next_action="Defer to a dedicated fundamentals discovery/design phase after benchmark price schema.",
        ),
        CommodityBenchmarkSourceCandidate(
            source_name="Nasdaq Data Link",
            source_url="https://data.nasdaq.com/",
            candidate_status="high_risk",
            data_domain="commercial_market_and_alternative_data",
            instruments=(
                BenchmarkInstrumentCandidate(
                    instrument_code="nasdaq_grains_oils_candidates",
                    title="Possible grains, oils, futures, or alternative benchmark datasets",
                    external_id="dataset-specific",
                    unit="dataset-specific",
                    frequency="dataset-specific",
                    history_depth="Dataset-specific and plan-dependent.",
                    notes="Do not treat as production-ready without access, pricing, and redistribution review.",
                ),
            ),
            format="API/CSV",
            frequency="dataset-specific",
            history_depth="dataset-specific",
            auth_required=True,
            rate_limits="API key, plan, and dataset limits likely.",
            license_notes="Commercial/subscription licensing may restrict dataset export use.",
            operational_risk="high",
            unit_notes="Dataset-specific; normalize only after selected dataset review.",
            publication_delay_notes="Dataset-specific.",
            ml_value="Potentially useful, but not appropriate as first open benchmark source.",
            recommended_next_action="Do not prototype until licensing, cost, and redistribution terms are approved.",
        ),
        CommodityBenchmarkSourceCandidate(
            source_name="Stooq / Yahoo-like market endpoints",
            source_url="manual-check-only",
            candidate_status="high_risk",
            data_domain="unofficial_or_scraped_market_data",
            instruments=(
                BenchmarkInstrumentCandidate(
                    instrument_code="unofficial_futures_candidates",
                    title="Possible commodity futures symbols",
                    external_id="symbol discovery required",
                    unit="market-dependent",
                    frequency="daily/intraday",
                    history_depth="Potentially long but terms and symbol stability are uncertain.",
                    notes="Avoid broad scraping and unofficial endpoints for production evidence.",
                ),
            ),
            format="HTML/CSV/API varies",
            frequency="varies",
            history_depth="varies",
            auth_required=False,
            rate_limits="Unknown; broad download risk.",
            license_notes="High uncertainty; manual terms review required.",
            operational_risk="high",
            unit_notes="Market-specific and possibly adjusted; not comparable without careful metadata.",
            publication_delay_notes="Unknown.",
            ml_value="Low until source stability and legal status are clear.",
            recommended_next_action="Reject for production collector design unless a stable, licensed endpoint is confirmed.",
        ),
        CommodityBenchmarkSourceCandidate(
            source_name="Jijinhao/Cngold regional source",
            source_url="https://api.jijinhao.com/",
            candidate_status="reject",
            data_domain="regional_chinese_market_prices",
            instruments=(
                BenchmarkInstrumentCandidate(
                    instrument_code="jijinhao_current_confirmed_products",
                    title="Confirmed Chinese current-price instruments",
                    external_id="JO_166042, JO_165951, JO_166106, JO_165938",
                    unit="CNY per metric ton",
                    frequency="current snapshots / compact history",
                    history_depth="Project already has current and historical collection paths.",
                    notes="Useful regional price source, but not a global benchmark source by itself.",
                ),
            ),
            format="JSON/CSV-like API responses",
            frequency="current snapshots and source-specific history",
            history_depth="Source-specific.",
            auth_required=False,
            rate_limits="Use bounded requests; no broad crawling.",
            license_notes="Manual source terms review remains needed.",
            operational_risk="medium",
            unit_notes="Regional CNY prices; do not label as global benchmark.",
            publication_delay_notes="Source-specific and not comparable with monthly global benchmarks.",
            ml_value="Already useful as target/source market signal, but not the global benchmark layer requested here.",
            recommended_next_action="Keep separate from commodity_benchmarks; do not use as first global benchmark source.",
        ),
    )


def recommendations() -> tuple[str, ...]:
    return (
        "Phase 6.2B should design a commodity_benchmarks schema before any production writes.",
        "First benchmark source candidate: World Bank Pink Sheet because it is broad, stable, monthly, and covers oils, grains, and fertilizers.",
        "First instruments should include soybean oil, soybeans, palm oil, maize/corn, wheat, fertilizer index, vegetable oils index, and cereals index where source mappings are confirmed.",
        "FAO indices are a strong second prototype for vegetable oils and cereals market-regime features.",
        "USDA/WASDE/PSD should be treated as a later fundamentals design, not the first price benchmark collector.",
        "Do not use unofficial finance scraping or commercial datasets until terms, access, and redistribution are approved.",
    )


def non_goals() -> tuple[str, ...]:
    return (
        "No production DB writes.",
        "No collectors.",
        "No scheduler changes.",
        "No migrations.",
        "No ML model.",
        "No targets.",
    )


def write_audit_outputs(audit: CommodityBenchmarkAudit, output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "commodity_benchmark_candidates.json").write_text(
        json.dumps(audit_to_dict(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "COMMODITY_BENCHMARK_AUDIT_REPORT.md").write_text(render_report(audit), encoding="utf-8")


def render_report(audit: CommodityBenchmarkAudit) -> str:
    counts = count_by_status(audit.candidates)
    lines = [
        "# Commodity Benchmark Source Audit",
        "",
        "## Executive Summary",
        "",
        "Phase 6.2A is local diagnostics/discovery-only. It does not write PostgreSQL rows, does not create collectors, does not change scheduler settings, and does not add ML targets.",
        "",
        f"Live probing: `{audit.live_probing}`. This report uses a curated static registry and performs no HTTP requests.",
        "",
        "Recommended first source: `World Bank Pink Sheet`. It is broad, stable, monthly, and covers oils, grains, fertilizers, energy, and other commodity benchmarks that can contextualize agricultural price movements.",
        "",
        "## Why Global Commodity Benchmarks Matter",
        "",
        "Global benchmarks help separate local/regional price movements from wider agricultural market regimes. Monthly oils, grains, and fertilizer benchmarks can capture substitution pressure, feed and biofuel context, input-cost pressure, and macro commodity cycles for future forecasting datasets.",
        "",
        "## Candidate Source Table",
        "",
        "| source | status | domain | format | frequency | auth | risk | instruments |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for candidate in audit.candidates:
        instruments = ", ".join(item.instrument_code for item in candidate.instruments)
        lines.append(
            "| {source} | {status} | {domain} | {fmt} | {frequency} | {auth} | {risk} | {instruments} |".format(
                source=candidate.source_name,
                status=candidate.candidate_status,
                domain=candidate.data_domain,
                fmt=candidate.format,
                frequency=candidate.frequency,
                auth="yes" if candidate.auth_required else "no",
                risk=candidate.operational_risk,
                instruments=instruments,
            )
        )

    lines.extend(
        [
            "",
            "## Recommended First Source",
            "",
            "Use World Bank Pink Sheet as the first production prototype candidate. It provides monthly global benchmark prices across agriculture, oils, grains, energy, and fertilizers with stable publication practices. Its lower frequency is a feature, not a bug: it can become a broad market-regime layer rather than a replacement for current local price snapshots.",
            "",
            "## Recommended First Instruments And Indices",
            "",
            "- World Bank soybean oil benchmark.",
            "- World Bank soybeans benchmark.",
            "- World Bank palm oil benchmark.",
            "- World Bank maize/corn benchmark.",
            "- World Bank wheat benchmark.",
            "- World Bank fertilizer index.",
            "- FAO vegetable oils index.",
            "- FAO cereals index.",
            "- Broad agriculture/food index where source mapping is confirmed.",
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
                f"- Data domain: {candidate.data_domain}",
                f"- Format: {candidate.format}",
                f"- Frequency: {candidate.frequency}",
                f"- History depth: {candidate.history_depth}",
                f"- Auth required: {candidate.auth_required}",
                f"- Rate limits: {candidate.rate_limits}",
                f"- License notes: {candidate.license_notes}",
                f"- Operational risk: {candidate.operational_risk}",
                f"- Unit notes: {candidate.unit_notes}",
                f"- Publication delay notes: {candidate.publication_delay_notes}",
                f"- ML value: {candidate.ml_value}",
                f"- Recommended next action: {candidate.recommended_next_action}",
                "",
                "| instrument | external id | unit | frequency | notes |",
                "|---|---|---|---|---|",
            ]
        )
        for instrument in candidate.instruments:
            lines.append(
                f"| {instrument.instrument_code} | {instrument.external_id} | {instrument.unit} | {instrument.frequency} | {instrument.notes} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Frequency Comparison",
            "",
            "- Daily: useful for liquid market or FRED-like proxy series, but source availability for grains/oils must be verified.",
            "- Weekly: useful for fuel/logistics and selected official updates.",
            "- Monthly: best first global benchmark layer via World Bank and FAO; use as market-regime features with publication lag.",
            "",
            "## Unit And Frequency Normalization Risks",
            "",
            "- Physical prices, index values, and fundamentals must not be mixed without metadata.",
            "- Store original units and normalized units separately.",
            "- Monthly values must be forward-filled only with explicit as-of policy and publication/fetched timestamps.",
            "- Publication lag is part of the data: future feature builders must not treat a monthly value as known before it was published/fetched.",
            "",
            "## Licensing And Access Risks",
            "",
            "- World Bank and FAO require citation/reuse review before packaging into exported datasets.",
            "- Commercial/keyed providers can restrict redistribution and should not be first production sources.",
            "- Unofficial scraped endpoints have high operational and legal risk.",
            "",
            "## Operational Risks",
            "",
            "- Large workbooks should be cached as raw evidence and downloaded only on controlled schedules.",
            "- Schema must support monthly and index data without pretending it is daily spot price data.",
            "- Collector idempotency should key by source, benchmark code, frequency, and period range.",
            "",
            "## Proposed Future Schema",
            "",
            "Design-only table: `commodity_benchmarks`.",
            "",
            "Suggested fields: `id`, `source_id`, `raw_response_id`, `collector_run_id`, `benchmark_code`, `benchmark_name`, `benchmark_group`, `frequency`, `period_start`, `period_end`, `observed_at`, `published_at`, `fetched_at`, `value`, `currency`, `unit`, `normalized_value`, `normalized_currency`, `normalized_unit`, `source_record_hash`, `source_payload_hash`, `metadata_json`, `created_at`, `updated_at`.",
            "",
            "Production collectors must store raw evidence through `raw_responses` and `RawStore`; this discovery step intentionally does neither.",
            "",
            "## Proposed Future Phases",
            "",
            "- Phase 6.2B: design `commodity_benchmarks` schema.",
            "- Phase 6.2C: non-destructive schema migration.",
            "- Phase 6.2D: first controlled/manual benchmark collector, likely World Bank Pink Sheet.",
            "- Phase 6.2E: benchmark features/export integration with leakage-safe as-of policy.",
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


def audit_to_dict(audit: CommodityBenchmarkAudit) -> dict[str, Any]:
    return {
        "generated_at": audit.generated_at,
        "mode": audit.mode,
        "live_probing": audit.live_probing,
        "recommended_first_source": audit.recommended_first_source,
        "candidates": [candidate_to_dict(candidate) for candidate in audit.candidates],
        "recommendations": list(audit.recommendations),
        "non_goals": list(audit.non_goals),
    }


def candidate_to_dict(candidate: CommodityBenchmarkSourceCandidate) -> dict[str, Any]:
    data = asdict(candidate)
    data["instruments"] = [asdict(item) for item in candidate.instruments]
    return data


def count_by_status(
    candidates: tuple[CommodityBenchmarkSourceCandidate, ...] | None = None,
) -> dict[str, int]:
    candidates = candidates or source_candidates()
    counts = {status: 0 for status in VALID_CANDIDATE_STATUSES}
    for candidate in candidates:
        counts[candidate.candidate_status] = counts.get(candidate.candidate_status, 0) + 1
    return counts


def high_risk_candidates(
    candidates: tuple[CommodityBenchmarkSourceCandidate, ...] | None = None,
) -> tuple[CommodityBenchmarkSourceCandidate, ...]:
    candidates = candidates or source_candidates()
    return tuple(candidate for candidate in candidates if candidate.candidate_status in {"high_risk", "reject"})


def recommended_first_source(
    candidates: tuple[CommodityBenchmarkSourceCandidate, ...] | None = None,
) -> CommodityBenchmarkSourceCandidate:
    candidates = candidates or source_candidates()
    for candidate in candidates:
        if candidate.source_name == "World Bank Pink Sheet":
            return candidate
    raise ValueError("World Bank Pink Sheet candidate is missing")
