from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CollectorRun, CommodityEvent, DailyNewsFeature, NewsArticle, Product, RawResponse, Source


news_events_migration = import_module("migrations.versions.0014_news_events_schema")


def test_metadata_contains_news_event_tables() -> None:
    assert "news_articles" in Base.metadata.tables
    assert "commodity_events" in Base.metadata.tables
    assert "daily_news_features" in Base.metadata.tables


def test_news_articles_required_columns_indexes_and_partial_unique_index() -> None:
    table = Base.metadata.tables["news_articles"]
    expected_columns = {
        "id",
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "external_id",
        "url",
        "canonical_url",
        "title",
        "summary",
        "body_text",
        "language",
        "source_name",
        "country",
        "region",
        "published_at",
        "fetched_at",
        "article_hash",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    index_names = {index.name for index in table.indexes}
    external_id_index = next(index for index in table.indexes if index.name == "uq_news_articles_source_external_id")

    assert expected_columns <= set(table.c.keys())
    assert table.c.source_id.nullable is False
    assert table.c.raw_response_id.nullable is False
    assert table.c.collector_run_id.nullable is False
    assert table.c.published_at.nullable is False
    assert table.c.fetched_at.nullable is False
    assert external_id_index.unique is True
    assert "external_id IS NOT NULL" in str(external_id_index.dialect_options["postgresql"]["where"])
    assert {
        "uq_news_articles_source_external_id",
        "uq_news_articles_source_article_hash",
        "ix_news_articles_source_published",
        "ix_news_articles_published_at",
        "ix_news_articles_language",
        "ix_news_articles_country",
        "ix_news_articles_article_hash",
        "ix_news_articles_raw_response_id",
        "ix_news_articles_collector_run_id",
        "ix_news_articles_record_hash",
    } <= index_names


def test_commodity_events_required_columns_constraints_and_indexes() -> None:
    table = Base.metadata.tables["commodity_events"]
    expected_columns = {
        "id",
        "news_article_id",
        "source_id",
        "event_category",
        "commodity_family",
        "affected_products",
        "country",
        "region",
        "event_date",
        "published_at",
        "direction_hint",
        "severity",
        "confidence",
        "lag_bucket",
        "extraction_method",
        "extraction_version",
        "source_text_hash",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert expected_columns <= set(table.c.keys())
    assert table.c.news_article_id.nullable is False
    assert table.c.source_id.nullable is False
    assert "uq_commodity_events_identity" in constraint_names
    assert "ck_commodity_events_category" in constraint_names
    assert "ck_commodity_events_direction" in constraint_names
    assert "ck_commodity_events_lag_bucket" in constraint_names
    assert "ck_commodity_events_method" in constraint_names
    assert "ck_commodity_events_confidence" in constraint_names
    assert {
        "ix_commodity_events_category_date",
        "ix_commodity_events_family_date",
        "ix_commodity_events_country_date",
        "ix_commodity_events_published_at",
        "ix_commodity_events_direction",
        "ix_commodity_events_confidence",
        "ix_commodity_events_article_id",
        "ix_commodity_events_source_id",
    } <= index_names


def test_daily_news_features_required_columns_constraints_and_indexes() -> None:
    table = Base.metadata.tables["daily_news_features"]
    expected_columns = {
        "id",
        "product_id",
        "commodity_family",
        "feature_date",
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
        "missing_flags",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert expected_columns <= set(table.c.keys())
    assert table.c.product_id.nullable is False
    assert "uq_daily_news_features_product_date" in constraint_names
    assert {
        "ix_daily_news_features_product_date",
        "ix_daily_news_features_family_date",
        "ix_daily_news_features_feature_date",
        "ix_daily_news_features_as_of",
    } <= index_names


def test_news_events_migration_revision_metadata_and_partial_index() -> None:
    migration_text = Path(news_events_migration.__file__).read_text(encoding="utf-8")

    assert news_events_migration.revision == "0014_news_events_schema"
    assert news_events_migration.down_revision == "0013_product_weather_features"
    assert "op.create_table(\n        \"news_articles\"" in migration_text
    assert "op.create_table(\n        \"commodity_events\"" in migration_text
    assert "op.create_table(\n        \"daily_news_features\"" in migration_text
    assert "postgresql_where=sa.text(\"external_id IS NOT NULL\")" in migration_text


def test_create_all_creates_news_event_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "news_articles" in table_names
    assert "commodity_events" in table_names
    assert "daily_news_features" in table_names


def test_news_article_event_and_daily_feature_insert_and_unique_constraints() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        source = Source(
            code="gdelt_2_1",
            name="GDELT 2.1 DOC/Event APIs",
            source_type="news_event",
            base_url="https://www.gdeltproject.org/",
        )
        product = Product(
            code="soybean_oil",
            name="Soybean oil",
            category="oil",
            unit="metric_ton",
            currency_default="USD",
        )
        session.add_all([source, product])
        session.flush()
        run = CollectorRun(
            source_id=source.id,
            collector_name="gdelt_news_collector",
            started_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
            status="success",
            run_type="manual",
        )
        session.add(run)
        session.flush()
        raw = RawResponse(
            source_id=source.id,
            collector_run_id=run.id,
            fetched_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
            url="https://api.gdeltproject.org/api/v2/doc/doc",
            method="GET",
            status_code=200,
            content_type="application/json",
            storage_path="data/raw/gdelt_2_1/2026/06/11/1/hash.json",
            sha256="a" * 64,
            bytes_size=2000,
            parser_version="gdelt_news_v1",
        )
        session.add(raw)
        session.flush()

        article = _news_article(source.id, raw.id, run.id)
        session.add(article)
        session.flush()
        session.add(_commodity_event(article.id, source.id))
        session.add(_daily_news_feature(product.id))
        session.commit()

        loaded_article = session.scalar(select(NewsArticle).where(NewsArticle.article_hash == "article" + "a" * 57))
        assert loaded_article is not None
        assert loaded_article.raw_response_id == raw.id
        assert loaded_article.collector_run_id == run.id
        assert loaded_article.source_payload_hash == raw.sha256

        session.add(_news_article(source.id, raw.id, run.id, external_id="different-id"))
        with pytest.raises(IntegrityError):
            session.commit()


def _news_article(
    source_id: int,
    raw_response_id: int,
    collector_run_id: int,
    *,
    external_id: str = "article-1",
) -> NewsArticle:
    return NewsArticle(
        source_id=source_id,
        raw_response_id=raw_response_id,
        collector_run_id=collector_run_id,
        external_id=external_id,
        url="https://example.com/article-1",
        canonical_url="https://example.com/article-1",
        title="Soybean export policy changes",
        summary="Policy summary",
        body_text=None,
        language="en",
        source_name="Example News",
        country="Brazil",
        region="Mato Grosso",
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        article_hash="article" + "a" * 57,
        source_record_hash="record" + "a" * 58,
        source_payload_hash="a" * 64,
        metadata_json={"query": "soybean export restriction"},
    )


def _commodity_event(news_article_id: int, source_id: int) -> CommodityEvent:
    return CommodityEvent(
        news_article_id=news_article_id,
        source_id=source_id,
        event_category="export_restriction",
        commodity_family="soybean",
        affected_products={"product_codes": ["soybean_oil", "soybean_meal"]},
        country="Brazil",
        region="Mato Grosso",
        event_date=date(2026, 6, 10),
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        direction_hint="bullish",
        severity=Decimal("0.70000000"),
        confidence=Decimal("0.90000000"),
        lag_bucket="1_7d",
        extraction_method="keyword_rule",
        extraction_version="news_rules_v1",
        source_text_hash="text" + "a" * 60,
        metadata_json={"matched_keywords": ["export", "quota"]},
    )


def _daily_news_feature(product_id: int) -> DailyNewsFeature:
    return DailyNewsFeature(
        product_id=product_id,
        commodity_family="soybean",
        feature_date=date(2026, 6, 10),
        news_count_1d=1,
        news_count_7d=3,
        news_count_30d=10,
        event_count_1d=1,
        event_count_7d=2,
        event_count_30d=5,
        bullish_event_count_7d=1,
        bearish_event_count_7d=0,
        mixed_event_count_7d=1,
        export_restriction_count_30d=1,
        import_policy_count_30d=0,
        war_logistics_count_30d=0,
        weather_disaster_count_30d=1,
        crop_report_count_30d=1,
        biofuel_policy_count_30d=0,
        energy_shock_count_30d=1,
        demand_shock_count_30d=1,
        supply_chain_count_30d=0,
        sentiment_proxy_7d=Decimal("0.50000000"),
        news_as_of_date=date(2026, 6, 10),
        missing_flags={"gdelt": False},
        metadata_json={"aggregation_version": "news_daily_v1"},
    )
