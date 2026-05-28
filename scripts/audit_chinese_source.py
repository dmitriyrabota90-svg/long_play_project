from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.discovery.chinese_source_audit import build_audit, write_audit_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only audit of Cngold/Jijinhao Chinese commodity source.")
    parser.add_argument("--mode", choices=("inventory", "check-known", "search-keywords"), default="inventory")
    parser.add_argument("--output-dir", default="diagnostics/chinese_source_audit")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    audit = build_audit(args.mode, timeout=args.timeout)
    write_audit_outputs(audit, Path(args.output_dir))

    print(f"source={audit.source}")
    print(f"mode={audit.mode}")
    print(f"known_endpoints={len(audit.known_endpoints)}")
    print(f"known_instruments={len(audit.known_instruments)}")
    print(f"product_candidates={len(audit.product_candidates)}")
    print(f"data_capabilities={len(audit.data_capabilities)}")
    print(f"probes={len(audit.probes)}")
    if args.mode == "search-keywords":
        print("search_keywords_status=not_supported")
    for probe in audit.probes:
        print(f"probe={probe.name} status={probe.status} http_status={probe.http_status} bytes_size={probe.bytes_size}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
