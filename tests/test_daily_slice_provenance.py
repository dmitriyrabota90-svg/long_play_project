from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CollectorRun, DailySliceRevision, PriceObservation, Product, RawResponse, Source
from app.exports.daily_slice_evidence_export import export_daily_slice_evidence
from app.features.daily import build_daily_features
from app.features.daily_slice_provenance import confirm_readiness_after_commit


AUDIT_PATH = Path("experiments/applied_target_audit_v1/src/run_audit.py")


def load_audit():
    if not AUDIT_PATH.is_file():
        pytest.skip("optional local applied-target audit is not in the release source")
    spec = importlib.util.spec_from_file_location("provenance_audit", AUDIT_PATH)
    assert spec and spec.loader
    audit = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = audit
    spec.loader.exec_module(audit)
    return audit


def factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def seed_price(session, *, day: date, value: str, hour: int = 15, published_at: datetime | None = None) -> PriceObservation:
    product = session.scalar(select(Product).where(Product.code == "soybean_oil"))
    if product is None:
        product = Product(code="soybean_oil", name="Soy", category="oil", unit="metric_ton", currency_default="CNY")
        source = Source(code="current_price_source", name="current", source_type="price")
        session.add_all([product, source])
        session.flush()
    else:
        source = session.scalar(select(Source).where(Source.code == "current_price_source"))
    run = CollectorRun(collector_name="test", started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc), status="success")
    session.add(run)
    session.flush()
    fetched = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=hour)
    raw = RawResponse(source_id=source.id, collector_run_id=run.id, fetched_at=fetched, url="https://example.test", method="GET", status_code=200, storage_path=f"raw/{day}", sha256=(str(run.id) * 64)[:64], bytes_size=1, parser_version="test")
    session.add(raw)
    session.flush()
    observation = PriceObservation(product_id=product.id, source_id=source.id, raw_response_id=raw.id, observed_at=fetched, published_at=published_at, price=Decimal(value), currency="CNY", unit="metric_ton", source_record_hash=f"{day}-{value}-{run.id}")
    session.add(observation)
    session.flush()
    return observation


def test_selected_price_and_revision_are_from_same_selection_and_rebuild_preserves_prior_version():
    Session = factory()
    with Session() as session:
        first = seed_price(session, day=date(2026, 5, 20), value="10", hour=14)
        later = seed_price(session, day=date(2026, 5, 20), value="11", hour=15)
        result_one = build_daily_features(session=session)
        session.commit()
        revision_one = session.get(DailySliceRevision, result_one.slice_revision_ids[0])
        assert revision_one.selected_price_observation_id == later.id
        assert revision_one.price_value == Decimal("11.000000")
        assert revision_one.selected_raw_response_id == later.raw_response_id
        first_hash = revision_one.content_sha256
        result_two = build_daily_features(session=session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 20))
        session.commit()
        revision_two = session.get(DailySliceRevision, result_two.slice_revision_ids[0])
        assert revision_two.id != revision_one.id
        assert session.get(DailySliceRevision, revision_one.id).content_sha256 == first_hash


def test_rollback_and_confirmation_failure_do_not_create_false_ready():
    Session = factory()
    with Session() as session:
        seed_price(session, day=date(2026, 5, 20), value="10")
        build_daily_features(session=session)
        session.rollback()
        assert session.scalars(select(DailySliceRevision)).all() == []
        seed_price(session, day=date(2026, 5, 20), value="10")
        result = build_daily_features(session=session)
        session.commit()
        revision = session.get(DailySliceRevision, result.slice_revision_ids[0])
        assert revision.readiness_confirmed_at is None
    with Session() as session:
        confirmed = confirm_readiness_after_commit(session, revision_ids=result.slice_revision_ids, confirmed_at=datetime(2026, 5, 20, 16, tzinfo=timezone.utc))
        session.commit()
        assert confirmed == result.slice_revision_ids
    with Session() as session:
        assert confirm_readiness_after_commit(session, revision_ids=result.slice_revision_ids) == []


def test_evidence_round_trip_and_unknown_freshness_stay_unverified(tmp_path: Path):
    Session = factory()
    with Session() as session:
        seed_price(session, day=date(2026, 5, 20), value="10")
        seed_price(session, day=date(2026, 5, 21), value="11")
        result = build_daily_features(session=session)
        session.commit()
    with Session() as session:
        confirm_readiness_after_commit(session, revision_ids=result.slice_revision_ids, confirmed_at=datetime(2026, 5, 20, 16, tzinfo=timezone.utc))
        session.commit()
    with Session() as session:
        exported = export_daily_slice_evidence(session=session, output_dir=tmp_path)
    payload = json.loads(Path(exported.evidence_path).read_text())
    assert payload["schema_version"] == "daily_slice_evidence_export_v1"
    assert payload["records"][0]["price_value"] == "10.000000"
    assert payload["records"][0]["freshness_status"] == "UNKNOWN_NO_PROVIDER_TIMESTAMP"


