from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


class CollectorError(Exception):
    """Raised when a collector cannot complete safely."""


@dataclass(frozen=True)
class CollectorResult:
    source_code: str
    collector_name: str
    parser_version: str
    started_at: datetime
    finished_at: datetime
    status: str
    run_id: int | None = None
    records_found: int = 0
    records_written: int = 0
    raw_response_ids: list[int] = field(default_factory=list)
    error_message: str | None = None
    errors_count: int = 0


class BaseCollector:
    source_code: str
    collector_name: str
    parser_version: str = "0.1.0"

    def __init__(self, *, source_code: str | None = None, collector_name: str | None = None) -> None:
        if source_code is not None:
            self.source_code = source_code
        if collector_name is not None:
            self.collector_name = collector_name
        if not getattr(self, "source_code", None):
            raise ValueError("source_code must be set")
        if not getattr(self, "collector_name", None):
            raise ValueError("collector_name must be set")

    def run(self) -> CollectorResult:
        started_at = datetime.now(timezone.utc)
        finished_at = datetime.now(timezone.utc)
        return CollectorResult(
            source_code=self.source_code,
            collector_name=self.collector_name,
            parser_version=self.parser_version,
            started_at=started_at,
            finished_at=finished_at,
            status="not_implemented",
            error_message="Real collectors will be added in later phases.",
        )
