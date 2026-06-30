#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT_LINES = 200

AREA_CONTEXT: dict[str, dict[str, tuple[str, ...]]] = {
    "supply-demand": {
        "docs": (
            "docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md",
            "docs/SUPPLY_DEMAND_COUNTRY_AGGREGATION_DESIGN.md",
            "docs/SUPPLY_DEMAND_DESIGN.md",
            "docs/LEAKAGE_AND_ASOF_AUDIT.md",
        ),
        "code": (
            "app/features/supply_demand_basket_config.py",
            "app/features/supply_demand_daily.py",
            "app/features/daily.py",
        ),
        "tests": (
            "tests/test_daily_supply_demand_features.py",
            "tests/test_daily_features.py",
        ),
        "safe_commands": (
            "python3 -m compileall app scripts",
            "pytest -q tests/test_daily_supply_demand_features.py tests/test_daily_features.py",
        ),
        "blockers": (
            "Tier B/C remain deferred.",
            "Source readiness does not authorize collection or backfill.",
        ),
    },
    "mapping": {
        "docs": (
            "docs/USDA_PSD_TIER_A_SOURCE_CONTRACT_AUDIT.md",
            "docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md",
        ),
        "code": (
            "app/collectors/supply_demand/usda_psd_config.py",
            "app/audits/usda_psd_tier_a_source_contract.py",
        ),
        "tests": (
            "tests/test_usda_psd_collector.py",
            "tests/test_usda_psd_tier_a_source_contract.py",
        ),
        "safe_commands": (
            "pytest -q tests/test_usda_psd_collector.py tests/test_usda_psd_tier_a_source_contract.py",
        ),
        "blockers": (
            "Mapping commit c48b8e7 is not deployed.",
            "Parser readiness is not production inventory or backfill approval.",
        ),
    },
    "production": {
        "docs": (
            "docs/codex/RUNBOOKS/production-readonly-audit.md",
            "docs/codex/RUNBOOKS/production-write-change.md",
            "DEPLOYMENT.md",
        ),
        "code": (
            "app/operations/backup.py",
            "app/monitoring/operational_report.py",
            "app/monitoring/quality_summary.py",
        ),
        "tests": (
            "tests/test_operational_tools.py",
            "tests/test_quality_summary.py",
        ),
        "safe_commands": (
            "python scripts/codex_project_context.py --area production",
            "docker compose config --quiet",
        ),
        "blockers": (
            "Production access and every write operation require explicit approval.",
            "Validate current HEAD/schema before relying on this snapshot.",
        ),
    },
    "review": {
        "docs": (
            "docs/codex/RUNBOOKS/safe-code-review.md",
            "docs/codex/ARCHITECTURE_MAP.md",
            "docs/codex/DECISION_INDEX.md",
        ),
        "code": (),
        "tests": (),
        "safe_commands": (
            "git diff --check",
            "git diff --stat",
            "pytest -q <focused-test-files>",
        ),
        "blockers": (
            "Review mode does not authorize edits or production access.",
            "Production impact needs production evidence, not local inference.",
        ),
    },
}

