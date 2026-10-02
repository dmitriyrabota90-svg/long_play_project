"""Immutable evidence for a daily feature version and its selected price."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.prices.current_price_config import CURRENT_PRICE_INSTRUMENTS
from app.db.models import DailyProductFeature, DailySliceBuildRun, DailySliceRevision, PriceObservation, Product, Source
from app.storage.hashes import stable_json_hash


SCHEMA_VERSION = "daily_slice_evidence_v1"


class DailySliceProvenanceError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_build_run(session: Session, *, build_mode: str, feature_builder_version: str, started_at: datetime) -> DailySliceBuildRun:
    run = DailySliceBuildRun(build_mode=build_mode, feature_builder_version=feature_builder_version, started_at=started_at)
    session.add(run)
    session.flush()
    return run


def record_slice_revision(
    session: Session,
    *,
    build_run: DailySliceBuildRun,
    feature: DailyProductFeature,
    selected_observation: PriceObservation,
    content: dict[str, Any],
) -> DailySliceRevision:
    """Capture the same observation object used by the price-last selection."""
    if feature.price_last != selected_observation.price:
        raise DailySliceProvenanceError("selected observation price does not match daily price_last")
    product = session.get(Product, feature.product_id)
    source = session.get(Source, selected_observation.source_id)
    if product is None or source is None:
        raise DailySliceProvenanceError("selected observation product/source is missing")
    if selected_observation.product_id != feature.product_id:
        raise DailySliceProvenanceError("selected observation product does not match daily slice")
    raw = selected_observation.raw_response
    external_code = next(
        (item.external_code for item in CURRENT_PRICE_INSTRUMENTS if item.product_code == product.code and source.code == "current_price_source"),
        None,
    )
    immutable_content = {
        "schema_version": SCHEMA_VERSION,
        "feature": content,
        "selected_price_source_time": selected_observation.source_time_metadata_json,
    }
    revision = DailySliceRevision(
        build_run_id=build_run.id,
        daily_product_feature_id=feature.id,
        product_id=feature.product_id,
        source_id=source.id,
        feature_date=feature.feature_date,
        schema_version=SCHEMA_VERSION,
        content_sha256=stable_json_hash(immutable_content),
        slice_content_json=immutable_content,
        logical_data_cutoff=feature.as_of_at,
        selected_price_observation_id=selected_observation.id,
        selected_raw_response_id=raw.id if raw is not None else None,
        product_code=product.code,
        source_code=source.code,
        external_code=external_code,
        price_value=selected_observation.price,
        price_currency=selected_observation.currency,
        price_unit=selected_observation.unit,
        observed_at=selected_observation.observed_at,
        fetched_at=raw.fetched_at if raw is not None else None,
        observation_created_at=selected_observation.created_at,
        collection_slot=selected_observation.collection_slot,
        provider_published_at=selected_observation.published_at,
        raw_sha256=raw.sha256 if raw is not None else None,
        source_record_hash=selected_observation.source_record_hash,
    )
    session.add(revision)
    session.flush()
    return revision


def confirm_readiness_after_commit(session: Session, *, revision_ids: list[int], confirmed_at: datetime | None = None) -> list[int]:
    """Idempotently confirm only revisions already committed by a prior transaction."""
    if not revision_ids:
        return []
    revisions = session.scalars(select(DailySliceRevision).where(DailySliceRevision.id.in_(revision_ids))).all()
    if len(revisions) != len(set(revision_ids)):
        raise DailySliceProvenanceError("cannot confirm a revision absent from the committed database")
    timestamp = confirmed_at or utc_now()
    confirmed: list[int] = []
    for revision in revisions:
        if revision.readiness_confirmed_at is None:
            revision.readiness_confirmed_at = timestamp
            confirmed.append(revision.id)
    session.flush()
    return confirmed
