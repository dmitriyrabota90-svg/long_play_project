from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.supply_demand.usda_psd import (
    UsdaPsdCollector,
    UsdaPsdParseError,
    assess_usda_psd_response,
    build_supply_demand_source_record_hash,
    build_usda_psd_live_probe_params,
    build_usda_psd_request,
    parse_usda_psd_rows,
    validate_marketing_year_range,
    validate_maxrecords,
)
from app.collectors.supply_demand.usda_psd_config import (
    DEFAULT_MAXRECORDS,
    DOWNLOADABLE_DATASET_ENDPOINT,
    OILSEEDS_COMMODITY_GROUP_CODE,
    OILSEEDS_DATASET_FILENAME,
    HEADERS,
    MAX_MARKETING_YEARS_PER_RUN,
    MAX_MAXRECORDS,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    SOURCE_SCHEMA_STATUS,
    SUPPORTED_COUNTRIES,
    SUPPORTED_METRICS,
    resolve_country,
)
from app.db.models import Base, CollectorRun, DailySupplyDemandFeature, DataQualityCheck, RawResponse, SupplyDemandObservation
from app.db.seed import seed_database
from app.monitoring.operational_report import build_operational_report
from app.storage.raw_store import RawStore
from scripts.run_collector import build_parser


class FakePsdClient:
    def __init__(self, payload: bytes | None = None, status_code: int = 200) -> None:
        self.payload = payload if payload is not None else psd_json()
        self.status_code = status_code
        self.calls: list[tuple[str, dict[str, str], dict[str, str], float]] = []

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        self.calls.append((url, params, headers, timeout))
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            self.status_code,
            content=self.payload,
            headers={"content-type": "application/json; charset=utf-8"},
            request=request,
        )


def psd_json(
    *,
    production_value: str = "1000.5",
    include_food_use: bool = False,
    include_expected_unsupported: bool = False,
    include_malformed: bool = False,
    include_unmapped: bool = False,
) -> bytes:
    rows: list[dict[str, Any]] = [
        {
            "id": "soybean-oil-wld-2023-production",
            "commodity_family": "soybean",
            "product_code": "soybean_oil",
            "metric_name": "production_volume",
            "country_code": "WLD",
            "country_name": "World",
            "marketing_year": "2023",
            "marketing_year_start": "2023-01-01",
            "marketing_year_end": "2023-12-31",
            "report_month": 5,
            "report_year": 2024,
            "report_published_at": "2024-05-10T12:00:00+00:00",
            "frequency": "monthly_report",
            "estimate_type": "forecast",
            "metric_value": production_value,
            "metric_unit": "1000 metric tons",
            "value_usd": "250000.25",
            "is_forecast": True,
        },
        {
            "id": "soybean-oil-wld-2023-exports",
            "commodity_family": "soybean",
            "product_code": "soybean_oil",
            "metric_name": "exports_volume",
            "country_code": "WLD",
            "country_name": "World",
            "marketing_year": "2023",
            "report_month": 5,
            "report_year": 2024,
            "published_at": "2024-05-10T12:00:00+00:00",
            "frequency": "monthly_report",
            "estimate_type": "forecast",
            "metric_value": "210.75",
            "metric_unit": "1000 metric tons",
            "is_forecast": True,
        },
    ]
    if include_food_use:
        rows.append(
            {
                "id": "soybean-oil-wld-2023-food-use",
                "commodity_family": "soybean",
                "product_code": "soybean_oil",
                "metric_name": "Food Use Dom. Cons.",
                "country_code": "WLD",
                "country_name": "World",
                "marketing_year": "2023",
                "report_month": 5,
                "report_year": 2024,
                "estimate_type": "forecast",
                "metric_value": "55.5",
                "metric_unit": "1000 metric tons",
            }
        )
    if include_expected_unsupported:
        rows.append(
            {
                "id": "soybean-oil-wld-2023-total-supply",
                "commodity_family": "soybean",
                "product_code": "soybean_oil",
                "metric_name": "total_supply",
                "country_code": "WLD",
                "country_name": "World",
                "marketing_year": "2023",
                "report_month": 5,
                "report_year": 2024,
                "estimate_type": "forecast",
                "metric_value": "1200",
                "metric_unit": "1000 metric tons",
            }
        )
    if include_malformed:
        rows.append(
            {
                "id": "malformed",
                "metric_name": "production_volume",
                "country_code": "WLD",
                "marketing_year": "2023",
                "metric_value": "not-a-number",
            }
        )
    if include_unmapped:
        rows.append(
            {
                "id": "sunflower-oil-wld-2023-production",
                "commodity_family": "sunflower",
                "product_code": "sunflower_oil",
                "metric_name": "production_volume",
                "country_code": "WLD",
                "marketing_year": "2023",
                "report_month": 5,
                "report_year": 2024,
                "estimate_type": "forecast",
                "metric_value": "1",
                "metric_unit": "1000 metric tons",
            }
        )
    return json.dumps({"data": rows}, separators=(",", ":")).encode("utf-8")


