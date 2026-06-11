from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.audits.dataset_readiness import (
    ASOF_MARKERS,
    LINEAGE_MARKERS,
    MISSING_FLAG_MARKERS,
    REQUIRED_DOCS,
    REQUIRED_FEATURE_GROUPS,
    extract_daily_feature_columns,
    run_dataset_readiness_audit,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_doc(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8").lower()


def test_required_dataset_readiness_docs_exist() -> None:
    for doc in REQUIRED_DOCS:
        assert (PROJECT_ROOT / doc).exists(), doc


def test_feature_catalog_mentions_required_groups() -> None:
    text = _read_doc("docs/FEATURE_CATALOG.md")

    for group in REQUIRED_FEATURE_GROUPS:
        assert group in text
    assert "production-deployed" in text
    assert "local-implemented-awaiting-server-batch" in text


def test_dataset_dictionary_documents_all_export_columns_and_key_groups() -> None:
    text = _read_doc("docs/DATASET_DICTIONARY.md")
    columns = extract_daily_feature_columns(PROJECT_ROOT / "app/exports/daily_features_export.py")

    assert len(columns) >= 140
    for column in columns:
        assert column.lower() in text, column
    for marker in (*ASOF_MARKERS, *MISSING_FLAG_MARKERS):
        assert marker in text


def test_source_lineage_mentions_major_sources_and_builders() -> None:
    text = _read_doc("docs/SOURCE_TO_FEATURE_LINEAGE.md")

    for marker in LINEAGE_MARKERS:
        assert marker in text
    for builder in ("daily", "weather_daily", "news_daily", "trade_daily", "daily_features"):
        assert builder in text


def test_leakage_audit_mentions_no_future_leakage_and_all_groups() -> None:
    text = _read_doc("docs/LEAKAGE_AND_ASOF_AUDIT.md")

    assert "no feature may use source data known after feature_date" in text
    for topic in ("price", "fx", "energy", "benchmark", "weather", "news", "trade", "export"):
        assert topic in text


def test_ml_ready_audit_mentions_server_batch_pending_and_no_targets() -> None:
    text = _read_doc("docs/ML_READY_DATASET_AUDIT.md")

    assert "server batch 6.6a is still pending" in text
    assert "production export validation pending" in text
    assert "does not train a model" in text
    assert "no targets" in text


def test_dataset_readiness_audit_writes_report_and_json(tmp_path: Path) -> None:
    audit = run_dataset_readiness_audit(project_root=PROJECT_ROOT, output_dir=tmp_path)
    report_path = tmp_path / "DATASET_READINESS_AUDIT_REPORT.md"
    json_path = tmp_path / "dataset_readiness_audit.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert audit.status == "ok"
    assert report_path.exists()
    assert json_path.exists()
    assert payload["status"] == "ok"
    assert payload["docs_checked"] == len(REQUIRED_DOCS)
    assert payload["missing_docs"] == []
    assert payload["undocumented_export_columns"] == []
    assert payload["warnings_count"] == 0


def test_dataset_readiness_cli_generates_tmp_artifacts(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/audit_dataset_readiness.py", "--output-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "status=ok" in result.stdout
    assert "missing_docs=" in result.stdout
    assert (tmp_path / "DATASET_READINESS_AUDIT_REPORT.md").exists()
    assert (tmp_path / "dataset_readiness_audit.json").exists()


def test_dataset_readiness_audit_fails_when_docs_are_missing(tmp_path: Path) -> None:
    export_path = tmp_path / "app/exports/daily_features_export.py"
    export_path.parent.mkdir(parents=True)
    export_path.write_text('DAILY_FEATURE_COLUMNS = ["product_code"]\n', encoding="utf-8")

    audit = run_dataset_readiness_audit(project_root=tmp_path, write_artifacts=False)

    assert audit.status == "fail"
    assert sorted(audit.missing_docs) == sorted(REQUIRED_DOCS)
    assert audit.undocumented_export_columns == ["product_code"]
