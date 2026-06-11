from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.news.gdelt_config import (
    DEFAULT_MAXRECORDS,
    ENDPOINT,
    GDELT_QUERY_PRESETS_BY_KEY,
    HEADERS,
    MAX_DATE_RANGE_DAYS,
    MAX_MAXRECORDS,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    gdelt_doc_params,
)
from app.collectors.news.gdelt_news import (
    GdeltNewsCollector,
    GdeltNewsParseError,
    assess_gdelt_response,
    build_article_hash,
    build_gdelt_request,
    parse_gdelt_articles,
    validate_gdelt_date_range,
    validate_maxrecords,
)
from app.db.models import Base, CollectorRun, DataQualityCheck, NewsArticle, RawResponse
from app.db.seed import seed_database
from app.monitoring.operational_report import build_operational_report
from app.storage.raw_store import RawStore
from scripts.run_collector import build_parser


class FakeGdeltClient:
    def __init__(self, payload: bytes | None = None, status_code: int = 200) -> None:
        self.payload = payload if payload is not None else gdelt_json()
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


def gdelt_json(*, title: str = "Soybean oil exports rise", include_malformed: bool = False) -> bytes:
    articles: list[dict[str, Any]] = [
        {
            "url": "https://example.com/markets/soybean-oil?utm_source=gdelt",
            "title": title,
            "seendate": "20260601T120000Z",
            "domain": "example.com",
            "sourceCommonName": "Example Markets",
            "language": "English",
            "sourceCountry": "United States",
            "summary": "Soybean oil export demand improved.",
        },
        {
            "url": "https://example.org/feed/soybean-meal",
            "title": "Soybean meal demand steady",
            "seendate": "20260602T081500Z",
            "domain": "example.org",
        },
    ]
    if include_malformed:
        articles.append({"title": "Missing URL", "seendate": "20260602T090000Z"})
    return json.dumps({"articles": articles}, separators=(",", ":")).encode("utf-8")


def test_gdelt_config_contains_expected_defaults_and_presets() -> None:
    assert SOURCE_CODE == "gdelt_2_1"
    assert ENDPOINT == "https://api.gdeltproject.org/api/v2/doc/doc"
    assert REQUEST_TIMEOUT > 0
    assert MAX_DATE_RANGE_DAYS == 7
    assert MAX_MAXRECORDS == 100
    assert {"soybean", "rapeseed_canola", "vegetable_oils", "grain_oilseed_policy"} <= set(GDELT_QUERY_PRESETS_BY_KEY)
    assert GDELT_QUERY_PRESETS_BY_KEY["soybean"].commodity_family == "soybean"
    assert "soybean_oil" in GDELT_QUERY_PRESETS_BY_KEY["soybean"].affected_products
    assert "commodity-dataset-builder" in HEADERS["User-Agent"]


def test_gdelt_doc_params_include_query_dates_and_limit() -> None:
    params = gdelt_doc_params(
        query="soybean oil",
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 3),
        maxrecords=25,
    )

    assert params["query"] == "soybean oil"
    assert params["mode"] == "ArtList"
    assert params["format"] == "json"
    assert params["maxrecords"] == "25"
    assert params["startdatetime"] == "20260601000000"
    assert params["enddatetime"] == "20260603235959"


def test_parser_handles_fixture_json_and_missing_optional_fields() -> None:
    rows, malformed, articles_array_present, raw_rows_count = parse_gdelt_articles(
        gdelt_json(),
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
    )

    assert articles_array_present is True
    assert raw_rows_count == 2
    assert malformed == []
    assert rows[0].title == "Soybean oil exports rise"
    assert rows[0].published_at == datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
    assert rows[0].canonical_url == "https://example.com/markets/soybean-oil"
    assert rows[0].source_name == "Example Markets"
    assert rows[1].source_name == "example.org"
    assert rows[1].language == "unknown"
    assert build_article_hash(rows[0]) == build_article_hash(rows[0])


def test_parser_reports_empty_and_unknown_formats() -> None:
    request = build_gdelt_request(
        query_key="soybean",
        query=None,
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 2),
        maxrecords=25,
    )

    rows, malformed, checks = assess_gdelt_response(
        payload=b"",
        content_type="application/json",
        status_code=200,
        request=request,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
    )

    assert rows == []
    assert malformed == []
    assert {check.check_name: check.status for check in checks}["news_articles_array_present"] == "fail"
    with pytest.raises(GdeltNewsParseError):
        parse_gdelt_articles(b'{"not_articles":[]}', fetched_at=datetime.now(timezone.utc))


def test_request_validation() -> None:
    validate_gdelt_date_range(from_date=date(2026, 6, 1), to_date=date(2026, 6, 7))
    validate_maxrecords(100)
    with pytest.raises(ValueError, match="either query_key or query"):
        build_gdelt_request(query_key=None, query=None, from_date=date(2026, 6, 1), to_date=date(2026, 6, 2), maxrecords=25)
    with pytest.raises(ValueError, match="cannot be combined"):
        build_gdelt_request(query_key="soybean", query="soybean", from_date=date(2026, 6, 1), to_date=date(2026, 6, 2), maxrecords=25)
    with pytest.raises(ValueError, match="from_date"):
        validate_gdelt_date_range(from_date=date(2026, 6, 2), to_date=date(2026, 6, 1))
    with pytest.raises(ValueError, match="max allowed days"):
        validate_gdelt_date_range(from_date=date(2026, 6, 1), to_date=date(2026, 6, 8))
    with pytest.raises(ValueError, match="maxrecords"):
        validate_maxrecords(101)