def psd_oilseeds_csv() -> str:
    return Path("tests/fixtures/usda_psd/oilseeds_sample.csv").read_text(encoding="utf-8")


def psd_oilseeds_zip(csv_text: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("psd_oilseeds.csv", csv_text if csv_text is not None else psd_oilseeds_csv())
    return buffer.getvalue()


def psd_downloadable_metadata_json() -> bytes:
    return json.dumps(
        [
            {
                "commodityName": "Meal, Soybean",
                "commodityCode": "0813100",
                "beginOfSeries": 1964,
                "splitYear": 0,
            }
        ],
        separators=(",", ":"),
    ).encode("utf-8")


def test_usda_psd_config_contains_controlled_defaults() -> None:
    assert SOURCE_CODE == "usda_psd"
    assert SOURCE_SCHEMA_STATUS == "needs_verification"
    assert REQUEST_TIMEOUT == 20.0
    assert DEFAULT_MAXRECORDS == 100
    assert MAX_MAXRECORDS == 500
    assert MAX_MARKETING_YEARS_PER_RUN == 3
    assert DOWNLOADABLE_DATASET_ENDPOINT == "https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip"
    assert OILSEEDS_COMMODITY_GROUP_CODE == "oil"
    assert OILSEEDS_DATASET_FILENAME == "psd_oilseeds_csv.zip"
    assert "psdonline/app/index.html" not in DOWNLOADABLE_DATASET_ENDPOINT.lower()
    assert "getdatasetcontents" not in DOWNLOADABLE_DATASET_ENDPOINT.lower()
    assert DOWNLOADABLE_DATASET_ENDPOINT.endswith(OILSEEDS_DATASET_FILENAME)
    assert "commodity-dataset-builder" in HEADERS["User-Agent"]
    assert {"WLD", "US", "BR", "AR", "CA", "CH", "EU", "IN", "MX", "RS", "BL", "PA"} == {
        country.code for country in SUPPORTED_COUNTRIES
    }
    assert {
        "production_volume",
        "domestic_consumption",
        "food_use",
        "feed_use",
        "crush_volume",
        "exports_volume",
        "imports_volume",
        "beginning_stocks",
        "ending_stocks",
        "stock_to_use_ratio",
        "planted_area",
        "harvested_area",
        "yield",
    } == set(SUPPORTED_METRICS)


def test_usda_psd_request_validation_rejects_unbounded_or_unknown_inputs() -> None:
    build_usda_psd_request(
        commodity_family="soybean_oil",
        from_marketing_year=2022,
        to_marketing_year=2024,
        country="US",
        maxrecords=100,
    )
    assert (
        build_usda_psd_request(
            commodity_family="soybean_oil",
            from_marketing_year=2024,
            to_marketing_year=2024,
            country="United States",
            maxrecords=100,
        ).country.code
        == "US"
    )
    assert (
        build_usda_psd_request(
            commodity_family="soybean_oil",
            from_marketing_year=2024,
            to_marketing_year=2024,
            country="Brazil",
            maxrecords=100,
        ).country.code
        == "BR"
    )

    with pytest.raises(ValueError, match="unsupported USDA PSD commodity family"):
        build_usda_psd_request(
            commodity_family="sunflower_oil",
            from_marketing_year=2024,
            to_marketing_year=2024,
            country="WLD",
            maxrecords=100,
        )
    with pytest.raises(ValueError, match="from_marketing_year"):
        validate_marketing_year_range(from_marketing_year=2025, to_marketing_year=2024)
    with pytest.raises(ValueError, match="max allowed years"):
        validate_marketing_year_range(from_marketing_year=2021, to_marketing_year=2024)
    with pytest.raises(ValueError, match="maxrecords"):
        validate_maxrecords(0)
    with pytest.raises(ValueError, match="maxrecords"):
        validate_maxrecords(501)
    with pytest.raises(ValueError, match="unsupported USDA PSD country"):
        build_usda_psd_request(
            commodity_family="soybean_oil",
            from_marketing_year=2024,
            to_marketing_year=2024,
            country="RUS",
            maxrecords=100,
        )


@pytest.mark.parametrize(
    ("raw_country_code", "raw_country_name"),
    (
        ("IN", "India"),
        ("MX", "Mexico"),
        ("RS", "Russia"),
        ("BL", "Bolivia"),
        ("PA", "Paraguay"),
    ),
)
def test_usda_psd_parser_normalizes_verified_tier_a_country_mappings(
    raw_country_code: str,
    raw_country_name: str,
) -> None:
    csv_text = (
        "Commodity_Code,Commodity_Description,Country_Code,Country_Name,Market_Year,"
        "Calendar_Year,Month,Attribute_ID,Attribute_Description,Unit_ID,Unit_Description,Value\n"
        f'4232000,"Oil, Soybean",{raw_country_code},{raw_country_name},2023,2024,06,'
        '088,Exports,08,"(1000 MT)",10.0000\n'
    )
    rows, malformed, rows_array_present, raw_rows_count = parse_usda_psd_rows(
        psd_oilseeds_zip(csv_text),
        request=_request(country=raw_country_code),
        fetched_at=datetime(2026, 6, 30, 12, tzinfo=timezone.utc),
    )

    assert rows_array_present is True
    assert raw_rows_count == 1
    assert malformed == []
    assert len(rows) == 1
    assert rows[0].country_code == raw_country_code
    assert rows[0].country_name == raw_country_name


def test_usda_psd_country_mapping_keeps_existing_codes_and_rejects_unverified_aliases() -> None:
    assert {code: resolve_country(code).name for code in ("US", "BR", "AR", "CH")} == {
        "US": "United States",
        "BR": "Brazil",
        "AR": "Argentina",
        "CH": "China",
    }
    with pytest.raises(ValueError, match="unsupported USDA PSD country"):
        resolve_country("RUS")


def test_usda_psd_parser_normalizes_fixture_rows() -> None:
    request = _request()
    rows, malformed, rows_array_present, raw_rows_count = parse_usda_psd_rows(
        psd_json(),
        request=request,
        fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
    )

    assert rows_array_present is True
    assert raw_rows_count == 2
    assert malformed == []
    assert rows[0].commodity_family == "soybean"
    assert rows[0].product_code == "soybean_oil"
    assert rows[0].metric_name == "production_volume"
    assert rows[0].country_code == "WLD"
    assert rows[0].marketing_year == "2023"
    assert rows[0].marketing_year_start == date(2023, 1, 1)
    assert rows[0].metric_value == Decimal("1000.5")
    assert rows[0].value_usd == Decimal("250000.25")
    assert rows[1].metric_name == "exports_volume"
    assert build_supply_demand_source_record_hash(source_code=SOURCE_CODE, row=rows[0], supply_demand_commodity_id=1)


def test_usda_psd_parser_extracts_downloadable_oilseeds_zip_and_filters_scope() -> None:
    request = _request(country="US")
    rows, malformed, rows_array_present, raw_rows_count = parse_usda_psd_rows(
        psd_oilseeds_zip(),
        request=request,
        fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
    )

    assert rows_array_present is True
    assert raw_rows_count == 9
    assert malformed == []
    assert [row.metric_name for row in rows] == ["production_volume", "exports_volume"]
    assert {row.product_code for row in rows} == {"soybean_oil"}
    assert {row.commodity_family for row in rows} == {"soybean"}
    assert {row.country_code for row in rows} == {"US"}
    assert {row.marketing_year for row in rows} == {"2023"}
    assert rows[0].source_record_id == "4232000|US|2023|production_volume"
    assert rows[0].metric_value == Decimal("1000.5")
    assert rows[0].metric_unit == "1000 Metric Tons"


def test_usda_psd_parser_extracts_brazil_country_level_rows() -> None:
    request = _request(country="BR")
    rows, malformed, rows_array_present, raw_rows_count = parse_usda_psd_rows(
        psd_oilseeds_zip(),
        request=request,
        fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
    )

    assert rows_array_present is True
    assert raw_rows_count == 9
    assert malformed == []
    assert [row.metric_name for row in rows] == ["production_volume", "exports_volume"]
    assert {row.country_code for row in rows} == {"BR"}
    assert rows[0].source_record_id == "4232000|BR|2023|production_volume"
    assert rows[0].metric_value == Decimal("1200.0")


def test_usda_psd_parser_does_not_fabricate_world_rows_from_country_level_zip() -> None:
    request = _request(country="WLD")
    rows, malformed, expected_skips, checks = assess_usda_psd_response(
        payload=psd_oilseeds_zip(),
        content_type="application/zip",
        status_code=200,
        request=request,
        fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
    )
    normalized_check = next(check for check in checks if check.check_name == "supply_demand_normalized_rows_found")

    assert rows == []
    assert malformed == []
    assert expected_skips == []
    assert normalized_check.status == "fail"
    assert normalized_check.severity == "warning"
    assert normalized_check.details["raw_rows_count"] == 9
    assert normalized_check.details["parsed_rows_count"] == 0
    assert (
        normalized_check.details["message"]
        == "USDA PSD oilseeds ZIP has no WLD/World rows; use concrete country codes or explicit aggregation mode"
    )


def test_usda_psd_parser_rejects_downloadable_metadata_json() -> None:
    request = _request()
    rows, malformed, expected_skips, checks = assess_usda_psd_response(
        payload=psd_downloadable_metadata_json(),
        content_type="application/json",
        status_code=200,
        request=request,
        fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
    )
    normalized_check = next(check for check in checks if check.check_name == "supply_demand_normalized_rows_found")

    assert rows == []
    assert malformed == []
    assert expected_skips == []
    assert normalized_check.status == "fail"
    assert normalized_check.severity == "error"
    assert normalized_check.details["error"] == "USDA PSD endpoint returned downloadable dataset metadata, not data rows"
    with pytest.raises(UsdaPsdParseError, match="downloadable dataset metadata"):
        parse_usda_psd_rows(
            psd_downloadable_metadata_json(),
            request=request,
            fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        )


def test_usda_psd_parser_rejects_html_shell() -> None:
    request = _request()
    payload = b"<!DOCTYPE html><html><head><title>PSD Online</title></head><body></body></html>"
    rows, malformed, expected_skips, checks = assess_usda_psd_response(
        payload=payload,
        content_type="text/html",
        status_code=200,
        request=request,
        fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
    )
    normalized_check = next(check for check in checks if check.check_name == "supply_demand_normalized_rows_found")

    assert rows == []
    assert malformed == []
    assert expected_skips == []
    assert normalized_check.status == "fail"
    assert normalized_check.severity == "error"
    assert normalized_check.details["error"] == "USDA PSD endpoint returned HTML shell, not data rows"
    with pytest.raises(UsdaPsdParseError, match="HTML shell"):
        parse_usda_psd_rows(payload, request=request, fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc))


