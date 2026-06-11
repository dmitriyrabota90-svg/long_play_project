from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CollectorRun, CommodityEvent, DataQualityCheck, NewsArticle, RawResponse, Source
from app.db.seed import seed_database
from app.features.news_event_rules import COMMODITY_FAMILY_RULES_BY_FAMILY, EVENT_RULES_BY_CATEGORY, EXTRACTION_VERSION
from app.features.news_events import (
    build_source_text_hash,
    detect_commodity_families,
    detect_event_categories,
    extract_candidates_for_article,
    extract_news_events,
    normalize_text,
)
from app.monitoring.operational_report import build_operational_report
from app.storage.hashes import stable_json_hash
from scripts.extract_news_events import build_parser


def test_rule_config_contains_all_taxonomy_categories() -> None:
    expected = {
        "export_restriction",
        "import_policy",
        "war_logistics_disruption",
        "weather_disaster",
        "crop_report",
        "biofuel_policy",
        "energy_shock",
        "currency_macro",
        "demand_shock",
        "supply_chain",
    }

    assert expected == set(EVENT_RULES_BY_CATEGORY)
    assert {"soybean", "rapeseed", "vegetable_oils", "grains", "fertilizer_energy"} <= set(COMMODITY_FAMILY_RULES_BY_FAMILY)


def test_soybean_export_restriction_article_creates_candidate() -> None:
    article = _article(title="Argentina announces soybean meal export ban after crop shortfall")

    candidates = extract_candidates_for_article(article)

    assert len(candidates) == 1
    event = candidates[0]
    assert event.event_category == "export_restriction"
    assert event.commodity_family == "soybean"
    assert event.affected_products["product_codes"] == ["soybean_oil", "soybean_meal"]
    assert event.direction_hint == "bullish"
    assert event.event_date == date(2026, 6, 2)
    assert Decimal("0") <= event.confidence <= Decimal("1")
    assert event.extraction_version == EXTRACTION_VERSION


def test_rapeseed_weather_disaster_article_creates_candidate() -> None:
    article = _article(title="Canada canola crop hit by drought in key production areas")

    candidates = extract_candidates_for_article(article)

    assert {(item.event_category, item.commodity_family) for item in candidates} == {("weather_disaster", "rapeseed")}
    assert candidates[0].lag_bucket == "7_30d"


def test_crop_report_article_creates_candidate() -> None:
    article = _article(title="USDA crop report cuts soybean production forecast")

    candidates = extract_candidates_for_article(article)

    assert {(item.event_category, item.commodity_family) for item in candidates} == {("crop_report", "soybean")}
    assert candidates[0].direction_hint == "mixed"


def test_energy_shock_article_creates_candidate() -> None:
    article = _article(title="Brent crude oil prices spike, lifting diesel costs")

    candidates = extract_candidates_for_article(article)

    assert {(item.event_category, item.commodity_family) for item in candidates} == {("energy_shock", "fertilizer_energy")}
    assert candidates[0].affected_products["product_codes"] == [
        "rapeseed_oil",
        "soybean_oil",
        "rapeseed_meal",
        "soybean_meal",
    ]


def test_unrelated_article_creates_no_candidate() -> None:
    article = _article(title="Technology shares rise after software earnings")

    assert extract_candidates_for_article(article) == []


def test_commodity_family_detection_and_confidence_inputs() -> None:
    text = normalize_text("Soybean oil and soybean meal demand rises while wheat remains steady")
    families = detect_commodity_families(text)
    categories = detect_event_categories(normalize_text("China soybean imports demand rise"))

    assert [item.rule.commodity_family for item in families] == ["soybean", "grains"]
    assert [item.rule.event_category for item in categories] == ["demand_shock"]


def test_new_events_inserted_into_commodity_events() -> None:
    session, cleanup = build_seeded_session()
    try:
        article = add_article(session, title="Argentina announces soybean oil export ban")
        result = extract_news_events(session=session, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3))
        event = session.scalar(select(CommodityEvent).where(CommodityEvent.news_article_id == article.id))
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())
    finally:
        cleanup()

    assert result.articles_scanned == 1
    assert result.articles_with_events == 1
    assert result.events_found == 1
    assert result.events_written == 1
    assert result.skipped_existing == 0
    assert result.conflicts_count == 0
    assert event is not None
    assert event.event_category == "export_restriction"
    assert event.commodity_family == "soybean"
    assert event.event_date == date(2026, 6, 2)
    assert event.published_at.replace(tzinfo=timezone.utc) == datetime(2026, 6, 2, 10, tzinfo=timezone.utc)
    assert event.extraction_method == "keyword_rule"
    assert event.source_text_hash == build_source_text_hash(article)
    assert "news_event_inserted" in check_names
    assert "news_event_confidence_valid" in check_names


def test_rerun_same_article_skips_existing_event() -> None:
    session, cleanup = build_seeded_session()
    try:
        add_article(session, title="Argentina announces soybean oil export ban")
        first = extract_news_events(session=session, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3))
        second = extract_news_events(session=session, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3))
        rows_count = session.scalar(select(func.count()).select_from(CommodityEvent))
    finally:
        cleanup()

    assert first.events_written == 1
    assert second.events_written == 0
    assert second.skipped_existing == 1
    assert second.conflicts_count == 0
    assert rows_count == 1