def test_collector_inserts_news_articles_with_raw_and_quality_checks(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    client = FakeGdeltClient()
    try:
        result = GdeltNewsCollector(
            http_client=client,
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(
            session,
            query_key="soybean",
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 3),
            maxrecords=25,
        )
        rows = session.scalars(select(NewsArticle).order_by(NewsArticle.published_at)).all()
        raw_response = session.scalar(select(RawResponse))
        run = session.scalar(select(CollectorRun))
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())
    finally:
        cleanup()

    assert result.status == "success"
    assert result.query_key == "soybean"
    assert result.records_found == 2
    assert result.records_written == 2
    assert result.skipped_existing == 0
    assert result.conflicts_count == 0
    assert len(rows) == 2
    assert raw_response is not None
    assert run is not None
    assert all(row.raw_response_id == raw_response.id for row in rows)
    assert all(row.collector_run_id == run.id for row in rows)
    assert rows[0].metadata_json["query_key"] == "soybean"
    assert rows[0].metadata_json["body_text_policy"] == "not_collected_in_phase_6_4d"
    assert rows[0].source_payload_hash == raw_response.sha256
    assert client.calls[0][0] == ENDPOINT
    assert client.calls[0][1]["maxrecords"] == "25"
    assert client.calls[0][2] == HEADERS
    assert client.calls[0][3] == REQUEST_TIMEOUT
    assert "news_raw_response_non_empty" in check_names
    assert "news_article_url_present" in check_names
    assert "news_raw_linkage_present" in check_names


def test_duplicate_retry_skips_existing_news_articles(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        collector = GdeltNewsCollector(
            http_client=FakeGdeltClient(),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        )
        first = collector.run(
            session,
            query_key="soybean",
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 3),
            maxrecords=25,
        )
        second = collector.run(
            session,
            query_key="soybean",
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 3),
            maxrecords=25,
        )
        rows_count = session.scalar(select(func.count()).select_from(NewsArticle))
    finally:
        cleanup()

    assert first.records_written == 2
    assert second.records_written == 0
    assert second.skipped_existing == 2
    assert second.conflicts_count == 0
    assert rows_count == 2


def test_changed_article_record_creates_conflict_warning_without_overwrite(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        GdeltNewsCollector(
            http_client=FakeGdeltClient(gdelt_json(title="Soybean oil exports rise")),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(session, query_key="soybean", from_date=date(2026, 6, 1), to_date=date(2026, 6, 3), maxrecords=25)
        second = GdeltNewsCollector(
            http_client=FakeGdeltClient(gdelt_json(title="Soybean oil exports fall")),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, 5, tzinfo=timezone.utc),
        ).run(session, query_key="soybean", from_date=date(2026, 6, 1), to_date=date(2026, 6, 3), maxrecords=25)
        row = session.scalar(select(NewsArticle).where(NewsArticle.url.like("%soybean-oil%")))
        warning = session.scalar(select(DataQualityCheck).where(DataQualityCheck.check_name == "news_existing_article_hash_changed"))
    finally:
        cleanup()

    assert second.status == "partial_success"
    assert second.records_written == 0
    assert second.skipped_existing == 1
    assert second.conflicts_count == 1
    assert row.title == "Soybean oil exports rise"
    assert warning is not None
    assert warning.status == "fail"
    assert warning.severity == "warning"
    assert warning.details_json["incoming_values"]["title"] == "Soybean oil exports fall"
    assert warning.details_json["policy_decision"] == "rejected_hash_conflict_no_overwrite"


def test_malformed_article_is_skipped_without_failing_entire_run(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        result = GdeltNewsCollector(
            http_client=FakeGdeltClient(gdelt_json(include_malformed=True)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(session, query_key="soybean", from_date=date(2026, 6, 1), to_date=date(2026, 6, 3), maxrecords=25)
        rows_count = session.scalar(select(func.count()).select_from(NewsArticle))
        skipped_check = session.scalar(select(DataQualityCheck).where(DataQualityCheck.check_name == "news_article_parse_skipped"))
    finally:
        cleanup()

    assert result.status == "success"
    assert result.records_written == 2
    assert result.skipped_malformed == 1
    assert rows_count == 2
    assert skipped_check is not None
    assert skipped_check.severity == "warning"


def test_cli_argument_parsing_supports_gdelt_news() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "gdelt_news",
            "--query-key",
            "soybean",
            "--from-date",
            "2026-06-01",
            "--to-date",
            "2026-06-03",
            "--maxrecords",
            "25",
        ]
    )

    assert args.collector_name == "gdelt_news"
    assert args.query_key == "soybean"
    assert args.from_date == "2026-06-01"
    assert args.to_date == "2026-06-03"
    assert args.maxrecords == 25


def test_cli_rejects_missing_gdelt_dates_without_db_access(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_collector.py", "gdelt_news", "--query-key", "soybean"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert result.returncode != 0
    assert "--from-date and --to-date are required" in result.stderr


def test_operational_report_sees_news_articles(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        GdeltNewsCollector(
            http_client=FakeGdeltClient(),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(session, query_key="soybean", from_date=date(2026, 6, 1), to_date=date(2026, 6, 3), maxrecords=25)
        report = build_operational_report(session=session)
    finally:
        cleanup()

    assert report["news_articles"]["count"] == 2
    assert report["news_articles"]["sources_count"] == 1
    assert report["news_articles"]["first_published_at"] == "2026-06-01T12:00:00+00:00"
    assert report["news_articles"]["last_published_at"] == "2026-06-02T08:15:00+00:00"
    assert report["news_articles"]["languages_count"] == 2


def build_seeded_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    seed_database(session)

    def cleanup() -> None:
        session.close()
        engine.dispose()

    return session, cleanup