def test_usda_psd_parser_reports_empty_and_unknown_formats() -> None:
    request = _request()
    rows, malformed, expected_skips, checks = assess_usda_psd_response(
        payload=b"",
        content_type="application/json",
        status_code=200,
        request=request,
        fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
    )

    assert rows == []
    assert malformed == []
    assert expected_skips == []
    assert {check.check_name: check.status for check in checks}["supply_demand_raw_response_non_empty"] == "fail"
    assert {check.check_name: check.status for check in checks}["supply_demand_normalized_rows_found"] == "fail"
    with pytest.raises(UsdaPsdParseError):
        parse_usda_psd_rows(b'{"not_data":[]}', request=request, fetched_at=datetime.now(timezone.utc))


def test_usda_psd_parser_separates_expected_skips_from_malformed_rows() -> None:
    request = _request()
    rows, malformed, expected_skips, checks = assess_usda_psd_response(
        payload=psd_json(include_food_use=True, include_expected_unsupported=True, include_malformed=True),
        content_type="application/json",
        status_code=200,
        request=request,
        fetched_at=datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
    )
    normalized_check = next(check for check in checks if check.check_name == "supply_demand_normalized_rows_found")
    expected_skip_check = next(check for check in checks if check.check_name == "supply_demand_expected_rows_skipped")

    assert [row.metric_name for row in rows] == ["production_volume", "exports_volume", "food_use"]
    assert len(malformed) == 1
    assert malformed[0]["error"] == "metric value is missing or invalid"
    assert len(expected_skips) == 1
    assert expected_skips[0]["category"] == "expected_unsupported_metric"
    assert expected_skips[0]["metric_name"] == "total_supply"
    assert normalized_check.details["parsed_rows_count"] == 3
    assert normalized_check.details["malformed_rows_count"] == 1
    assert normalized_check.details["expected_skipped_rows_count"] == 1
    assert expected_skip_check.status == "skip"


