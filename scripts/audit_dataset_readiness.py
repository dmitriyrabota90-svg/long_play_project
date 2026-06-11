from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.audits.dataset_readiness import run_dataset_readiness_audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit ML-ready daily_features documentation locally.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("diagnostics/dataset_readiness"),
        help="Diagnostics output directory.",
    )
    args = parser.parse_args()

    audit = run_dataset_readiness_audit(project_root=PROJECT_ROOT, output_dir=args.output_dir)
    print(f"status={audit.status}")
    print(f"docs_checked={audit.docs_checked}")
    print(f"export_columns_count={audit.export_columns_count}")
    print(f"missing_docs={','.join(audit.missing_docs)}")
    print(f"missing_feature_groups={','.join(audit.missing_feature_groups)}")
    print(f"warnings_count={audit.warnings_count}")
    print(f"recommendation={audit.recommendation}")


if __name__ == "__main__":
    main()
