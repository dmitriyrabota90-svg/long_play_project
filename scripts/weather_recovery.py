from __future__ import annotations

import argparse
import json
from datetime import date

from app.collectors.weather.recovery import WeatherRecoveryService


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan or run bounded Open-Meteo recovery")
    parser.add_argument("--mode", choices=("catchup", "regular"), default="catchup")
    parser.add_argument("--from-date", type=date.fromisoformat)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = WeatherRecoveryService().run(mode=args.mode, dry_run=args.dry_run, lower_bound=args.from_date)
    print(json.dumps({"status": result.status, "requests_completed": result.requests_completed,
                      "observations_written": result.observations_written, "observations_skipped": result.observations_skipped,
                      "feature_rows_written": result.feature_rows_written, "errors": result.errors,
                      "plan": {"safe_end": result.plan.safe_end.isoformat(), "lower_bound": result.plan.lower_bound.isoformat(),
                               "requests_planned": result.plan.requests_planned, "backlog_days": result.plan.backlog_days,
                               "budget_exhausted": result.plan.budget_exhausted,
                               "chunks": [{"region_code": chunk.region_code, "from_date": chunk.from_date.isoformat(), "to_date": chunk.to_date.isoformat(), "reason": chunk.reason} for chunk in result.plan.chunks]}}, default=str))


if __name__ == "__main__":
    main()
