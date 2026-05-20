from datetime import datetime, timezone
from pathlib import Path

from app.storage.hashes import sha256_bytes
from app.storage.raw_store import RawStore


def test_raw_store_saves_bytes_and_hash(tmp_path: Path) -> None:
    payload = b'{"hello":"world"}'
    fetched_at = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    store = RawStore(base_dir=tmp_path / "raw")

    result = store.save_bytes(
        source_code="test_source",
        collector_run_id=42,
        payload=payload,
        fetched_at=fetched_at,
        extension="json",
    )

    assert result.sha256 == sha256_bytes(payload)
    assert result.bytes_size == len(payload)
    assert Path(result.storage_path).exists()
    assert Path(result.storage_path).read_bytes() == payload

