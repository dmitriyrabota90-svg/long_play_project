from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CollectorRun, CommodityEvent, DailyNewsFeature, NewsArticle, Product, RawResponse, Source
from app.features.news_daily import NEWS_CATEGORY_FIELDS, build_news_daily_features
from app.storage.hashes import stable_json_hash


product_news_migration = import_module("migrations.versions.0015_product_news_features")


PRODUCT_NEWS_COLUMNS = {
    "news_count_1d",
    "news_count_7d",
    "news_count_30d",
    "event_count_1d",
    "event_count_7d",
    "event_count_30d",
    "bullish_event_count_7d",
    "bearish_event_count_7d",
    "mixed_event_count_7d",
    "export_restriction_count_30d",
    "import_policy_count_30d",
    "war_logistics_count_30d",
    "weather_disaster_count_30d",
    "crop_report_count_30d",
    "biofuel_policy_count_30d",
    "energy_shock_count_30d",
    "demand_shock_count_30d",
    "supply_chain_count_30d",
    "sentiment_proxy_7d",
    "news_as_of_date",
    "news_missing_flags",
}


def test_daily_product_feature_metadata_contains_news_columns() -> None:
    table = Base.metadata.tables["daily_product_features"]

    assert PRODUCT_NEWS_COLUMNS <= set(table.c.keys())
    for column_name in PRODUCT_NEWS_COLUMNS:
        assert table.c[column_name].nullable is True


def test_product_news_feature_migration_metadata_and_columns() -> None:
    migration_columns = {name for name, _column_type in product_news_migration.NEWS_PRODUCT_COLUMNS}

    assert product_news_migration.revision == "0015_product_news_features"
    assert product_news_migration.down_revision == "0014_news_events_schema"
    assert migration_columns == PRODUCT_NEWS_COLUMNS


def test_news_daily_builder_counts_windows_categories_and_sentiment() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        products = _seed_products(session)
        source, run, raw = _seed_news_source_lineage(session)
        _article(session, source=source, run=run, raw=raw, product_codes=["soybean_oil", "soybean_meal"], published_at=date(2026, 6, 10))
        _article(session, source=source, run=run, raw=raw, product_codes=["soybean_oil", "soybean_meal"], published_at=date(2026, 6, 5))
        _article(session, source=source, run=run, raw=raw, product_codes=["soybean_oil", "soybean_meal"], published_at=date(2026, 5, 20))
        _article(session, source=source, run=run, raw=raw, product_codes=["soybean_oil", "soybean_meal"], published_at=date(2026, 6, 11))
        _event(
            session,
            source=source,
            article_id=1,
            family="soybean",
            category="export_restriction",
            direction="bullish",
            event_date=date(2026, 6, 10),
            product_codes=["soybean_oil", "soybean_meal"],
        )
        _event(
            session,
            source=source,
            article_id=2,
            family="soybean",
            category="import_policy",
            direction="bearish",
            event_date=date(2026, 6, 8),
            product_codes=["soybean_oil", "soybean_meal"],
        )
        _event(
            session,
            source=source,
            article_id=2,
            family="soybean",
            category="crop_report",
            direction="mixed",
            event_date=date(2026, 6, 5),
            product_codes=["soybean_oil", "soybean_meal"],
        )
        _event(
            session,
            source=source,
            article_id=3,
            family="soybean",
            category="energy_shock",
            direction="mixed",
            event_date=date(2026, 5, 20),
            product_codes=["soybean_oil", "soybean_meal"],
        )
        _event(
            session,
            source=source,
            article_id=4,
            family="soybean",
            category="demand_shock",
            direction="bullish",
            event_date=date(2026, 6, 11),
            product_codes=["soybean_oil", "soybean_meal"],
        )

        result = build_news_daily_features(
            session=session,
            product_code="soybean_oil",
            from_date=date(2026, 6, 10),
            to_date=date(2026, 6, 10),
        )
        session.commit()
        feature = session.scalar(
            select(DailyNewsFeature).where(DailyNewsFeature.product_id == products["soybean_oil"].id)
        )

    assert result.products_processed == 1
    assert result.dates_processed == 1
    assert result.rows_created == 1
    assert result.rows_updated == 0
    assert result.rows_skipped == 0
    assert feature.news_count_1d == 1
    assert feature.news_count_7d == 2
    assert feature.news_count_30d == 3
    assert feature.event_count_1d == 1
    assert feature.event_count_7d == 3
    assert feature.event_count_30d == 4
    assert feature.bullish_event_count_7d == 1
    assert feature.bearish_event_count_7d == 1
    assert feature.mixed_event_count_7d == 1
    assert feature.export_restriction_count_30d == 1
    assert feature.import_policy_count_30d == 1
    assert feature.crop_report_count_30d == 1
    assert feature.energy_shock_count_30d == 1
    assert feature.demand_shock_count_30d == 0
    assert feature.sentiment_proxy_7d == Decimal("0E-8")
    assert feature.news_as_of_date == date(2026, 6, 10)
    assert feature.missing_flags is None
    assert sorted(feature.metadata_json["event_ids_30d"]) == [1, 2, 3, 4]


