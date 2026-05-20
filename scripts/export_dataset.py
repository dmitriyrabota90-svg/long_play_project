from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.logging import setup_logging
from app.exports.dataset_exporter import create_empty_export_manifest


def main() -> None:
    setup_logging()
    manifest = create_empty_export_manifest()
    print(f"Created skeleton dataset manifest: {manifest['manifest_path']}")


if __name__ == "__main__":
    main()