def test_usda_psd_collector_inserts_observations_with_raw_and_quality_checks(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixture = _write_fixture(tmp_path, psd_json())
    try:
        result = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        ).run(
            session,
            commodity_family="soybean_oil",
            from_marketing_year=2023,
            to_marketing_year=2023,
            country="WLD",
            fixture_file=fixture,
        )
        rows = session.scalars(select(SupplyDemandObservation).order_by(SupplyDemandObservation.source_record_id)).all()
        raw_response = session.scalar(select(RawResponse))
        run = session.scalar(select(CollectorRun).where(CollectorRun.collector_name == "usda_psd"))
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())
        daily_rows = session.scalar(select(func.count()).select_from(DailySupplyDemandFeature))
    finally:
        cleanup()

    assert result.status == "success"
    assert result.records_found == 2
    assert result.records_written == 2
    assert result.skipped_existing == 0
    assert result.conflicts_count == 0
    assert result.skipped_expected == 0
    assert result.fixture_file == str(fixture)
    assert result.live_probe is False
    assert len(rows) == 2
    assert raw_response is not None
    assert run is not None
    assert all(row.raw_response_id == raw_response.id for row in rows)
    assert all(row.collector_run_id == run.id for row in rows)
    assert rows[0].source_payload_hash == raw_response.sha256
    assert rows[0].metadata_json["source_schema_status"] == "needs_verification"
    assert raw_response.storage_path.startswith(str(tmp_path / "raw" / "usda_psd"))
    assert daily_rows == 0
    assert "supply_demand_raw_response_persisted" in check_names
    assert "supply_demand_source_record_hash_present" in check_names
    assert "supply_demand_live_probe_skipped_fixture_mode" in check_names