RUNTIME_PATH_PREFIXES = (
    "diagnostics/",
    "data/raw/",
    "data/exports/",
    "logs/",
    "deploy_artifacts/",
    ".env",
)
RUNTIME_SUFFIXES = (".db", ".sqlite", ".tar", ".tar.gz", ".zip")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print bounded, read-only project context for Codex tasks.",
    )
    parser.add_argument(
        "--area",
        choices=("all", *AREA_CONTEXT),
        default="all",
        help="Select the smallest relevant context area.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def area_context(area: str) -> dict[str, list[str]]:
    if area != "all":
        return {key: list(values) for key, values in AREA_CONTEXT[area].items()}
    merged: dict[str, list[str]] = {
        "docs": [],
        "code": [],
        "tests": [],
        "safe_commands": [],
        "blockers": [],
    }
    for area_name in AREA_CONTEXT:
        for key, values in AREA_CONTEXT[area_name].items():
            merged[key].extend(value for value in values if value not in merged[key])
    return merged


def collect_git_state(project_root: Path) -> dict[str, Any]:
    status = _git(project_root, "status", "--short", "--untracked-files=normal")
    status_lines = [line for line in status.splitlines() if line.strip()]
    return {
        "branch": _git(project_root, "branch", "--show-current") or "unknown",
        "head": _git(project_root, "rev-parse", "HEAD") or "unknown",
        "status": status_lines,
        "runtime_artifact_warnings": runtime_artifact_warnings(status_lines),
    }


def runtime_artifact_warnings(status_lines: Iterable[str]) -> list[str]:
    warnings: list[str] = []
    for line in status_lines:
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith(RUNTIME_PATH_PREFIXES) or path.endswith(RUNTIME_SUFFIXES):
            warnings.append(f"Do not stage runtime artifact: {path}")
    return warnings


def read_current_state(project_root: Path, *, max_lines: int = 90) -> list[str]:
    path = project_root / "docs/codex/CURRENT_STATE.md"
    if not path.is_file():
        return ["CURRENT_STATE.md is absent; use code, tests, and Git history."]
    lines = path.read_text(encoding="utf-8").splitlines()
    selected = [line for line in lines if line.strip()]
    return selected[:max_lines]


def latest_export_metadata(project_root: Path) -> dict[str, Any]:
    export_dir = project_root / "data/exports"
    if not export_dir.is_dir():
        return {"status": "absent"}
    manifests = [path for path in export_dir.glob("*_manifest.json") if path.is_file()]
    if not manifests:
        return {"status": "absent"}
    latest = max(manifests, key=lambda path: (path.stat().st_mtime_ns, path.name))
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unreadable", "path": str(latest.relative_to(project_root)), "reason": str(exc)}
    return {
        "status": "present",
        "path": str(latest.relative_to(project_root)),
        "export_name": payload.get("export_name"),
        "export_version": payload.get("export_version"),
        "git_commit": payload.get("git_commit"),
        "row_count": payload.get("row_count"),
        "column_count": payload.get("column_count"),
        "feature_date_min": payload.get("feature_date_min"),
        "feature_date_max": payload.get("feature_date_max"),
        "sha256": payload.get("sha256"),
    }


def build_context(project_root: Path, area: str) -> dict[str, Any]:
    return {
        "area": area,
        "git": collect_git_state(project_root),
        "current_state": read_current_state(project_root),
        "relevant": area_context(area),
        "latest_local_export_manifest": latest_export_metadata(project_root),
        "safety": [
            "Read-only context command; it performs no network, Docker, DB, collector, builder, or export calls.",
            "Production claims require a current read-only audit.",
            "Runtime artifacts must not be committed.",
        ],
    }


def render_text(context: dict[str, Any]) -> str:
    git = context["git"]
    relevant = context["relevant"]
    lines = [
        "# Codex Project Context",
        f"Area: {context['area']}",
        "",
        "## Git State",
        f"Branch: {git['branch']}",
        f"HEAD: {git['head']}",
        "Status:",
        *(f"- {line}" for line in git["status"]),
        "",
        "## Current Phase / Production Baseline",
        *context["current_state"],
    ]
    for key, title in (
        ("docs", "Relevant Docs"),
        ("code", "Relevant Code"),
        ("tests", "Relevant Tests"),
        ("safe_commands", "Safe Local Commands"),
        ("blockers", "Known Blockers"),
    ):
        lines.extend(["", f"## {title}", *(f"- {value}" for value in relevant[key])])
    lines.extend(["", "## Latest Local Export Manifest"])
    manifest = context["latest_local_export_manifest"]
    lines.extend(f"- {key}: {value}" for key, value in manifest.items())
    lines.extend(["", "## Runtime Artifact Warnings"])
    warnings = git["runtime_artifact_warnings"]
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- none detected in Git status")
    lines.extend(["", "## Safety", *(f"- {value}" for value in context["safety"])])
    if len(lines) > MAX_OUTPUT_LINES:
        lines = lines[: MAX_OUTPUT_LINES - 1] + ["[output truncated at 200 lines]"]
    return "\n".join(lines)


def _git(project_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context = build_context(PROJECT_ROOT, args.area)
    if args.format == "json":
        print(json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(render_text(context))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
