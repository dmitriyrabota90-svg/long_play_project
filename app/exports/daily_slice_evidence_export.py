"""Explicit sidecar export for immutable daily-slice provenance revisions."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DailySliceRevision
from app.db.session import session_scope
from app.storage.hashes import sha256_bytes, stable_json_hash


SCHEMA_VERSION = "daily_slice_evidence_export_v1"


@dataclass(frozen=True)
class DailySliceEvidenceExportResult:
    evidence_path: str
    manifest_path: str
    row_count: int
    sha256: str


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if value is not None else None


def export_daily_slice_evidence(
    *,
    output_dir: Path | str,
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session | None = None,
) -> DailySliceEvidenceExportResult:
    if session is None:
        with session_scope() as scoped_session:
            return export_daily_slice_evidence(output_dir=output_dir, from_date=from_date, to_date=to_date, session=scoped_session)
    if from_date and to_date and from_date > to_date:
        raise ValueError("from_date must be on or before to_date")
    statement = select(DailySliceRevision).order_by(DailySliceRevision.feature_date, DailySliceRevision.id)
    if from_date:
        statement = statement.where(DailySliceRevision.feature_date >= from_date)
    if to_date:
        statement = statement.where(DailySliceRevision.feature_date <= to_date)
    revisions = session.scalars(statement).all()
    records = [_record(row) for row in revisions]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc)
    base = f"daily_slice_evidence_v1_{created_at.strftime('%Y%m%d_%H%M%S')}"
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": created_at.isoformat(),
        "scope": {"from_date": from_date.isoformat() if from_date else None, "to_date": to_date.isoformat() if to_date else None, "revision_count": len(records)},
        "records": records,
    }
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_iso).encode("utf-8")
    evidence_path = output / f"{base}.json"
    evidence_path.write_bytes(payload + b"\n")
    digest = sha256_bytes(evidence_path.read_bytes())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": created_at.isoformat(),
        "files": [{"path": str(evidence_path), "sha256": digest, "bytes_size": evidence_path.stat().st_size}],
        "input_content_sha256": stable_json_hash([item["content_sha256"] for item in records]),
        "scope": evidence["scope"],
        "timing_note": "exported_at is not historical readiness evidence",
    }
    manifest_path = output / f"{base}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return DailySliceEvidenceExportResult(str(evidence_path), str(manifest_path), len(records), digest)


def _record(row: DailySliceRevision) -> dict[str, Any]:
    return {
        "slice_revision_id": row.id,
        "build_run_id": row.build_run_id,
        "schema_version": row.schema_version,
        "content_sha256": row.content_sha256,
        "slice_content": row.slice_content_json,
        "selected_price_source_time": row.slice_content_json.get("selected_price_source_time"),
        "product_code": row.product_code,
        "source_code": row.source_code,
        "external_code": row.external_code,
        "feature_date": _iso(row.feature_date),
        "logical_data_cutoff": _iso(row.logical_data_cutoff),
        "readiness_confirmed_at": _iso(row.readiness_confirmed_at),
        "selected_price_observation_id": row.selected_price_observation_id,
        "selected_raw_response_id": row.selected_raw_response_id,
        "price_value": _iso(row.price_value),
        "price_currency": row.price_currency,
        "price_unit": row.price_unit,
        "observed_at": _iso(row.observed_at),
        "fetched_at": _iso(row.fetched_at),
        "observation_created_at": _iso(row.observation_created_at),
        "collection_slot": _iso(row.collection_slot),
        "provider_published_at": _iso(row.provider_published_at),
        "raw_sha256": row.raw_sha256,
        "source_record_hash": row.source_record_hash,
        "freshness_status": "CONFIRMED_PROVIDER_TIMESTAMP" if row.provider_published_at else "UNKNOWN_NO_PROVIDER_TIMESTAMP",
    }
