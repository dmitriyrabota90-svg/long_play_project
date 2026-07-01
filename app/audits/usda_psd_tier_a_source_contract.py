from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator, TextIO

from app.collectors.supply_demand.usda_psd_config import (
    COUNTRY_IDENTITY_MISMATCH_REASON,
    DOWNLOADABLE_OILSEEDS_COMMODITIES_BY_CODE,
    PsdCountryIdentityMismatch,
    expected_unsupported_metric_reason,
    is_supported_metric,
    normalize_usda_psd_column_key,
    normalize_usda_psd_metric,
    resolve_country_identity,
)
from app.features.supply_demand_basket_config import reviewed_tier_a_country_weights


SOURCE_CONTRACT_SCHEMA_VERSION = "usda_psd_tier_a_source_contract_v2"
SOURCE_CONTRACT_STATUSES = frozenset(
    {
        "available",
        COUNTRY_IDENTITY_MISMATCH_REASON,
        "missing_raw_row",
        "expected_unsupported_metric",
        "unexpected_mapping_gap",
        "unexpected_parser_failure",
    }
)


def audit_usda_psd_tier_a_source_contract(
    *,
    source_path: str | Path,
    product_code: str,
    marketing_years: tuple[str, ...],
) -> dict[str, Any]:
    path = Path(source_path)
    if not path.is_file():
        raise ValueError(f"USDA PSD source file not found: {path}")
    years = tuple(dict.fromkeys(str(year).strip() for year in marketing_years if str(year).strip()))
    if not years:
        raise ValueError("marketing_years must not be empty")

    weights = reviewed_tier_a_country_weights(product_code=product_code, commodity_family=product_code)
    if not weights:
        raise ValueError(f"no reviewed Tier A basket config for product: {product_code}")
    metric_countries: dict[str, list[str]] = {}
    for item in weights:
        if item.metric_code is not None:
            metric_countries.setdefault(item.metric_code, []).append(item.country_code)
    required_countries = {country for countries in metric_countries.values() for country in countries}
    commodity_codes = {
        code
        for code, commodity in DOWNLOADABLE_OILSEEDS_COMMODITIES_BY_CODE.items()
        if commodity.product_code == product_code
    }
    if not commodity_codes:
        raise ValueError(f"no downloadable USDA PSD commodity mapping for product: {product_code}")

    rows_by_identity: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    expected_unsupported_rows: list[dict[str, Any]] = []
    unexpected_metric_rows: list[dict[str, Any]] = []
    raw_rows_scanned = 0
    raw_rows_in_scope = 0
    with _open_usda_psd_csv(path) as (handle, member_name):
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("USDA PSD CSV has no header row")
        headers = [normalize_usda_psd_column_key(item) for item in reader.fieldnames]
        required_headers = {
            "commodity_code",
            "country_code",
            "country_name",
            "market_year",
            "attribute_description",
            "value",
        }
        missing_headers = sorted(required_headers - set(headers))
        if missing_headers:
            raise ValueError(f"USDA PSD CSV missing required headers: {', '.join(missing_headers)}")

        for row_number, raw_row in enumerate(reader, start=2):
            raw_rows_scanned += 1
            row = _normalize_csv_row(raw_row)
            if row.get("commodity_code") not in commodity_codes:
                continue
            country_code = str(row.get("country_code") or "").strip().upper()
            marketing_year = str(row.get("market_year") or "").strip()
            if country_code not in required_countries or marketing_year not in years:
                continue
            raw_rows_in_scope += 1
            raw_metric_name = str(row.get("attribute_description") or "").strip()
            normalized_metric = normalize_usda_psd_metric(raw_metric_name)
            row["_row_number"] = row_number
            row["_raw_metric_name"] = raw_metric_name
            row["_normalized_metric"] = normalized_metric
            if normalized_metric is None:
                unexpected_metric_rows.append(
                    _row_issue(row, status="unexpected_mapping_gap", reason="raw metric name is empty")
                )
                continue
            expected_reason = expected_unsupported_metric_reason(normalized_metric)
            if expected_reason is not None:
                expected_unsupported_rows.append(
                    _row_issue(row, status="expected_unsupported_metric", reason=expected_reason)
                )
                continue
            if not is_supported_metric(normalized_metric):
                unexpected_metric_rows.append(
                    _row_issue(
                        row,
                        status="unexpected_mapping_gap",
                        reason=f"normalized metric is not mapped by current parser: {normalized_metric}",
                    )
                )
                continue
            if normalized_metric in metric_countries:
                rows_by_identity[(normalized_metric, country_code, marketing_year)].append(row)

    matrix = [
        _contract_cell(
            metric_code=metric_code,
            country_code=country_code,
            marketing_year=marketing_year,
            raw_rows=rows_by_identity.get((metric_code, country_code, marketing_year), []),
        )
        for metric_code, countries in metric_countries.items()
        for country_code in countries
        for marketing_year in years
    ]
    metric_summary = [
        _metric_summary(metric_code=metric_code, required_countries=countries, matrix=matrix)
        for metric_code, countries in metric_countries.items()
    ]
    source_ready_candidates, blocked_units = _source_units(matrix)
    unexpected_issues_count = sum(
        1
        for row in matrix
        if row["status"]
        in {
            COUNTRY_IDENTITY_MISMATCH_REASON,
            "unexpected_mapping_gap",
            "unexpected_parser_failure",
        }
    ) + len(unexpected_metric_rows)
    return {
        "schema_version": SOURCE_CONTRACT_SCHEMA_VERSION,
        "audit_scope": "local_current_usda_psd_zip",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "product_code": product_code,
        "marketing_years": list(years),
        "source_path": str(path),
        "source_kind": "zip" if path.suffix.lower() == ".zip" else "csv",
        "source_size_bytes": path.stat().st_size,
        "raw_csv_member_name": member_name,
        "source_commodity_codes": sorted(commodity_codes),
        "tier_a_metrics": list(metric_countries),
        "tier_a_countries_by_metric": metric_countries,
        "raw_rows_scanned": raw_rows_scanned,
        "raw_rows_in_scope": raw_rows_in_scope,
        "availability_matrix": matrix,
        "metric_summary": metric_summary,
        "expected_unsupported_rows_count": len(expected_unsupported_rows),
        "expected_unsupported_rows_sample": expected_unsupported_rows[:40],
        "unexpected_metric_rows": unexpected_metric_rows,
        "unexpected_issues_count": unexpected_issues_count,
        "source_ready_backfill_candidates": source_ready_candidates,
        "blocked_source_units": blocked_units,
        "limitations": [
            "This is a local source-contract audit against a current USDA PSD ZIP.",
            "It does not prove production database inventory or execute a production backfill.",
            "Source-ready candidates are proposals only and are not claims about production gaps.",
        ],
    }


