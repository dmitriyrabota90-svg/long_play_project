"""expand commodity benchmarks

Revision ID: 0010_commodity_benchmarks
Revises: 0009_energy_features
Create Date: 2026-06-09 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_commodity_benchmarks"
down_revision = "0009_energy_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("commodity_benchmarks", sa.Column("collector_run_id", sa.Integer(), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("external_id", sa.String(length=255), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("benchmark_name", sa.String(length=255), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("benchmark_category", sa.String(length=100), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("commodity_family", sa.String(length=100), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("geography", sa.String(length=100), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("frequency", sa.String(length=32), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("period_start", sa.Date(), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("period_end", sa.Date(), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("normalized_value", sa.Numeric(18, 8), nullable=True))
    op.add_column("commodity_benchmarks", sa.Column("normalized_currency", sa.String(length=16), nullable=True))
    op.add_column("commodity_benchmarks", sa.Column("normalized_unit", sa.String(length=100), nullable=True))
    op.add_column("commodity_benchmarks", sa.Column("source_record_hash", sa.String(length=64), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("source_payload_hash", sa.String(length=64), nullable=False))
    op.add_column("commodity_benchmarks", sa.Column("metadata_json", sa.JSON(), nullable=True))
    op.add_column(
        "commodity_benchmarks",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.alter_column("commodity_benchmarks", "value", existing_type=sa.Numeric(18, 6), type_=sa.Numeric(18, 8))
    op.alter_column(
        "commodity_benchmarks",
        "currency",
        existing_type=sa.String(length=16),
        nullable=True,
        existing_nullable=False,
    )
    op.create_foreign_key(
        "fk_comm_bench_collector_run_id",
        "commodity_benchmarks",
        "collector_runs",
        ["collector_run_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_comm_bench_source_code_freq_period",
        "commodity_benchmarks",
        ["source_id", "benchmark_code", "frequency", "period_start", "period_end"],
    )
    op.create_check_constraint("ck_comm_bench_period_order", "commodity_benchmarks", "period_end >= period_start")
    op.create_check_constraint(
        "ck_comm_bench_frequency",
        "commodity_benchmarks",
        "frequency IN ('daily', 'weekly', 'monthly')",
    )
    op.create_index(
        "ix_comm_bench_source_code_period",
        "commodity_benchmarks",
        ["source_id", "benchmark_code", "period_start", "period_end"],
    )
    op.create_index("ix_comm_bench_code_observed", "commodity_benchmarks", ["benchmark_code", "observed_at"])
    op.create_index("ix_comm_bench_category_observed", "commodity_benchmarks", ["benchmark_category", "observed_at"])
    op.create_index("ix_comm_bench_family_observed", "commodity_benchmarks", ["commodity_family", "observed_at"])
    op.create_index("ix_comm_bench_fetched_at", "commodity_benchmarks", ["fetched_at"])
    op.create_index("ix_comm_bench_raw_response_id", "commodity_benchmarks", ["raw_response_id"])
    op.create_index("ix_comm_bench_collector_run_id", "commodity_benchmarks", ["collector_run_id"])
    op.create_index("ix_comm_bench_source_record_hash", "commodity_benchmarks", ["source_record_hash"])


def downgrade() -> None:
    op.drop_index("ix_comm_bench_source_record_hash", table_name="commodity_benchmarks")
    op.drop_index("ix_comm_bench_collector_run_id", table_name="commodity_benchmarks")
    op.drop_index("ix_comm_bench_raw_response_id", table_name="commodity_benchmarks")
    op.drop_index("ix_comm_bench_fetched_at", table_name="commodity_benchmarks")
    op.drop_index("ix_comm_bench_family_observed", table_name="commodity_benchmarks")
    op.drop_index("ix_comm_bench_category_observed", table_name="commodity_benchmarks")
    op.drop_index("ix_comm_bench_code_observed", table_name="commodity_benchmarks")
    op.drop_index("ix_comm_bench_source_code_period", table_name="commodity_benchmarks")
    op.drop_constraint("ck_comm_bench_frequency", "commodity_benchmarks", type_="check")
    op.drop_constraint("ck_comm_bench_period_order", "commodity_benchmarks", type_="check")
    op.drop_constraint("uq_comm_bench_source_code_freq_period", "commodity_benchmarks", type_="unique")
    op.drop_constraint("fk_comm_bench_collector_run_id", "commodity_benchmarks", type_="foreignkey")
    op.alter_column(
        "commodity_benchmarks",
        "currency",
        existing_type=sa.String(length=16),
        nullable=False,
        existing_nullable=True,
    )
    op.alter_column("commodity_benchmarks", "value", existing_type=sa.Numeric(18, 8), type_=sa.Numeric(18, 6))
    op.drop_column("commodity_benchmarks", "updated_at")
    op.drop_column("commodity_benchmarks", "metadata_json")
    op.drop_column("commodity_benchmarks", "source_payload_hash")
    op.drop_column("commodity_benchmarks", "source_record_hash")
    op.drop_column("commodity_benchmarks", "normalized_unit")
    op.drop_column("commodity_benchmarks", "normalized_currency")
    op.drop_column("commodity_benchmarks", "normalized_value")
    op.drop_column("commodity_benchmarks", "fetched_at")
    op.drop_column("commodity_benchmarks", "period_end")
    op.drop_column("commodity_benchmarks", "period_start")
    op.drop_column("commodity_benchmarks", "frequency")
    op.drop_column("commodity_benchmarks", "geography")
    op.drop_column("commodity_benchmarks", "commodity_family")
    op.drop_column("commodity_benchmarks", "benchmark_category")
    op.drop_column("commodity_benchmarks", "benchmark_name")
    op.drop_column("commodity_benchmarks", "external_id")
    op.drop_column("commodity_benchmarks", "collector_run_id")
