from __future__ import annotations

import os
import sys
import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.logging import setup_logging
from app.operations.backup import build_backup_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Show backup plan. Defaults to dry-run.")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()

    setup_logging()
    print(json.dumps(build_backup_plan(dry_run=args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