def test_changed_source_text_hash_creates_conflict_warning_without_overwrite() -> None:
    session, cleanup = build_seeded_session()
    try:
        article = add_article(
            session,
            title="Argentina announces soybean oil export ban",
            summary="Initial summary.",
        )
        extract_news_events(session=session, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3))
        article.summary = "Updated summary with new details."
        session.flush()
        second = extract_news_events(session=session, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3))
        event = session.scalar(select(CommodityEvent))
        warning = session.scalar(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "commodity_event_existing_rule_hash_changed")
        )
    finally:
        cleanup()

    assert second.events_written == 0
    assert second.skipped_existing == 0
    assert second.conflicts_count == 1
    assert event.source_text_hash != build_source_text_hash(article)
    assert warning is not None
    assert warning.status == "fail"
    assert warning.severity == "warning"
    assert warning.details_json["policy_decision"] == "rejected_rule_hash_conflict_no_overwrite"


def test_unrelated_article_writes_skip_quality_without_failure() -> None:
    session, cleanup = build_seeded_session()
    try:
        add_article(session, title="Technology shares rise after software earnings")
        result = extract_news_events(session=session, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3))
        rows_count = session.scalar(select(func.count()).select_from(CommodityEvent))
        checks = session.scalars(select(DataQualityCheck).where(DataQualityCheck.check_name.like("news_event_%"))).all()
    finally:
        cleanup()

    assert result.articles_scanned == 1
    assert result.events_found == 0
    assert result.events_written == 0
    assert rows_count == 0
    assert any(check.check_name == "news_event_no_relevant_event_detected" and check.status == "skip" for check in checks)
    assert all(check.status != "fail" for check in checks)


def test_missing_text_is_handled_safely() -> None:
    article = _article(title="", summary=None, body_text=None)

    assert extract_candidates_for_article(article) == []


def test_dry_run_finds_events_without_writing() -> None:
    session, cleanup = build_seeded_session()
    try:
        add_article(session, title="Argentina announces soybean oil export ban")
        result = extract_news_events(
            session=session,
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 3),
            dry_run=True,
        )
        rows_count = session.scalar(select(func.count()).select_from(CommodityEvent))
    finally:
        cleanup()

    assert result.dry_run is True
    assert result.events_found == 1
    assert result.events_written == 0
    assert rows_count == 0


def test_cli_argument_parsing_supports_news_event_extraction() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "--from-date",
            "2026-06-01",
            "--to-date",
            "2026-06-03",
            "--source",
            "gdelt_2_1",
            "--limit",
            "10",
            "--dry-run",
        ]
    )

    assert args.from_date == "2026-06-01"
    assert args.to_date == "2026-06-03"
    assert args.source == "gdelt_2_1"
    assert args.limit == 10
    assert args.dry_run is True


def test_cli_rejects_bad_dates_without_db_access(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/extract_news_events.py",
            "--from-date",
            "2026-06-03",
            "--to-date",
            "2026-06-01",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert result.returncode != 0
    assert "--from-date must be on or before --to-date" in result.stderr


def test_operational_report_sees_commodity_events() -> None:
    session, cleanup = build_seeded_session()
    try:
        add_article(session, title="Argentina announces soybean oil export ban")
        extract_news_events(session=session, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3))
        report = build_operational_report(session=session)
    finally:
        cleanup()

    assert report["commodity_events"]["count"] == 1
    assert report["commodity_events"]["categories_count"] == 1
    assert report["commodity_events"]["commodity_families_count"] == 1
    assert report["commodity_events"]["first_event_date"] == "2026-06-02"
    assert report["commodity_events"]["last_event_date"] == "2026-06-02"
    assert report["commodity_events"]["latest_published_at"] == "2026-06-02T10:00:00+00:00"


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


def add_article(
    session,
    *,
    title: str,
    summary: str | None = None,
    body_text: str | None = None,
    published_at: datetime = datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
) -> NewsArticle:
    source = session.scalar(select(Source).where(Source.code == "gdelt_2_1"))
    run = CollectorRun(
        source_id=source.id,
        collector_name="gdelt_news",
        started_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        status="success",
        run_type="manual",
    )
    session.add(run)
    session.flush()
    raw = RawResponse(
        source_id=source.id,
        collector_run_id=run.id,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        method="GET",
        status_code=200,
        content_type="application/json",
        storage_path=f"data/raw/gdelt_2_1/2026/06/11/{run.id}/hash.json",
        sha256=stable_json_hash({"title": title}),
        bytes_size=1000,
        parser_version="gdelt_news_v1",
    )
    session.add(raw)
    session.flush()
    article = _article(
        source_id=source.id,
        raw_response_id=raw.id,
        collector_run_id=run.id,
        title=title,
        summary=summary,
        body_text=body_text,
        published_at=published_at,
    )
    session.add(article)
    session.flush()
    return article


def _article(
    *,
    source_id: int = 1,
    raw_response_id: int = 1,
    collector_run_id: int = 1,
    title: str,
    summary: str | None = None,
    body_text: str | None = None,
    published_at: datetime = datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
) -> NewsArticle:
    article_hash = stable_json_hash({"title": title, "published_at": published_at.isoformat()})
    return NewsArticle(
        id=None,
        source_id=source_id,
        raw_response_id=raw_response_id,
        collector_run_id=collector_run_id,
        external_id=None,
        url=f"https://example.com/{article_hash[:12]}",
        canonical_url=f"https://example.com/{article_hash[:12]}",
        title=title,
        summary=summary,
        body_text=body_text,
        language="English",
        source_name="Example News",
        country="Argentina" if "argentina" in title.casefold() else None,
        region=None,
        published_at=published_at,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        article_hash=article_hash,
        source_record_hash=stable_json_hash({"title": title, "summary": summary, "body_text": body_text}),
        source_payload_hash="a" * 64,
        metadata_json={"fixture": True},
    )