def write_usda_psd_tier_a_source_contract_report(
    audit: dict[str, Any],
    *,
    output_path: str | Path,
    output_format: str,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif output_format in {"md", "markdown"}:
        path.write_text(render_usda_psd_tier_a_source_contract_markdown(audit), encoding="utf-8")
    else:
        raise ValueError("output_format must be json or md")
    return path


def render_usda_psd_tier_a_source_contract_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# USDA PSD Tier A Source-Contract Audit",
        "",
        "**This is a local source-contract audit against a current USDA PSD ZIP.**",
        "",
        "**It does not prove production database inventory or execute a production backfill.**",
        "",
        f"- Audited at: `{audit['audited_at']}`",
        f"- Source path: `{audit['source_path']}`",
        f"- Source size: `{audit['source_size_bytes']}` bytes",
        f"- Raw CSV member: `{audit['raw_csv_member_name']}`",
        f"- Product: `{audit['product_code']}`",
        f"- Marketing years: `{', '.join(audit['marketing_years'])}`",
        f"- Raw rows scanned: `{audit['raw_rows_scanned']}`",
        f"- Unexpected issues: `{audit['unexpected_issues_count']}`",
        "",
        "## Metric Summary",
        "",
        "| metric | required countries | available country-years | missing country-years | unexpected issues |",
        "|---|---|---:|---:|---:|",
    ]
    for row in audit["metric_summary"]:
        lines.append(
            f"| {row['metric_code']} | {', '.join(row['required_countries'])} | "
            f"{row['available_country_years']} | {len(row['missing_country_years'])} | "
            f"{row['unexpected_issues_count']} |"
        )
    lines.extend(
        [
            "",
            "## Availability Matrix",
            "",
            "| metric | country | year | raw rows | normalized rows | status | issue |",
            "|---|---|---|---:|---:|---|---|",
        ]
    )
    for row in audit["availability_matrix"]:
        lines.append(
            f"| {row['metric_code']} | {row['country_code']} | {row['marketing_year']} | "
            f"{row['raw_rows_found']} | {row['normalized_rows_available']} | {row['status']} | "
            f"{row['mapping_or_parser_issue'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Source-Ready Candidate Units",
            "",
            "These units are source-ready proposals only. They are not claims that production is missing them.",
            "",
            "| country | marketing year | source-ready Tier A metrics |",
            "|---|---|---|",
        ]
    )
    if audit["source_ready_backfill_candidates"]:
        for row in audit["source_ready_backfill_candidates"]:
            lines.append(
                f"| {row['country_code']} | {row['marketing_year']} | {', '.join(row['metric_codes'])} |"
            )
    else:
        lines.append("| - | - | No fully source-ready units |")
    lines.extend(
        [
            "",
            "## Blocked Units",
            "",
            "| country | marketing year | blocked metrics | reasons |",
            "|---|---|---|---|",
        ]
    )
    if audit["blocked_source_units"]:
        for row in audit["blocked_source_units"]:
            lines.append(
                f"| {row['country_code']} | {row['marketing_year']} | "
                f"{', '.join(row['metric_codes'])} | {', '.join(row['reasons'])} |"
            )
    else:
        lines.append("| - | - | - | No blocked units |")
    lines.extend(
        [
            "",
            "## Expected Unsupported Rows",
            "",
            f"Expected unsupported aggregate/detail rows: `{audit['expected_unsupported_rows_count']}`. "
            "They are informational and are not parser failures.",
            "",
        ]
    )
    return "\n".join(lines)


