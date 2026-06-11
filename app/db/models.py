from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    text,
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


class EnergyPrice(Base, TimestampMixin):
    __tablename__ = "energy_prices"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "instrument_code",
            "frequency",
            "period_start",
            "period_end",
            name="uq_energy_source_instr_freq_period",
        ),
        CheckConstraint("period_end >= period_start", name="ck_energy_prices_period_order"),
        CheckConstraint("frequency IN ('daily', 'weekly', 'monthly')", name="ck_energy_prices_frequency"),
        Index("ix_energy_source_instr_period", "source_id", "instrument_code", "period_start", "period_end"),
        Index("ix_energy_instr_observed", "instrument_code", "observed_at"),
        Index("ix_energy_category_observed", "instrument_category", "observed_at"),
        Index("ix_energy_fetched_at", "fetched_at"),
        Index("ix_energy_raw_response_id", "raw_response_id"),
        Index("ix_energy_collector_run_id", "collector_run_id"),
        Index("ix_energy_source_record_hash", "source_record_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), nullable=False)
    instrument_code: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    instrument_name: Mapped[str] = mapped_column(String(255), nullable=False)
    instrument_category: Mapped[str] = mapped_column(String(100), nullable=False)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unit: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    normalized_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    normalized_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    source: Mapped[Source] = relationship()
    raw_response: Mapped[RawResponse] = relationship()
    collector_run: Mapped[CollectorRun] = relationship()


class CommodityBenchmark(Base, TimestampMixin):
    __tablename__ = "commodity_benchmarks"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "benchmark_code",
            "frequency",
            "period_start",
            "period_end",
            name="uq_comm_bench_source_code_freq_period",
        ),
        CheckConstraint("period_end >= period_start", name="ck_comm_bench_period_order"),
        CheckConstraint("frequency IN ('daily', 'weekly', 'monthly')", name="ck_comm_bench_frequency"),
        Index("ix_comm_bench_source_code_period", "source_id", "benchmark_code", "period_start", "period_end"),
        Index("ix_comm_bench_code_observed", "benchmark_code", "observed_at"),
        Index("ix_comm_bench_category_observed", "benchmark_category", "observed_at"),
        Index("ix_comm_bench_family_observed", "commodity_family", "observed_at"),
        Index("ix_comm_bench_fetched_at", "fetched_at"),
        Index("ix_comm_bench_raw_response_id", "raw_response_id"),
        Index("ix_comm_bench_collector_run_id", "collector_run_id"),
        Index("ix_comm_bench_source_record_hash", "source_record_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), nullable=False)
    benchmark_code: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    benchmark_name: Mapped[str] = mapped_column(String(255), nullable=False)
    benchmark_category: Mapped[str] = mapped_column(String(100), nullable=False)
    commodity_family: Mapped[str] = mapped_column(String(100), nullable=False)
    geography: Mapped[str] = mapped_column(String(100), nullable=False)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unit: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    normalized_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    normalized_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    source: Mapped[Source] = relationship()
    raw_response: Mapped[RawResponse] = relationship()
    collector_run: Mapped[CollectorRun] = relationship()


class WeatherRegion(Base, TimestampMixin):
    __tablename__ = "weather_regions"
    __table_args__ = (
        UniqueConstraint("region_code", name="uq_weather_regions_code"),
        CheckConstraint("priority IN ('high', 'medium', 'later')", name="ck_weather_regions_priority"),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_weather_regions_latitude"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_weather_regions_longitude"),
        Index("ix_weather_regions_code", "region_code"),
        Index("ix_weather_regions_country_crop", "country", "crop"),
        Index("ix_weather_regions_family", "commodity_family"),
        Index("ix_weather_regions_active", "is_active"),
        Index("ix_weather_regions_priority", "priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_code: Mapped[str] = mapped_column(String(100), nullable=False)
    region_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    crop: Mapped[str] = mapped_column(String(100), nullable=False)
    commodity_family: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    spatial_model: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregation_strategy: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class WeatherObservation(Base, TimestampMixin):
    __tablename__ = "weather_observations"
    __table_args__ = (
        UniqueConstraint("source_id", "region_id", "observation_date", "frequency", name="uq_weather_obs_source_region_date_freq"),
        CheckConstraint("frequency IN ('daily')", name="ck_weather_obs_frequency"),
        Index("ix_weather_obs_region_date", "region_id", "observation_date"),
        Index("ix_weather_obs_source_date", "source_id", "observation_date"),
        Index("ix_weather_obs_fetched_at", "fetched_at"),
        Index("ix_weather_obs_raw_response_id", "raw_response_id"),
        Index("ix_weather_obs_collector_run_id", "collector_run_id"),
        Index("ix_weather_obs_record_hash", "source_record_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("weather_regions.id"), nullable=False)
    source_region_key: Mapped[str] = mapped_column(String(255), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    temperature_2m_mean: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    temperature_2m_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    temperature_2m_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    precipitation_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    snowfall_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    relative_humidity_mean: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    wind_speed_mean: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    wind_speed_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    soil_moisture: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    evapotranspiration: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    shortwave_radiation: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    source: Mapped[Source] = relationship()
    raw_response: Mapped[RawResponse] = relationship()
    collector_run: Mapped[CollectorRun] = relationship()
    region: Mapped[WeatherRegion] = relationship()


class WeatherDailyFeature(Base, TimestampMixin):
    __tablename__ = "weather_daily_features"
    __table_args__ = (
        UniqueConstraint("region_id", "feature_date", name="uq_weather_daily_region_date"),
        Index("ix_weather_daily_region_date", "region_id", "feature_date"),
        Index("ix_weather_daily_feature_date", "feature_date"),
        Index("ix_weather_daily_as_of_date", "weather_as_of_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("weather_regions.id"), nullable=False)
    feature_date: Mapped[date] = mapped_column(Date, nullable=False)
    temperature_7d_mean: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    temperature_30d_mean: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    temperature_min_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    temperature_max_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    precipitation_7d_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    precipitation_14d_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    precipitation_30d_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    heat_stress_days_7d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heat_stress_days_30d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frost_days_7d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frost_days_30d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drought_proxy_30d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    growing_degree_days_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    growing_degree_days_30d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    missing_flags: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    region: Mapped[WeatherRegion] = relationship()


class NewsArticle(Base, TimestampMixin):
    __tablename__ = "news_articles"
    __table_args__ = (
        Index(
            "uq_news_articles_source_external_id",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index("uq_news_articles_source_article_hash", "source_id", "article_hash", unique=True),
        Index("ix_news_articles_source_published", "source_id", "published_at"),
        Index("ix_news_articles_published_at", "published_at"),
        Index("ix_news_articles_language", "language"),
        Index("ix_news_articles_country", "country"),
        Index("ix_news_articles_article_hash", "article_hash"),
        Index("ix_news_articles_raw_response_id", "raw_response_id"),
        Index("ix_news_articles_collector_run_id", "collector_run_id"),
        Index("ix_news_articles_record_hash", "source_record_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_response_id: Mapped[int] = mapped_column(ForeignKey("raw_responses.id"), nullable=False)
    collector_run_id: Mapped[int] = mapped_column(ForeignKey("collector_runs.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    article_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    source: Mapped[Source] = relationship()
    raw_response: Mapped[RawResponse] = relationship()
    collector_run: Mapped[CollectorRun] = relationship()


class CommodityEvent(Base, TimestampMixin):
    __tablename__ = "commodity_events"
    __table_args__ = (
        UniqueConstraint(
            "news_article_id",
            "event_category",
            "commodity_family",
            "country",
            "region",
            "event_date",
            "extraction_method",
            name="uq_commodity_events_identity",
        ),
        CheckConstraint(
            "event_category IN ("
            "'export_restriction', 'import_policy', 'war_logistics_disruption', "
            "'weather_disaster', 'crop_report', 'biofuel_policy', 'energy_shock', "
            "'currency_macro', 'demand_shock', 'supply_chain'"
            ")",
            name="ck_commodity_events_category",
        ),
        CheckConstraint("direction_hint IN ('bullish', 'bearish', 'mixed', 'unknown')", name="ck_commodity_events_direction"),
        CheckConstraint("lag_bucket IN ('same_day', '1_7d', '7_30d', '30d_plus', 'unknown')", name="ck_commodity_events_lag_bucket"),
        CheckConstraint(
            "extraction_method IN ('manual_rule', 'keyword_rule', 'official_report_mapping', 'future_nlp', 'future_llm')",
            name="ck_commodity_events_method",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_commodity_events_confidence"),
        Index("ix_commodity_events_category_date", "event_category", "event_date"),
        Index("ix_commodity_events_family_date", "commodity_family", "event_date"),
        Index("ix_commodity_events_country_date", "country", "event_date"),
        Index("ix_commodity_events_published_at", "published_at"),
        Index("ix_commodity_events_direction", "direction_hint"),
        Index("ix_commodity_events_confidence", "confidence"),
        Index("ix_commodity_events_article_id", "news_article_id"),
        Index("ix_commodity_events_source_id", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    event_category: Mapped[str] = mapped_column(String(100), nullable=False)
    commodity_family: Mapped[str] = mapped_column(String(100), nullable=False)
    affected_products: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direction_hint: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    lag_bucket: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    news_article: Mapped[NewsArticle] = relationship()
    source: Mapped[Source] = relationship()


class DailyNewsFeature(Base, TimestampMixin):
    __tablename__ = "daily_news_features"
    __table_args__ = (
        UniqueConstraint("product_id", "feature_date", name="uq_daily_news_features_product_date"),
        Index("ix_daily_news_features_product_date", "product_id", "feature_date"),
        Index("ix_daily_news_features_family_date", "commodity_family", "feature_date"),
        Index("ix_daily_news_features_feature_date", "feature_date"),
        Index("ix_daily_news_features_as_of", "news_as_of_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    commodity_family: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_date: Mapped[date] = mapped_column(Date, nullable=False)
    news_count_1d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    news_count_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    news_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    event_count_1d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    event_count_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    event_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bullish_event_count_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bearish_event_count_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mixed_event_count_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    export_restriction_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    import_policy_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    war_logistics_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weather_disaster_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    crop_report_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    biofuel_policy_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    energy_shock_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    demand_shock_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    supply_chain_count_30d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sentiment_proxy_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    news_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    missing_flags: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    product: Mapped[Product] = relationship()


class ProductWeatherRegionWeight(Base, TimestampMixin):
    __tablename__ = "product_weather_region_weights"
    __table_args__ = (
        UniqueConstraint("product_id", "region_id", "role", "effective_from", name="uq_product_weather_region_weight"),
        CheckConstraint("weight >= 0", name="ck_product_weather_weight_nonnegative"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_product_weather_effective_range"),
        Index("ix_product_weather_product_active", "product_id", "is_active"),
        Index("ix_product_weather_region_active", "region_id", "is_active"),
        Index("ix_product_weather_effective", "effective_from", "effective_to"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("weather_regions.id"), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    product: Mapped[Product] = relationship()
    region: Mapped[WeatherRegion] = relationship()


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
    energy_brent_usd_per_barrel: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_wti_usd_per_barrel: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_henry_hub_usd_mmbtu: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_diesel_proxy_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_brent_delta_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_brent_delta_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_wti_delta_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_wti_delta_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_henry_hub_delta_1d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_henry_hub_delta_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_diesel_proxy_delta_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    energy_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    energy_brent_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    energy_wti_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    energy_henry_hub_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    energy_diesel_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    energy_missing_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    benchmark_soybean_oil_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_soybeans_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_palm_oil_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_maize_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_wheat_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_fertilizer_index_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_soybean_oil_delta_1m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_soybean_oil_delta_3m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_soybeans_delta_1m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_soybeans_delta_3m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_palm_oil_delta_1m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_palm_oil_delta_3m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_maize_delta_1m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_maize_delta_3m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_wheat_delta_1m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_wheat_delta_3m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_fertilizer_index_delta_1m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_fertilizer_index_delta_3m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_soybean_oil_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_soybeans_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_palm_oil_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_maize_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_wheat_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_fertilizer_index_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_missing_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    weather_temperature_7d_mean_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_temperature_30d_mean_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_temperature_min_7d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_temperature_max_7d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_precipitation_7d_sum_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_precipitation_14d_sum_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_precipitation_30d_sum_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_heat_stress_days_7d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_heat_stress_days_30d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_frost_days_7d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_frost_days_30d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_drought_proxy_30d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_growing_degree_days_7d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_growing_degree_days_30d_weighted: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    weather_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weather_regions_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    weather_missing_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    calendar_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_week_of_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_day_of_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calendar_is_month_start: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    calendar_is_month_end: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    calendar_is_quarter_start: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    calendar_is_quarter_end: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    calendar_sin_day_of_year: Mapped[float | None] = mapped_column(Float, nullable=True)
    calendar_cos_day_of_year: Mapped[float | None] = mapped_column(Float, nullable=True)
    calendar_sin_month: Mapped[float | None] = mapped_column(Float, nullable=True)
    calendar_cos_month: Mapped[float | None] = mapped_column(Float, nullable=True)
    calendar_season: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
