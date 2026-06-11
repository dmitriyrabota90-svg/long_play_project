from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.discovery.supply_demand_source_audit import (
    build_audit,
    count_by_status,
    recommended_first_source,
    write_audit_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostics-only audit of supply-demand / production-stocks source candidates."
    )
    parser.add_argument("--output-dir", default="diagnostics/supply_demand_source_audit")
    parser.add_argument(
        "--live-probe",
        action="store_true",
        help="Reserved for a later bounded HTTP probe. Phase 6.7A uses the static registry only.",
    )
    args = parser.parse_args()

    audit = build_audit(live_probe=args.live_probe)
    write_audit_outputs(audit, Path(args.output_dir))
    first_source = recommended_first_source(audit.candidates)
    counts = count_by_status(audit.candidates)

    ready_count = counts.get("ready_to_probe", 0) + counts.get("ready_to_prototype", 0)
    manual_count = counts.get("needs_manual_check", 0)
    paid_or_complex_count = counts.get("paid_later", 0) + counts.get("high_complexity", 0)

    print("phase=6.7A")
    print("mode=inventory")
    print(f"live_probing={audit.live_probing}")
    print(f"recommended_first_source={first_source.source_name}")
    print(f"recommended_first_prototype_scope={audit.recommended_first_prototype_scope}")
    print(f"metric_taxonomy={len(audit.metric_taxonomy)}")
    print(f"commodity_metric_mappings={len(audit.commodity_metric_mappings)}")
    print(f"candidates={len(audit.candidates)}")
    print(f"ready_to_probe_or_prototype={ready_count}")
    print(f"needs_manual_check={manual_count}")
    print(f"paid_later_or_high_complexity={paid_or_complex_count}")
    for status in sorted(counts):
        print(f"{status}={counts[status]}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