def test_usda_psd_collector_writes_supported_rows_and_expected_skips_do_not_fail_run(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixture = _write_fixture(tmp_path, psd_json(include_food_use=True, include_expected_unsupported=True))
    try:
        result = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        ).run(
            session,
            commodity_family="soybean_oil",
            from_marketing_year=2023,
            to_marketing_year=2023,
            country="WLD",
            fixture_file=fixture,
        )
        rows = session.scalars(select(SupplyDemandObservation).order_by(SupplyDemandObservation.source_record_id)).all()
        metric_names = {row.supply_demand_commodity.metric_name for row in rows}
        expected_skip_check = session.scalar(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "supply_demand_expected_rows_skipped")
        )
    finally:
        cleanup()

    assert result.status == "success"
    assert result.records_found == 3
    assert result.records_written == 3
    assert result.skipped_expected == 1
    assert result.skipped_malformed == 0
    assert result.skipped_unmapped == 0
    assert metric_names == {"production_volume", "exports_volume", "food_use"}
    assert expected_skip_check is not None
    assert expected_skip_check.status == "skip"
    assert expected_skip_check.details_json["expected_skip_reason_counts"] == {"aggregate_total_supply_not_feature_metric": 1}


def test_usda_psd_collector_keeps_real_malformed_rows_problematic(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixture = _write_fixture(tmp_path, psd_json(include_malformed=True))
    try:
        result = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        ).run(
            session,
            commodity_family="soybean_oil",
            from_marketing_year=2023,
            to_marketing_year=2023,
            country="WLD",
            fixture_file=fixture,
        )
        warning = session.scalar(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "supply_demand_malformed_row_skipped")
        )
    finally:
        cleanup()

    assert result.status == "partial_success"
    assert result.records_written == 2
    assert result.skipped_malformed == 1
    assert result.skipped_expected == 0
    assert warning is not None
    assert warning.status == "fail"
    assert warning.details_json["category"] == "malformed_empty_or_missing_required"