def test_adapter_allows_only_explicit_provider_timestamp_evidence():
    audit = load_audit()
    cutoff = "2026-05-20T16:00:00+00:00"
    evidence = {date(2026, 5, 20): [{"product_code": "soybean_oil", "source_code": "current_price_source", "external_code": "JO_165951", "price_value": "10", "observed_at": "2026-05-20T15:00:00+00:00", "readiness_confirmed_at": cutoff, "selected_price_observation_id": 1}], date(2026, 5, 21): [{"product_code": "soybean_oil", "source_code": "current_price_source", "external_code": "JO_165951", "price_value": "11", "provider_published_at": "2026-05-20T17:00:00+00:00", "selected_price_observation_id": 2}]}
    rows = {date(2026, 5, 20): [audit.SnapshotRow(date(2026, 5, 20), Decimal("10"), "2026-05-20T15:00:00+00:00", "a")], date(2026, 5, 21): [audit.SnapshotRow(date(2026, 5, 21), Decimal("11"), "2026-05-21T15:00:00+00:00", "b")]}
    result = audit.audit_pairs(rows, evidence)
    assert result[0]["eligibility_status"] == "ELIGIBLE"
    evidence[date(2026, 5, 21)][0]["provider_published_at"] = None
    assert audit.audit_pairs(rows, evidence)[0]["eligibility_status"] == "UNVERIFIED"


def test_postgres_lifecycle_with_explicit_disposable_dsn(tmp_path: Path):
    audit = load_audit()
    dsn = os.environ.get("CDB_PROVENANCE_TEST_DSN")
    if not dsn:
        raise RuntimeError("CDB_PROVENANCE_TEST_DSN is required; refusing any default database")
    if "@cdb-provenance-v1-pg:5432/provenance_test" not in dsn:
        raise RuntimeError("refusing non-disposable provenance test DSN")
    engine = create_engine(dsn, future=True)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        seed_price(session, day=date(2026, 5, 20), value="10", published_at=datetime(2026, 5, 20, 15, tzinfo=timezone.utc))
        seed_price(session, day=date(2026, 5, 21), value="11", published_at=datetime(2026, 5, 20, 17, tzinfo=timezone.utc))
        seed_price(session, day=date(2026, 5, 22), value="9", published_at=datetime(2026, 5, 21, 17, tzinfo=timezone.utc))
        seed_price(session, day=date(2026, 5, 23), value="9", published_at=datetime(2026, 5, 22, 17, tzinfo=timezone.utc))
        result = build_daily_features(session=session)
        session.commit()
    with Session() as session:
        revisions = session.scalars(select(DailySliceRevision).where(DailySliceRevision.id.in_(result.slice_revision_ids)).order_by(DailySliceRevision.feature_date)).all()
        for revision in revisions:
            confirm_readiness_after_commit(session, revision_ids=[revision.id], confirmed_at=datetime.combine(revision.feature_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=16))
        session.commit()
    with Session() as session:
        exported = export_daily_slice_evidence(session=session, output_dir=tmp_path)
    evidence = audit.load_evidence(Path(exported.evidence_path))
    rows = {
        date(2026, 5, 20): [audit.SnapshotRow(date(2026, 5, 20), Decimal("10"), "2026-05-20T15:00:00+00:00", "synthetic-1")],
        date(2026, 5, 21): [audit.SnapshotRow(date(2026, 5, 21), Decimal("11"), "2026-05-21T15:00:00+00:00", "synthetic-2")],
    }
    rows.update({
        date(2026, 5, 22): [audit.SnapshotRow(date(2026, 5, 22), Decimal("9"), "2026-05-22T15:00:00+00:00", "synthetic-3")],
        date(2026, 5, 23): [audit.SnapshotRow(date(2026, 5, 23), Decimal("9"), "2026-05-23T15:00:00+00:00", "synthetic-4")],
    })
    pairs = audit.audit_pairs(rows, evidence)
    audit.complete_eligible_labels(pairs)
    assert [pair["direction"] for pair in pairs[:3]] == ["UP", "DOWN", "UNCHANGED"]
    stale = evidence[date(2026, 5, 21)][0]
    stale["provider_published_at"] = "2026-05-20T15:00:00+00:00"
    assert audit.audit_pairs(rows, evidence)[0]["eligibility_status"] == "UNVERIFIED"
