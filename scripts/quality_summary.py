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
from app.monitoring.quality_summary import build_quality_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Print data quality checks summary.")
    parser.add_argument("--limit", type=int, default=20, help="Number of latest problematic checks to include.")
    args = parser.parse_args()

    setup_logging()
    summary = build_quality_summary(limit=args.limit)
    if summary["problematic_checks"] == 0:
        summary["message"] = "quality checks ok"
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
