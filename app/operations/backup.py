from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import Settings, get_settings


def build_backup_plan(*, settings: Settings | None = None, dry_run: bool = True) -> dict[str, Any]:
    settings = settings or get_settings()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = Path("backups") / timestamp
    pg_dump_path = backup_root / "postgres" / "commodity_dataset.dump"
    raw_backup_path = backup_root / "raw"
    exports_backup_path = backup_root / "exports"

    return {
        "dry_run": dry_run,
        "actions_executed": [],
        "postgres": {
            "database_url_setting": "DATABASE_URL",
            "command": f'pg_dump --format=custom --file "{pg_dump_path}" "$DATABASE_URL"',
            "target_path": str(pg_dump_path),
        },
        "raw_data": {
            "source_path": str(settings.raw_data_dir),
            "target_path": str(raw_backup_path),
            "note": "Copy raw data immutably; do not delete source raw files.",
        },
        "exports": {
            "source_path": str(settings.export_data_dir),
            "target_path": str(exports_backup_path),
            "note": "Copy exported datasets and manifests.",
        },
        "verification": [
            "Verify pg_dump exit code.",
            "Verify raw/export file counts and checksums.",
            "Record backup timestamp and storage location.",
        ],
    }