def test_usda_psd_collector_inserts_from_zip_fixture_with_raw_zip_extension(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixture = _write_fixture(tmp_path, psd_oilseeds_zip(), name="psd_oilseeds_csv.zip")
    try:
        result = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        ).run(
            session,
            commodity_family="soybean_oil",
            from_marketing_year=2023,
            to_marketing_year=2023,
            country="US",
            fixture_file=fixture,
        )
        rows = session.scalars(select(SupplyDemandObservation).order_by(SupplyDemandObservation.source_record_id)).all()
        raw_response = session.scalar(select(RawResponse))
        product_codes = {row.supply_demand_commodity.product_code for row in rows}
    finally:
        cleanup()

    assert result.status == "success"
    assert result.records_found == 2
    assert result.records_written == 2
    assert len(rows) == 2
    assert raw_response is not None
    assert raw_response.content_type == "application/zip"
    assert raw_response.storage_path.endswith(".zip")
    assert product_codes == {"soybean_oil"}


def test_usda_psd_collector_writes_concrete_brazil_rows_from_zip_fixture(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixture = _write_fixture(tmp_path, psd_oilseeds_zip(), name="psd_oilseeds_csv.zip")
    try:
        result = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        ).run(
            session,
            commodity_family="soybean_oil",
            from_marketing_year=2023,
            to_marketing_year=2023,
            country="BR",
            fixture_file=fixture,
        )
        rows = session.scalars(select(SupplyDemandObservation).order_by(SupplyDemandObservation.source_record_id)).all()
        metric_names = [row.supply_demand_commodity.metric_name for row in rows]
    finally:
        cleanup()

    assert result.status == "success"
    assert result.records_found == 2
    assert result.records_written == 2
    assert {row.country_code for row in rows} == {"BR"}
    assert metric_names == ["exports_volume", "production_volume"]


def test_usda_psd_duplicate_retry_skips_existing_observations(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixture = _write_fixture(tmp_path, psd_json())
    try:
        collector = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        )
        first = collector.run(session, commodity_family="soybean_oil", from_marketing_year=2023, to_marketing_year=2023, country="WLD", fixture_file=fixture)
        second = collector.run(session, commodity_family="soybean_oil", from_marketing_year=2023, to_marketing_year=2023, country="WLD", fixture_file=fixture)
        rows_count = session.scalar(select(func.count()).select_from(SupplyDemandObservation))
    finally:
        cleanup()

    assert first.records_written == 2
    assert second.records_written == 0
    assert second.skipped_existing == 2
    assert second.conflicts_count == 0
    assert rows_count == 2


