from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.logging import setup_logging
from app.monitoring.operational_report import build_operational_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Print operational report.")
    parser.add_argument("--freshness-hours", type=int, default=24)
    args = parser.parse_args()

    setup_logging()
    print(json.dumps(build_operational_report(freshness_hours=args.freshness_hours), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

