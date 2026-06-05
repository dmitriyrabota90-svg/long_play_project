from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


RecommendedStatus = Literal["ready_to_prototype", "needs_manual_check", "high_risk", "reject"]

VALID_RECOMMENDED_STATUSES = {"ready_to_prototype", "needs_manual_check", "high_risk", "reject"}
OUTPUT_DIR = Path("diagnostics/energy_source_audit")


@dataclass(frozen=True)
class EnergyInstrumentCandidate:
    instrument_code: str
    title: str
    external_id: str
    unit: str
    frequency: str
    history_depth: str
    notes: str


@dataclass(frozen=True)
class EnergySourceCandidate:
    source_name: str
    source_url: str
    data_type: str
    instruments: tuple[EnergyInstrumentCandidate, ...]
    format: str
    frequency: str
    history_depth: str
    auth_required: bool
    rate_limits: str
    license_notes: str
    operational_risk: str
    recommended_status: RecommendedStatus
    notes: str

    def __post_init__(self) -> None:
        if self.recommended_status not in VALID_RECOMMENDED_STATUSES:
            raise ValueError(f"invalid recommended_status: {self.recommended_status}")


@dataclass(frozen=True)
class EnergySourceAudit:
    checked_at: str
    mode: str
    live_probing: str
    candidates: tuple[EnergySourceCandidate, ...]
    recommendations: tuple[str, ...]
    non_goals: tuple[str, ...]


def build_audit(*, checked_at: datetime | None = None, live_probe: bool = False) -> EnergySourceAudit:
    checked_at = checked_at or datetime.now(timezone.utc)
    live_probing = "not_supported" if live_probe else "not_run_static_registry"
    return EnergySourceAudit(
        checked_at=checked_at.isoformat(),
        mode="inventory",
        live_probing=live_probing,
        candidates=source_candidates(),
        recommendations=recommendations(),
        non_goals=non_goals(),
    )