def test_usda_psd_changed_hash_conflict_warns_without_overwrite(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    first_fixture = _write_fixture(tmp_path, psd_json(production_value="1000.5"), name="first.json")
    second_fixture = _write_fixture(tmp_path, psd_json(production_value="1002.5"), name="second.json")
    try:
        collector = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        )
        collector.run(session, commodity_family="soybean_oil", from_marketing_year=2023, to_marketing_year=2023, country="WLD", fixture_file=first_fixture)
        second = collector.run(session, commodity_family="soybean_oil", from_marketing_year=2023, to_marketing_year=2023, country="WLD", fixture_file=second_fixture)
        production_row = session.scalar(
            select(SupplyDemandObservation).where(SupplyDemandObservation.source_record_id == "soybean-oil-wld-2023-production")
        )
        warning = session.scalar(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "supply_demand_existing_observation_hash_changed")
        )
    finally:
        cleanup()

    assert second.records_written == 0
    assert second.skipped_existing == 1
    assert second.conflicts_count == 1
    assert second.status == "partial_success"
    assert production_row.metric_value == Decimal("1000.50000000")
    assert warning is not None
    assert warning.status == "fail"
    assert warning.severity == "warning"
    assert "metric_value" in warning.details_json["changed_fields"]
    assert warning.details_json["policy_decision"] == "rejected_hash_conflict_no_overwrite"


def test_usda_psd_unmapped_rows_are_skipped_with_warning(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixture = _write_fixture(tmp_path, psd_json(include_unmapped=True))
    try:
        result = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        ).run(session, commodity_family="soybean_oil", from_marketing_year=2023, to_marketing_year=2023, country="WLD", fixture_file=fixture)
        rows_count = session.scalar(select(func.count()).select_from(SupplyDemandObservation))
        warning = session.scalar(select(DataQualityCheck).where(DataQualityCheck.check_name == "supply_demand_mapping_found", DataQualityCheck.status == "fail"))
    finally:
        cleanup()

    assert result.status == "partial_success"
    assert result.records_found == 3
    assert result.records_written == 2
    assert result.skipped_unmapped == 1
    assert rows_count == 2
    assert warning is not None
    assert warning.severity == "warning"
    assert warning.details_json["product_code"] == "sunflower_oil"


def test_usda_psd_missing_source_returns_error_without_raw_write(tmp_path: Path) -> None:
    session, cleanup = build_empty_session()
    fixture = _write_fixture(tmp_path, psd_json())
    try:
        result = UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        ).run(session, commodity_family="soybean_oil", from_marketing_year=2023, to_marketing_year=2023, country="WLD", fixture_file=fixture)
        raw_count = session.scalar(select(func.count()).select_from(RawResponse))
        check = session.scalar(select(DataQualityCheck).where(DataQualityCheck.check_name == "supply_demand_source_mapping_found"))
    finally:
        cleanup()

    assert result.status == "error"
    assert result.errors_count == 1
    assert result.records_written == 0
    assert raw_count == 0
    assert check is not None
    assert check.status == "fail"
    assert check.severity == "error"


