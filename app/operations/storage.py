from __future__ import annotations

from pathlib import Path


def directory_size_bytes(path: Path | str) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def rotated_log_candidates(log_dir: Path | str) -> list[dict[str, object]]:
    root = Path(log_dir)
    if not root.exists():
        return []
    candidates = []
    for item in sorted(root.glob("app.log.*")):
        if item.is_file():
            try:
                stat = item.stat()
            except OSError:
                continue
            candidates.append(
                {
                    "path": str(item),
                    "bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
    return candidates