def source_candidates() -> tuple[EnergySourceCandidate, ...]:
    return (
        EnergySourceCandidate(
            source_name="FRED EIA-derived CSV",
            source_url="https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU,DCOILWTICO,DHHNGSP,GASDESW",
            data_type="energy_spot_and_fuel_prices",
            instruments=(
                EnergyInstrumentCandidate(
                    instrument_code="brent_crude_oil",
                    title="Brent crude oil spot price",
                    external_id="DCOILBRENTEU",
                    unit="USD per barrel",
                    frequency="daily",
                    history_depth="Daily history via FRED/EIA spot prices.",
                    notes="FRED page identifies EIA as source, units as dollars per barrel, and frequency as daily.",
                ),
                EnergyInstrumentCandidate(
                    instrument_code="wti_crude_oil",
                    title="WTI crude oil spot price, Cushing Oklahoma",
                    external_id="DCOILWTICO",
                    unit="USD per barrel",
                    frequency="daily",
                    history_depth="Daily history via FRED/EIA spot prices.",
                    notes="FRED page identifies EIA as source, units as dollars per barrel, and frequency as daily.",
                ),
                EnergyInstrumentCandidate(
                    instrument_code="henry_hub_natural_gas",
                    title="Henry Hub natural gas spot price",
                    external_id="DHHNGSP",
                    unit="USD per million BTU",
                    frequency="daily",
                    history_depth="Daily history via FRED/EIA natural gas spot prices.",
                    notes="FRED page identifies EIA as source, units as dollars per million BTU, and frequency as daily.",
                ),
                EnergyInstrumentCandidate(
                    instrument_code="us_diesel_retail",
                    title="US diesel sales price",
                    external_id="GASDESW",
                    unit="USD per gallon",
                    frequency="weekly",
                    history_depth="Weekly history via FRED/EIA gasoline and diesel fuel update.",
                    notes="Useful diesel/fuel proxy; weekly ending Monday.",
                ),
            ),
            format="CSV",
            frequency="daily and weekly",
            history_depth="Long history depends on FRED series; sufficient for prototype and backfill discovery.",
            auth_required=False,
            rate_limits="No project-specific key. Use low-frequency bounded requests; verify FRED usage policy before production.",
            license_notes="Underlying source is EIA via FRED; FRED pages request review of copyright/series notes and citation.",
            operational_risk="low",
            recommended_status="ready_to_prototype",
            notes="Best first prototype candidate because one CSV endpoint can cover Brent, WTI, Henry Hub gas, and diesel proxy without secrets.",
        ),
        EnergySourceCandidate(
            source_name="EIA Open Data API v2",
            source_url="https://www.eia.gov/opendata/documentation.php",
            data_type="official_energy_prices_and_petroleum_products",
            instruments=(
                EnergyInstrumentCandidate(
                    instrument_code="wti_crude_oil",
                    title="WTI crude oil spot price",
                    external_id="EIA petroleum/spot price route",
                    unit="USD per barrel",
                    frequency="daily",
                    history_depth="Official EIA historical route; exact endpoint/facets need API-key prototype.",
                    notes="Official source for many FRED energy series.",
                ),
                EnergyInstrumentCandidate(
                    instrument_code="henry_hub_natural_gas",
                    title="Henry Hub natural gas spot price",
                    external_id="EIA natural gas spot/futures route",
                    unit="USD per million BTU",
                    frequency="daily",
                    history_depth="Official EIA historical route; exact endpoint/facets need API-key prototype.",
                    notes="Useful if the project accepts API-key based collectors.",
                ),
                EnergyInstrumentCandidate(
                    instrument_code="diesel_or_distillate_proxy",
                    title="Diesel or distillate fuel price proxies",
                    external_id="EIA gasoline/diesel fuel update routes",
                    unit="USD per gallon",
                    frequency="weekly",
                    history_depth="Official retail fuel history; exact endpoint/facets need API-key prototype.",
                    notes="Potential logistics/fuel-cost proxy for agricultural commodities.",
                ),
            ),
            format="JSON API",
            frequency="daily, weekly, monthly depending on route",
            history_depth="Deep official history but route-specific.",
            auth_required=True,
            rate_limits="Free API key required; EIA documents throttling and temporary suspension for excessive requests.",
            license_notes="EIA data is free of charge and should follow EIA reuse/copyright policy.",
            operational_risk="medium",
            recommended_status="needs_manual_check",
            notes="Best official long-term source after API key policy is accepted and exact routes/facets are prototyped.",
        ),
        EnergySourceCandidate(
            source_name="World Bank Pink Sheet",
            source_url="https://www.worldbank.org/en/research/commodity-markets",
            data_type="monthly_energy_commodity_benchmarks",
            instruments=(
                EnergyInstrumentCandidate(
                    instrument_code="worldbank_energy_index",
                    title="World Bank energy price index",
                    external_id="Pink Sheet energy index",
                    unit="index",
                    frequency="monthly",
                    history_depth="Monthly prices from 1960 to present are published in Pink Sheet workbooks.",
                    notes="Good benchmark feature, lower frequency than price observations.",
                ),
                EnergyInstrumentCandidate(
                    instrument_code="worldbank_crude_oil",
                    title="World Bank crude oil benchmarks",
                    external_id="Pink Sheet crude oil series",
                    unit="USD per barrel",
                    frequency="monthly",
                    history_depth="Monthly Pink Sheet history.",
                    notes="Can complement daily spot prices as a lower-frequency benchmark.",
                ),
                EnergyInstrumentCandidate(
                    instrument_code="worldbank_natural_gas",
                    title="World Bank natural gas benchmarks",
                    external_id="Pink Sheet natural gas series",
                    unit="USD per mmbtu or source-specific unit",
                    frequency="monthly",
                    history_depth="Monthly Pink Sheet history.",
                    notes="Useful for slow-moving global energy context.",
                ),
            ),
            format="XLS/XLSX",
            frequency="monthly",
            history_depth="1960-present monthly workbook family.",
            auth_required=False,
            rate_limits="Low-frequency workbook download; avoid repeated large downloads.",
            license_notes="World Bank commodity market data; verify redistribution and citation requirements before export packaging.",
            operational_risk="low",
            recommended_status="ready_to_prototype",
            notes="Recommended benchmark source, not a replacement for daily energy prices.",
        ),
        EnergySourceCandidate(
            source_name="Stooq public historical data",
            source_url="https://stooq.com/db/h/",
            data_type="market_price_history",
            instruments=(
                EnergyInstrumentCandidate(
                    instrument_code="energy_futures_candidates",
                    title="Possible crude oil, gas, and fuel futures symbols",
                    external_id="symbol discovery required",
                    unit="market dependent",
                    frequency="daily/intraday depending on symbol",
                    history_depth="Potentially deep files, but symbol coverage and terms require manual check.",
                    notes="Do not use as production-ready until symbols, license, and stability are verified.",
                ),
            ),
            format="CSV / downloadable database",
            frequency="daily and intraday",
            history_depth="Potentially deep historical data.",
            auth_required=False,
            rate_limits="Avoid broad downloads; symbol-specific bounded probes only.",
            license_notes="Manual terms review required before production.",
            operational_risk="medium",
            recommended_status="needs_manual_check",
            notes="Useful fallback for market data but not first production source.",
        ),
        EnergySourceCandidate(
            source_name="Nasdaq Data Link",
            source_url="https://data.nasdaq.com/",
            data_type="commercial_or_keyed_market_data",
            instruments=(
                EnergyInstrumentCandidate(
                    instrument_code="energy_market_data_candidates",
                    title="Energy futures and spot datasets",
                    external_id="dataset-specific",
                    unit="dataset-specific",
                    frequency="dataset-specific",
                    history_depth="Often good, but dataset-specific and may require subscription.",
                    notes="Treat as manual-check until access, price, and license are clear.",
                ),
            ),
            format="API / CSV",
            frequency="dataset-specific",
            history_depth="dataset-specific",
            auth_required=True,
            rate_limits="API key and plan limits likely.",
            license_notes="Commercial/subscription licensing may apply.",
            operational_risk="medium",
            recommended_status="needs_manual_check",
            notes="Not a first open-source collector candidate.",
        ),
        EnergySourceCandidate(
            source_name="Yahoo Finance / Investing / TradingEconomics-like endpoints",
            source_url="manual-check-only",
            data_type="unofficial_or_scraped_market_data",
            instruments=(
                EnergyInstrumentCandidate(
                    instrument_code="brent_wti_ng_futures_unofficial",
                    title="Brent, WTI, natural gas, diesel-like market contracts",
                    external_id="varies",
                    unit="market dependent",
                    frequency="daily/intraday",
                    history_depth="varies",
                    notes="Avoid scraping or unofficial endpoints as production evidence source.",
                ),
            ),
            format="HTML/API varies",
            frequency="varies",
            history_depth="varies",
            auth_required=True,
            rate_limits="Unknown or commercial.",
            license_notes="High legal/operational uncertainty.",
            operational_risk="high",
            recommended_status="high_risk",
            notes="Use only for manual comparison, not production collector design.",
        ),
    )


