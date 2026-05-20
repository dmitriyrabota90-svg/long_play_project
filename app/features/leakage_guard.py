from __future__ import annotations

from datetime import datetime, timezone


class DataLeakageError(ValueError):
    """Raised when a feature attempts to use information from the future."""


def ensure_available_as_of(*, data_available_at: datetime, as_of_at: datetime, field_name: str) -> None:
    data_available_at = _to_utc(data_available_at)
    as_of_at = _to_utc(as_of_at)
    if data_available_at > as_of_at:
        raise DataLeakageError(
            f"{field_name} is not available as of {as_of_at.isoformat()}: "
            f"data timestamp is {data_available_at.isoformat()}"
        )


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

