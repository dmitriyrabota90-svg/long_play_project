from __future__ import annotations

from typing import Any

from app.config.settings import Settings, get_settings
from app.operations.storage import directory_size_bytes, rotated_log_candidates


def build_cleanup_plan(*, settings: Settings | None = None, dry_run: bool = True) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "dry_run": dry_run,
        "actions_executed": [],
        "policy": {
            "raw_data_deleted": False,
            "exports_deleted": False,
            "note": "Raw data and exports are never deleted by this cleanup skeleton.",
        },
        "sizes": {
            "logs_bytes": directory_size_bytes(settings.log_dir),
            "raw_bytes": directory_size_bytes(settings.raw_data_dir),
            "exports_bytes": directory_size_bytes(settings.export_data_dir),
        },
        "rotated_log_candidates": rotated_log_candidates(settings.log_dir),
        "suggested_actions": [
            "Review rotated logs before deleting anything.",
            "Keep raw data and exports under backup policy, not cleanup policy.",
        ],
    }