def test_product_family_mapping_for_generic_and_macro_events() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        products = _seed_products(session)
        source, run, raw = _seed_news_source_lineage(session)
        article = _article(session, source=source, run=run, raw=raw, product_codes=["soybean_oil", "rapeseed_oil"], published_at=date(2026, 6, 10))
        _event(
            session,
            source=source,
            article_id=article.id,
            family="vegetable_oils",
            category="supply_chain",
            direction="bullish",
            event_date=date(2026, 6, 10),
            product_codes=[],
        )
        _event(
            session,
            source=source,
            article_id=article.id,
            family="fertilizer_energy",
            category="energy_shock",
            direction="mixed",
            event_date=date(2026, 6, 10),
            product_codes=[],
        )

        build_news_daily_features(session=session, from_date=date(2026, 6, 10), to_date=date(2026, 6, 10))
        session.commit()
        by_code = {
            product.code: feature
            for product, feature in session.execute(
                select(Product, DailyNewsFeature).join(DailyNewsFeature, DailyNewsFeature.product_id == Product.id)
            ).all()
        }

    assert by_code["soybean_oil"].event_count_1d == 2
    assert by_code["rapeseed_oil"].event_count_1d == 2
    assert by_code["soybean_meal"].event_count_1d == 1
    assert by_code["rapeseed_meal"].event_count_1d == 1
    assert by_code["soybean_meal"].supply_chain_count_30d == 0
    assert by_code["soybean_meal"].energy_shock_count_30d == 1
    assert products["rapeseed_oil"].code in by_code


def test_missing_flags_and_no_event_sentiment_are_deterministic() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        products = _seed_products(session)
        result = build_news_daily_features(
            session=session,
            product_code="rapeseed_meal",
            from_date=date(2026, 6, 10),
            to_date=date(2026, 6, 10),
        )
        session.commit()
        feature = session.scalar(
            select(DailyNewsFeature).where(DailyNewsFeature.product_id == products["rapeseed_meal"].id)
        )

    assert result.rows_created == 1
    assert result.warnings_count == 1
    assert result.missing_news_products == ["rapeseed_meal"]
    assert feature.news_count_30d == 0
    assert feature.event_count_30d == 0
    assert feature.sentiment_proxy_7d is None
    assert feature.news_as_of_date is None
    assert feature.missing_flags == {
        "no_news_articles": True,
        "no_commodity_events": True,
        "partial_source_coverage": True,
    }


def test_news_daily_idempotent_rerun_skips_then_updates_changed_values() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_products(session)
        source, run, raw = _seed_news_source_lineage(session)
        article = _article(session, source=source, run=run, raw=raw, product_codes=["soybean_oil", "soybean_meal"], published_at=date(2026, 6, 10))

        first = build_news_daily_features(session=session, product_code="soybean_oil", from_date=date(2026, 6, 10), to_date=date(2026, 6, 10))
        second = build_news_daily_features(session=session, product_code="soybean_oil", from_date=date(2026, 6, 10), to_date=date(2026, 6, 10))
        _event(
            session,
            source=source,
            article_id=article.id,
            family="soybean",
            category="export_restriction",
            direction="bullish",
            event_date=date(2026, 6, 10),
            product_codes=["soybean_oil", "soybean_meal"],
        )
        third = build_news_daily_features(session=session, product_code="soybean_oil", from_date=date(2026, 6, 10), to_date=date(2026, 6, 10))
        rows_count = session.scalar(select(func.count()).select_from(DailyNewsFeature))

    assert first.rows_created == 1
    assert second.rows_skipped == 1
    assert third.rows_updated == 1
    assert rows_count == 1