def recommendations() -> tuple[str, ...]:
    return (
        "Phase 6.1B should design an energy_prices table before any production writes.",
        "First prototype source: FRED EIA-derived CSV for Brent, WTI, Henry Hub natural gas, and US diesel proxy.",
        "Add World Bank Pink Sheet as a monthly benchmark candidate after daily/weekly source design is clear.",
        "Use EIA Open Data API only after accepting free API-key operational policy and exact route discovery.",
        "Reject broad scraping and unofficial finance endpoints for production collectors.",
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


def write_audit_outputs(audit: EnergySourceAudit, output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "energy_source_candidates.json").write_text(
        json.dumps(audit_to_dict(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "ENERGY_SOURCE_AUDIT_REPORT.md").write_text(render_report(audit), encoding="utf-8")


def render_report(audit: EnergySourceAudit) -> str:
    candidates = sorted(audit.candidates, key=lambda item: (item.recommended_status, item.source_name))
    lines = [
        "# Energy Source Audit",
        "",
        "## Executive Summary",
        "",
        "Phase 6.1A is diagnostics/discovery-only. It does not write PostgreSQL rows, does not create collectors, does not change scheduler settings, and does not add ML targets.",
        "",
        "Recommended first production prototype: FRED EIA-derived CSV for Brent crude oil, WTI crude oil, Henry Hub natural gas, and US diesel sales price proxy. It is simple, keyless for CSV download, and covers daily/weekly energy factors needed for agricultural price modeling.",
        "",
        "World Bank Pink Sheet is the best monthly benchmark complement. EIA Open Data API is official and rich, but needs an API key and route/facet prototype before production.",
        "",
        "## Why Energy/Oil Factors Matter",
        "",
        "Energy prices affect agricultural commodity prices through fuel, freight, crushing/processing costs, fertilizer and chemicals, biofuel demand, and macro inflation channels. Brent/WTI capture global oil pressure, Henry Hub captures natural gas/fertilizer/energy pressure, and diesel is a direct logistics proxy.",
        "",
        "## Candidate Source Table",
        "",
        "| source | status | format | frequency | auth | risk | instruments |",
        "|---|---|---|---|---|---|---|",
    ]
    for candidate in candidates:
        instrument_list = ", ".join(item.instrument_code for item in candidate.instruments)
        lines.append(
            "| {source} | {status} | {fmt} | {frequency} | {auth} | {risk} | {instruments} |".format(
                source=candidate.source_name,
                status=candidate.recommended_status,
                fmt=candidate.format,
                frequency=candidate.frequency,
                auth="yes" if candidate.auth_required else "no",
                risk=candidate.operational_risk,
                instruments=instrument_list,
            )
        )

    lines.extend(
        [
            "",
            "## Recommended First Production Source",
            "",
            "`FRED EIA-derived CSV` is the preferred first prototype because it can provide daily Brent, daily WTI, daily Henry Hub natural gas, and weekly US diesel proxy without storing secrets. Before production, confirm source citation/terms and implement bounded date-window requests.",
            "",
            "## Recommended Instruments",
            "",
            "- `brent_crude_oil` / `DCOILBRENTEU` / USD per barrel / daily",
            "- `wti_crude_oil` / `DCOILWTICO` / USD per barrel / daily",
            "- `henry_hub_natural_gas` / `DHHNGSP` / USD per million BTU / daily",
            "- `us_diesel_retail` / `GASDESW` / USD per gallon / weekly fuel proxy",
            "- `worldbank_energy_index` / monthly benchmark, later phase",
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
                f"- Status: `{candidate.recommended_status}`",
                f"- Data type: {candidate.data_type}",
                f"- Format: {candidate.format}",
                f"- Frequency: {candidate.frequency}",
                f"- History depth: {candidate.history_depth}",
                f"- Auth required: {candidate.auth_required}",
                f"- Rate limits: {candidate.rate_limits}",
                f"- License notes: {candidate.license_notes}",
                f"- Operational risk: {candidate.operational_risk}",
                f"- Notes: {candidate.notes}",
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
            "- Daily: Brent, WTI, Henry Hub via FRED/EIA-derived series.",
            "- Weekly: US diesel sales price proxy via FRED/EIA.",
            "- Monthly: World Bank Pink Sheet energy index and commodity benchmarks.",
            "",
            "## Data Quality Risks",
            "",
            "- Energy series can be revised or delayed; store `fetched_at`, `observed_at`, and source payload hash.",
            "- Daily series may have missing holidays/weekends; feature builder must use explicit as-of rules.",
            "- Units differ (`USD/barrel`, `USD/MMBtu`, `USD/gallon`, index values); normalize units before features.",
            "",
            "## Licensing/Access Risks",
            "",
            "- FRED pages ask users to review series notes/copyright and cite the source.",
            "- EIA API requires a free API key and throttling discipline.",
            "- World Bank workbook redistribution and citation should be checked before packaging exports.",
            "- Unofficial finance/scraping endpoints are high risk and should not be production sources.",
            "",
            "## Future Schema Proposal",
            "",
            "Design-only table: `energy_prices`.",
            "",
            "Suggested fields: `id`, `source_id`, `raw_response_id`, `instrument_code`, `external_id`, `frequency`, `observed_at`, `published_at`, `fetched_at`, `value`, `unit`, `currency`, `source_record_hash`, `created_at`, `updated_at`.",
            "",
            "Production collectors must store raw evidence through `raw_responses` and `RawStore`; this discovery step intentionally does neither.",
            "",
            "## Future Collector Plan",
            "",
            "- Phase 6.1B: schema design for `energy_prices`.",
            "- Phase 6.1C: non-destructive schema migration.",
            "- Phase 6.1D: first controlled/manual energy collector, likely FRED CSV.",
            "- Phase 6.1E: feature integration and export update with leakage-safe as-of policy.",
            "",
            "## Explicit Non-Goals",
            "",
        ]
    )
    for item in audit.non_goals:
        lines.append(f"- {item}")
    lines.extend(["", "## Recommendations", ""])
    for item in audit.recommendations:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def audit_to_dict(audit: EnergySourceAudit) -> dict[str, Any]:
    return {
        "checked_at": audit.checked_at,
        "mode": audit.mode,
        "live_probing": audit.live_probing,
        "candidates": [candidate_to_dict(candidate) for candidate in audit.candidates],
        "recommendations": list(audit.recommendations),
        "non_goals": list(audit.non_goals),
    }


def candidate_to_dict(candidate: EnergySourceCandidate) -> dict[str, Any]:
    data = asdict(candidate)
    data["instruments"] = [asdict(item) for item in candidate.instruments]
    return data


def high_risk_candidates(candidates: tuple[EnergySourceCandidate, ...] | None = None) -> tuple[EnergySourceCandidate, ...]:
    candidates = candidates or source_candidates()
    return tuple(candidate for candidate in candidates if candidate.recommended_status in {"high_risk", "reject"})


def recommended_first_source(candidates: tuple[EnergySourceCandidate, ...] | None = None) -> EnergySourceCandidate:
    candidates = candidates or source_candidates()
    for candidate in candidates:
        if candidate.source_name == "FRED EIA-derived CSV":
            return candidate
    raise ValueError("FRED EIA-derived CSV candidate is missing")
