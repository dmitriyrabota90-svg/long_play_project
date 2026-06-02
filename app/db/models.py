from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    collector_runs: Mapped[list[CollectorRun]] = relationship(back_populates="source")


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str] = mapped_column(String(100), nullable=False)
    currency_default: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    collector_name: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    run_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    collection_slot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    source: Mapped[Source | None] = relationship(back_populates="collector_runs")
    raw_responses: Mapped[list[RawResponse]] = relationship(back_populates="collector_run")


class RawResponse(Base):
    __tablename__ = "raw_responses"
    __table_args__ = (
        Index("ix_raw_responses_source_fetched_at", "source_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bytes_size: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    collector_run: Mapped[CollectorRun] = relationship(back_populates="raw_responses")
    source: Mapped[Source] = relationship()


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "source_id",
            "observed_at",
            "source_record_hash",
            name="uq_price_product_source_observed_record_hash",
        ),
        Index("ix_price_observations_product_observed_at", "product_id", "observed_at"),
        Index("ix_price_observations_source_observed_at", "source_id", "observed_at"),
        Index("ix_price_observations_source_product_collection_slot", "source_id", "product_id", "collection_slot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collection_slot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    unit: Mapped[str] = mapped_column(String(100), nullable=False)
    basis: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_period: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    product: Mapped[Product] = relationship()
    source: Mapped[Source] = relationship()
    raw_response: Mapped[RawResponse] = relationship()


class HistoricalPriceBar(Base, TimestampMixin):
    __tablename__ = "historical_price_bars"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "source_id",
            "endpoint_alias",
            "bar_timeframe",
            "bar_date",
            name="uq_hist_bars_product_source_endpoint_timeframe_date",
        ),
        Index("ix_hist_bars_product_bar_date", "product_id", "bar_date"),
        Index("ix_hist_bars_source_fetched_at", "source_id", "fetched_at"),
        Index("ix_hist_bars_product_source_timeframe_date", "product_id", "source_id", "bar_timeframe", "bar_date"),
        Index("ix_hist_bars_raw_response_id", "raw_response_id"),
        Index("ix_hist_bars_collector_run_id", "collector_run_id"),
        Index("ix_hist_bars_source_record_hash", "source_record_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), nullable=False)
    external_code: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint_alias: Mapped[str] = mapped_column(String(50), nullable=False)
    bar_date: Mapped[date] = mapped_column(Date, nullable=False)
    bar_timeframe: Mapped[str] = mapped_column(String(50), nullable=False)
    open_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    high_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    low_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    unit: Mapped[str] = mapped_column(String(100), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    product: Mapped[Product] = relationship()
    source: Mapped[Source] = relationship()
    raw_response: Mapped[RawResponse] = relationship()
    collector_run: Mapped[CollectorRun] = relationship()


class HistoricalPriceBarRevision(Base):
    __tablename__ = "historical_price_bar_revisions"
    __table_args__ = (
        Index("ix_hist_bar_revisions_bar_id", "historical_price_bar_id"),
        Index("ix_hist_bar_revisions_product_created", "product_id", "created_at"),
        Index("ix_hist_bar_revisions_source_created", "source_id", "created_at"),
        Index("ix_hist_bar_revisions_created_at", "created_at"),
        Index("ix_hist_bar_revisions_reason", "revision_reason"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    historical_price_bar_id: Mapped[int] = mapped_column(ForeignKey("historical_price_bars.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), nullable=False)
    revision_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_open: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    previous_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    previous_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    previous_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    previous_volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    previous_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_unit: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    previous_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    new_raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    new_collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), nullable=False)
    new_open: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    new_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    new_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    new_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    new_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    new_volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    new_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    new_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    new_source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    new_source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    historical_price_bar: Mapped[HistoricalPriceBar] = relationship()
    product: Mapped[Product] = relationship()
    source: Mapped[Source] = relationship()
    raw_response: Mapped[RawResponse] = relationship(foreign_keys=[raw_response_id])
    collector_run: Mapped[CollectorRun] = relationship(foreign_keys=[collector_run_id])
    new_raw_response: Mapped[RawResponse] = relationship(foreign_keys=[new_raw_response_id])
    new_collector_run: Mapped[CollectorRun] = relationship(foreign_keys=[new_collector_run_id])


class FxRate(Base):
    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class CommodityBenchmark(Base):
    __tablename__ = "commodity_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    benchmark_code: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    unit: Mapped[str] = mapped_column(String(100), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WeatherObservation(Base):
    __tablename__ = "weather_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    region_code: Mapped[str] = mapped_column(String(100), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    precipitation: Mapped[float] = mapped_column(Float, nullable=False)
    soil_moisture: Mapped[float | None] = mapped_column(Float, nullable=True)
    weather_metric_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        Index("ix_news_items_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tone: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class NewsProductLink(Base):
    __tablename__ = "news_product_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_item_id: Mapped[int] = mapped_column(ForeignKey("news_items.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    match_method: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    news_item: Mapped[NewsItem] = relationship()
    product: Mapped[Product] = relationship()


class DailyProductFeature(Base):
    __tablename__ = "daily_product_features"
    __table_args__ = (
        UniqueConstraint("product_id", "feature_date", name="uq_daily_product_features_product_date"),
        Index("ix_daily_product_features_product_feature_date", "product_id", "feature_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    feature_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(100), nullable=False)
    price_last: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_first: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_observations_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_delta_abs_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_delta_pct_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    price_intraday_delta_abs: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_intraday_delta_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    price_rolling_mean_3d: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_rolling_mean_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    price_rolling_std_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cny_rub: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    usd_rub: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    eur_rub: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cny_rub_delta_abs_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cny_rub_delta_pct_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    usd_rub_delta_abs_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    usd_rub_delta_pct_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    eur_rub_delta_abs_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    eur_rub_delta_pct_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    fx_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    product: Mapped[Product] = relationship()


class DatasetExport(Base):
    __tablename__ = "dataset_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    export_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    train_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    train_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_path: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DataQualityCheck(Base):
    __tablename__ = "data_quality_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    check_name: Mapped[str] = mapped_column(String(100), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    source: Mapped[Source | None] = relationship()