def test_news_daily_cli_runs_against_fixture_db(tmp_path: Path) -> None:
    db_path = tmp_path / "news_daily.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    SessionLocal = _session_factory(database_url)
    with SessionLocal() as session:
        _seed_products(session)
        source, run, raw = _seed_news_source_lineage(session)
        _article(session, source=source, run=run, raw=raw, product_codes=["soybean_oil", "soybean_meal"], published_at=date(2026, 6, 10))
        session.commit()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_features.py",
            "news_daily",
            "--product",
            "soybean_oil",
            "--from-date",
            "2026-06-10",
            "--to-date",
            "2026-06-10",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": database_url, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert "products_processed=1" in result.stdout
    assert "dates_processed=1" in result.stdout
    assert "rows_created=1" in result.stdout


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_products(session) -> dict[str, Product]:
    products = {}
    for code, category in (
        ("rapeseed_oil", "oil"),
        ("soybean_oil", "oil"),
        ("rapeseed_meal", "meal"),
        ("soybean_meal", "meal"),
    ):
        product = Product(code=code, name=code.replace("_", " ").title(), category=category, unit="metric_ton", currency_default="CNY")
        session.add(product)
        session.flush()
        products[code] = product
    return products


def _seed_news_source_lineage(session):
    source = Source(code="gdelt_2_1", name="GDELT 2.1 DOC/Event APIs", source_type="news_event", base_url="https://www.gdeltproject.org/")
    session.add(source)
    session.flush()
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
        sha256="a" * 64,
        bytes_size=100,
        parser_version="gdelt_news_v1",
    )
    session.add(raw)
    session.flush()
    return source, run, raw


def _article(
    session,
    *,
    source: Source,
    run: CollectorRun,
    raw: RawResponse,
    product_codes: list[str],
    published_at: date,
) -> NewsArticle:
    title = f"Fixture article {published_at.isoformat()} {' '.join(product_codes)}"
    article = NewsArticle(
        source_id=source.id,
        raw_response_id=raw.id,
        collector_run_id=run.id,
        external_id=f"fixture-{published_at.isoformat()}-{len(product_codes)}-{session.scalar(select(func.count()).select_from(NewsArticle))}",
        url=f"https://example.test/{published_at.isoformat()}",
        canonical_url=None,
        title=title,
        summary=None,
        body_text=None,
        language="English",
        source_name="Fixture",
        country=None,
        region=None,
        published_at=datetime.combine(published_at, datetime.min.time(), tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        article_hash=stable_json_hash({"title": title, "published_at": published_at.isoformat()}),
        source_record_hash=stable_json_hash({"title": title}),
        source_payload_hash=raw.sha256,
        metadata_json={
            "query_key": "fixture",
            "affected_products_hint": product_codes,
            "commodity_family_hint": "soybean" if "soybean_oil" in product_codes else "vegetable_oils",
        },
    )
    session.add(article)
    session.flush()
    return article


def _event(
    session,
    *,
    source: Source,
    article_id: int,
    family: str,
    category: str,
    direction: str,
    event_date: date,
    product_codes: list[str],
) -> CommodityEvent:
    event = CommodityEvent(
        news_article_id=article_id,
        source_id=source.id,
        event_category=category,
        commodity_family=family,
        affected_products={"product_codes": product_codes, "mapping_basis": "test"},
        country=None,
        region=None,
        event_date=event_date,
        published_at=datetime.combine(event_date, datetime.min.time(), tzinfo=timezone.utc),
        direction_hint=direction,
        severity=Decimal("0.5"),
        confidence=Decimal("0.8"),
        lag_bucket="same_day",
        extraction_method="keyword_rule",
        extraction_version="news_event_rules_v1",
        source_text_hash=stable_json_hash({"event_date": event_date.isoformat(), "category": category, "family": family}),
        metadata_json={"test": True},
    )
    assert category in NEWS_CATEGORY_FIELDS or category == "crop_report"
    session.add(event)
    session.flush()
    return event
