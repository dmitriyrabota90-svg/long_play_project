from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import get_settings
from app.storage.hashes import sha256_bytes


@dataclass(frozen=True)
class RawStoreResult:
    storage_path: str
    sha256: str
    bytes_size: int


class RawStore:
    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path(get_settings().raw_data_dir)

    def save_bytes(
        self,
        *,
        source_code: str,
        collector_run_id: int | str,
        payload: bytes,
        fetched_at: datetime | None = None,
        extension: str | None = None,
        content_type: str | None = None,
    ) -> RawStoreResult:
        fetched_at = _ensure_utc(fetched_at or datetime.now(timezone.utc))
        digest = sha256_bytes(payload)
        ext = _normalize_extension(extension or _extension_from_content_type(content_type))
        safe_source_code = _safe_path_part(source_code)
        safe_run_id = _safe_path_part(str(collector_run_id))

        target_dir = (
            self.base_dir
            / safe_source_code
            / f"{fetched_at:%Y}"
            / f"{fetched_at:%m}"
            / f"{fetched_at:%d}"
            / safe_run_id
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{digest}.{ext}"

        if not target_path.exists():
            target_path.write_bytes(payload)

        return RawStoreResult(
            storage_path=str(target_path),
            sha256=digest,
            bytes_size=len(payload),
        )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_path_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "unknown"


def _normalize_extension(extension: str | None) -> str:
    if not extension:
        return "bin"
    return extension.lower().lstrip(".") or "bin"


def _extension_from_content_type(content_type: str | None) -> str:
    if not content_type:
        return "bin"
    content_type = content_type.split(";")[0].strip().lower()
    mapping = {
        "application/json": "json",
        "text/json": "json",
        "text/html": "html",
        "application/xhtml+xml": "html",
        "text/csv": "csv",
        "application/csv": "csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.ms-excel": "xls",
    }
    return mapping.get(content_type, "bin")

