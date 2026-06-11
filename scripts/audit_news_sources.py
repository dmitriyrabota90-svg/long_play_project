from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.discovery.news_source_audit import (
    build_audit,
    count_by_status,
    recommended_first_source,
    write_audit_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostics-only audit of news and event source candidates.")
    parser.add_argument("--output-dir", default="diagnostics/news_source_audit")
    parser.add_argument(
        "--live-probe",
        action="store_true",
        help="Reserved for a later bounded HTTP probe. Phase 6.4A uses the static registry only.",
    )
    args = parser.parse_args()

    audit = build_audit(live_probe=args.live_probe)
    write_audit_outputs(audit, Path(args.output_dir))
    first_source = recommended_first_source(audit.candidates)
    counts = count_by_status(audit.candidates)

    print("phase=6.4A")
    print("mode=inventory")
    print(f"live_probing={audit.live_probing}")
    print(f"recommended_first_source={first_source.source_name}")
    print(f"recommended_first_event_layer={audit.recommended_first_event_layer}")
    print(f"event_categories={len(audit.event_taxonomy)}")
    print(f"candidates={len(audit.candidates)}")
    for status in sorted(counts):
        print(f"{status}={counts[status]}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
