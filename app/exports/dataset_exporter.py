from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import get_settings
from app.exports.manifest import write_manifest


def create_empty_export_manifest(export_dir: Path | str | None = None) -> dict[str, Any]:
    settings = get_settings()
    created_at = datetime.now(timezone.utc)
    export_version = created_at.strftime("%Y%m%dT%H%M%SZ")
    base_dir = Path(export_dir) if export_dir is not None else Path(settings.export_data_dir)
    target_dir = base_dir / export_version

    manifest = {
        "app_version": settings.app_version,
        "created_at": created_at.isoformat(),
        "export_version": export_version,
        "status": "skeleton",
        "row_count": 0,
        "files": [],
        "message": "Dataset export skeleton. Real dataset export will be added in a later phase.",
    }
    manifest_path = write_manifest(target_dir / "dataset_manifest.json", manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest

