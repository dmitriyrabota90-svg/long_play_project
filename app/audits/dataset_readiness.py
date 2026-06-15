from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_DOCS = (
    "docs/FEATURE_CATALOG.md",
    "docs/DATASET_DICTIONARY.md",
    "docs/SOURCE_TO_FEATURE_LINEAGE.md",
    "docs/LEAKAGE_AND_ASOF_AUDIT.md",
    "docs/ML_READY_DATASET_AUDIT.md",
)
REQUIRED_FEATURE_GROUPS = (
    "identity",
    "price",
    "fx",
    "calendar",
    "energy",
    "benchmarks",
    "weather",
    "news_events",
    "trade",
    "supply_demand",
)
ASOF_MARKERS = (
    "energy_as_of_date",
    "benchmark_as_of_date",
    "weather_as_of_date",
    "news_as_of_date",
    "trade_as_of_date",
    "supply_demand_as_of_date",
)
MISSING_FLAG_MARKERS = (
    "energy_missing_flags",
    "benchmark_missing_flags",
    "weather_missing_flags",
    "news_missing_flags",
    "trade_missing_flags",
    "supply_demand_missing_flags",
)
LINEAGE_MARKERS = (
    "current price",
    "cbr fx",
    "fred",
    "world bank pink sheet",
    "open-meteo",
    "gdelt",
    "un comtrade",
    "usda psd",
)
LEAKAGE_MARKERS = (
    "price",
    "fx",
    "energy",
    "benchmark",
    "weather",
    "news",
    "trade",
    "supply-demand",
    "export",
    "no feature may use source data known after feature_date",
)


@dataclass(frozen=True)
class DatasetReadinessAudit:
    status: str
    docs_checked: int
    export_columns_count: int
    missing_docs: list[str]
    undocumented_export_columns: list[str]
    missing_feature_groups: list[str]
    missing_asof_docs: list[str]
    missing_missing_flag_docs: list[str]
    missing_lineage_rows: list[str]
    missing_leakage_topics: list[str]
    warnings: list[str]
    recommendation: str

    @property
    def warnings_count(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "docs_checked": self.docs_checked,
            "export_columns_count": self.export_columns_count,
            "missing_docs": self.missing_docs,
            "undocumented_export_columns": self.undocumented_export_columns,
            "missing_feature_groups": self.missing_feature_groups,
            "missing_asof_docs": self.missing_asof_docs,
            "missing_missing_flag_docs": self.missing_missing_flag_docs,
            "missing_lineage_rows": self.missing_lineage_rows,
            "missing_leakage_topics": self.missing_leakage_topics,
            "warnings": self.warnings,
            "warnings_count": self.warnings_count,
            "recommendation": self.recommendation,
        }


def run_dataset_readiness_audit(
    *,
    project_root: Path | str,
    output_dir: Path | str | None = None,
    write_artifacts: bool = True,
) -> DatasetReadinessAudit:
    root = Path(project_root)
    export_columns = extract_daily_feature_columns(root / "app/exports/daily_features_export.py")
    docs_text = _read_docs(root)

    missing_docs = [doc for doc in REQUIRED_DOCS if not (root / doc).exists()]
    dictionary_text = docs_text.get("docs/DATASET_DICTIONARY.md", "").lower()
    catalog_text = docs_text.get("docs/FEATURE_CATALOG.md", "").lower()
    lineage_text = docs_text.get("docs/SOURCE_TO_FEATURE_LINEAGE.md", "").lower()
    leakage_text = docs_text.get("docs/LEAKAGE_AND_ASOF_AUDIT.md", "").lower()
    ml_ready_text = docs_text.get("docs/ML_READY_DATASET_AUDIT.md", "").lower()

    undocumented_export_columns = [column for column in export_columns if column.lower() not in dictionary_text]
    missing_feature_groups = [group for group in REQUIRED_FEATURE_GROUPS if group not in catalog_text]
    missing_asof_docs = [marker for marker in ASOF_MARKERS if marker not in dictionary_text and marker not in leakage_text]
    missing_missing_flag_docs = [
        marker for marker in MISSING_FLAG_MARKERS if marker not in dictionary_text and marker not in catalog_text
    ]
    missing_lineage_rows = [marker for marker in LINEAGE_MARKERS if marker not in lineage_text]
    missing_leakage_topics = [marker for marker in LEAKAGE_MARKERS if marker not in leakage_text]

    warnings: list[str] = []
    if "server batch" not in ml_ready_text and "6.6a" not in ml_ready_text:
        warnings.append("server_batch_pending_not_documented")
    if "production export validation pending" not in ml_ready_text:
        warnings.append("production_export_validation_pending_not_documented")

    blocking = (
        missing_docs
        or undocumented_export_columns
        or missing_feature_groups
        or missing_asof_docs
        or missing_missing_flag_docs
        or missing_lineage_rows
        or missing_leakage_topics
    )
    if blocking:
        status = "fail"
        recommendation = "Fix missing dataset readiness documentation before treating export v1 as ML-ready."
    elif warnings:
        status = "warning"
        recommendation = "Documentation is structurally complete, but review warnings before production export validation."
    else:
        status = "ok"
        recommendation = "Run Phase 6.6A server batch, then validate a production export snapshot before ML experiments."

    audit = DatasetReadinessAudit(
        status=status,
        docs_checked=len(REQUIRED_DOCS),
        export_columns_count=len(export_columns),
        missing_docs=missing_docs,
        undocumented_export_columns=undocumented_export_columns,
        missing_feature_groups=missing_feature_groups,
        missing_asof_docs=missing_asof_docs,
        missing_missing_flag_docs=missing_missing_flag_docs,
        missing_lineage_rows=missing_lineage_rows,
        missing_leakage_topics=missing_leakage_topics,
        warnings=warnings,
        recommendation=recommendation,
    )
    if write_artifacts:
        artifact_dir = Path(output_dir) if output_dir is not None else root / "diagnostics/dataset_readiness"
        write_dataset_readiness_artifacts(audit, output_dir=artifact_dir)
    return audit


def extract_daily_feature_columns(path: Path) -> list[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "DAILY_FEATURE_COLUMNS":
                return list(ast.literal_eval(node.value))
    raise ValueError(f"DAILY_FEATURE_COLUMNS not found in {path}")


def write_dataset_readiness_artifacts(audit: DatasetReadinessAudit, *, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "DATASET_READINESS_AUDIT_REPORT.md"
    json_path = output_dir / "dataset_readiness_audit.json"
    payload = audit.to_dict()
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    report_path.write_text(_render_markdown_report(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path, json_path


def _read_docs(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for doc in REQUIRED_DOCS:
        path = root / doc
        result[doc] = path.read_text(encoding="utf-8") if path.exists() else ""
    return result


def _render_markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Dataset Readiness Audit Report",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- status: `{payload['status']}`",
        f"- docs_checked: `{payload['docs_checked']}`",
        f"- export_columns_count: `{payload['export_columns_count']}`",
        f"- warnings_count: `{payload['warnings_count']}`",
        f"- recommendation: {payload['recommendation']}",
        "",
        "## Findings",
    ]
    for key in (
        "missing_docs",
        "undocumented_export_columns",
        "missing_feature_groups",
        "missing_asof_docs",
        "missing_missing_flag_docs",
        "missing_lineage_rows",
        "missing_leakage_topics",
        "warnings",
    ):
        values = payload[key]
        lines.append(f"- {key}: {', '.join(values) if values else 'none'}")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "This audit is local-only. It reads export schema and documentation, writes diagnostics artifacts, "
            "and does not require PostgreSQL, collectors, migrations, scheduler, SSH, or production services.",
            "",
        ]
    )
    return "\n".join(lines)