def _contract_cell(
    *,
    metric_code: str,
    country_code: str,
    marketing_year: str,
    raw_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_country_names = sorted({str(row.get("country_name") or "").strip() for row in raw_rows if row.get("country_name")})
    raw_metric_names = sorted({str(row.get("_raw_metric_name") or "") for row in raw_rows})
    normalized_metric_codes = sorted({str(row.get("_normalized_metric") or "") for row in raw_rows})
    skip_reasons: list[str] = []
    issue: str | None = None
    normalized_rows_available = 0
    if not raw_rows:
        status = "missing_raw_row"
    else:
        mismatch_issues: list[str] = []
        mapping_issues: list[str] = []
        for row in raw_rows:
            try:
                resolved_country = resolve_country_identity(
                    country_code=str(row.get("country_code") or "").strip() or None,
                    country_name=str(row.get("country_name") or "").strip() or None,
                )
                if resolved_country.code != country_code:
                    mapping_issues.append(
                        f"country resolver maps {country_code} row to {resolved_country.code}"
                    )
            except PsdCountryIdentityMismatch as exc:
                mismatch_issues.append(str(exc))
            except ValueError as exc:
                mapping_issues.append(str(exc))
        if mismatch_issues:
            status = COUNTRY_IDENTITY_MISMATCH_REASON
            issue = "; ".join(sorted(set(mismatch_issues)))
        elif mapping_issues:
            status = "unexpected_mapping_gap"
            issue = "; ".join(sorted(set(mapping_issues)))
        elif not is_supported_metric(metric_code):
            status = "unexpected_mapping_gap"
            issue = f"Tier A metric is not supported by current parser: {metric_code}"
        else:
            parser_errors = [_metric_value_error(row.get("value")) for row in raw_rows]
            parser_errors = [error for error in parser_errors if error is not None]
            if parser_errors:
                status = "unexpected_parser_failure"
                issue = "; ".join(sorted(set(parser_errors)))
            else:
                status = "available"
                normalized_rows_available = len(raw_rows)
    if status not in SOURCE_CONTRACT_STATUSES:
        raise AssertionError(f"unsupported source-contract status: {status}")
    return {
        "metric_code": metric_code,
        "country_code": country_code,
        "marketing_year": marketing_year,
        "raw_rows_found": len(raw_rows),
        "normalized_rows_available": normalized_rows_available,
        "raw_country_name": raw_country_names[0] if len(raw_country_names) == 1 else raw_country_names,
        "raw_metric_names": raw_metric_names,
        "normalized_metric_codes": normalized_metric_codes,
        "status": status,
        "skip_reasons": skip_reasons,
        "mapping_or_parser_issue": issue,
    }


def _metric_summary(
    *,
    metric_code: str,
    required_countries: list[str],
    matrix: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [row for row in matrix if row["metric_code"] == metric_code]
    missing = [
        {"country_code": row["country_code"], "marketing_year": row["marketing_year"], "status": row["status"]}
        for row in rows
        if row["status"] != "available"
    ]
    unexpected = sum(
        row["status"]
        in {
            COUNTRY_IDENTITY_MISMATCH_REASON,
            "unexpected_mapping_gap",
            "unexpected_parser_failure",
        }
        for row in rows
    )
    return {
        "metric_code": metric_code,
        "required_countries": required_countries,
        "available_country_years": sum(row["status"] == "available" for row in rows),
        "missing_country_years": missing,
        "unexpected_issues_count": unexpected,
    }


def _source_units(matrix: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in matrix:
        grouped[(row["country_code"], row["marketing_year"])].append(row)
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for (country_code, marketing_year), rows in sorted(grouped.items()):
        available_metrics = sorted(row["metric_code"] for row in rows if row["status"] == "available")
        blocked_rows = [row for row in rows if row["status"] != "available"]
        if not blocked_rows:
            ready.append(
                {
                    "country_code": country_code,
                    "marketing_year": marketing_year,
                    "metric_codes": available_metrics,
                    "status": "source_ready_candidate",
                }
            )
        else:
            blocked.append(
                {
                    "country_code": country_code,
                    "marketing_year": marketing_year,
                    "metric_codes": sorted(row["metric_code"] for row in blocked_rows),
                    "reasons": sorted(
                        {
                            row["mapping_or_parser_issue"] or row["status"]
                            for row in blocked_rows
                        }
                    ),
                    "available_metric_codes": available_metrics,
                    "status": "blocked_source_candidate",
                }
            )
    return ready, blocked


def _row_issue(row: dict[str, Any], *, status: str, reason: str) -> dict[str, Any]:
    return {
        "country_code": row.get("country_code"),
        "country_name": row.get("country_name"),
        "marketing_year": row.get("market_year"),
        "raw_metric_name": row.get("_raw_metric_name"),
        "normalized_metric_code": row.get("_normalized_metric"),
        "status": status,
        "reason": reason,
        "row_number": row.get("_row_number"),
    }


def _metric_value_error(value: Any) -> str | None:
    if value in (None, ""):
        return "metric value is missing"
    try:
        Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return f"metric value is invalid: {value}"
    return None


def _normalize_csv_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    return {
        normalize_usda_psd_column_key(str(key)): value.strip() if isinstance(value, str) else value
        for key, value in raw_row.items()
        if key is not None
    }


@contextmanager
def _open_usda_psd_csv(path: Path) -> Iterator[tuple[TextIO, str]]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            csv_names = sorted(
                name for name in archive.namelist() if name.lower().endswith(".csv") and not name.endswith("/")
            )
            if not csv_names:
                raise ValueError("USDA PSD ZIP does not contain a CSV file")
            member_name = csv_names[0]
            with archive.open(member_name) as raw_handle:
                with io.TextIOWrapper(raw_handle, encoding="utf-8-sig", newline="") as text_handle:
                    yield text_handle, member_name
        return
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as text_handle:
            yield text_handle, path.name
        return
    raise ValueError("source_path must be a .csv or .zip file")