def test_usda_psd_mocked_live_probe_uses_bounded_params_and_headers(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    client = FakePsdClient(payload=psd_oilseeds_zip())
    try:
        collector = UsdaPsdCollector(
            http_client=client,
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        )
        result = collector.run(
            session,
            commodity_family="soybean_oil",
            from_marketing_year=2023,
            to_marketing_year=2023,
            country="US",
            maxrecords=100,
            live_probe=True,
        )
    finally:
        cleanup()

    assert result.status == "success"
    assert result.records_found == 2
    assert result.records_written == 2
    assert client.calls[0][0] == DOWNLOADABLE_DATASET_ENDPOINT
    assert client.calls[0][1] == build_usda_psd_live_probe_params(_request(country="US"))
    assert client.calls[0][2] == HEADERS
    assert client.calls[0][3] == REQUEST_TIMEOUT
    assert client.calls[0][1] == {}


def test_usda_psd_cli_argument_parsing_supports_manual_fixture_mode() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "usda_psd",
            "--commodity-family",
            "soybean_oil",
            "--from-marketing-year",
            "2023",
            "--to-marketing-year",
            "2023",
            "--country",
            "US",
            "--fixture-file",
            "tests/fixtures/usda_psd/sample.json",
            "--maxrecords",
            "100",
            "--dry-run",
        ]
    )

    assert args.collector_name == "usda_psd"
    assert args.commodity_family == "soybean_oil"
    assert args.from_marketing_year == 2023
    assert args.to_marketing_year == 2023
    assert args.country == "US"
    assert args.fixture_file == "tests/fixtures/usda_psd/sample.json"
    assert args.maxrecords == 100
    assert args.dry_run is True


def test_usda_psd_cli_rejects_missing_required_args_without_db_access(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_collector.py", "usda_psd", "--commodity-family", "soybean_oil", "--fixture-file", "fixture.json"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert result.returncode != 0
    assert "--from-marketing-year" in result.stderr
    assert "--country" in result.stderr


def test_usda_psd_cli_requires_fixture_or_explicit_live_probe_without_db_access(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_collector.py",
            "usda_psd",
            "--commodity-family",
            "soybean_oil",
            "--from-marketing-year",
            "2023",
            "--to-marketing-year",
            "2023",
            "--country",
            "US",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert result.returncode != 0
    assert "provide exactly one of --fixture-file or --live-probe" in result.stderr


def test_usda_psd_operational_report_includes_supply_demand_counts(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixture = _write_fixture(tmp_path, psd_json())
    try:
        UsdaPsdCollector(
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 14, 12, tzinfo=timezone.utc),
        ).run(session, commodity_family="soybean_oil", from_marketing_year=2023, to_marketing_year=2023, country="WLD", fixture_file=fixture)
        report = build_operational_report(session=session)
    finally:
        cleanup()

    assert report["supply_demand_observations"]["count"] == 2
    assert report["supply_demand_observations"]["commodities_count"] == 2
    assert report["supply_demand_observations"]["countries_count"] == 1
    assert report["supply_demand_observations"]["last_fetched_at"] == "2026-06-14T12:00:00+00:00"
    assert report["supply_demand_observations"]["last_successful_run"]["collector_name"] == "usda_psd"
    assert report["daily_supply_demand_features"]["count"] == 0


def test_source_record_hash_is_not_part_of_supply_demand_observation_identity() -> None:
    table = Base.metadata.tables["supply_demand_observations"]
    unique = next(constraint for constraint in table.constraints if constraint.name == "uq_supply_demand_observations_identity")

    assert "source_record_hash" not in {column.name for column in unique.columns}


def test_usda_psd_is_not_registered_in_scheduler() -> None:
    scheduler_text = "\n".join(path.read_text(encoding="utf-8") for path in Path("app/scheduler").rglob("*.py"))

    assert "usda_psd" not in scheduler_text


def _request(*, country: str = "WLD"):
    return build_usda_psd_request(
        commodity_family="soybean_oil",
        from_marketing_year=2023,
        to_marketing_year=2023,
        country=country,
        maxrecords=100,
    )


def _write_fixture(tmp_path: Path, payload: bytes, *, name: str = "psd.json") -> Path:
    fixture = tmp_path / name
    fixture.write_bytes(payload)
    return fixture


def build_seeded_session():
    session, cleanup = build_empty_session()
    seed_database(session)
    return session, cleanup


def build_empty_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()

    def cleanup() -> None:
        session.close()
        engine.dispose()

    return session, cleanup
