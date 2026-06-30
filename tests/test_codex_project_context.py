from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import codex_project_context


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_area_context_selects_narrow_mapping_files() -> None:
    context = codex_project_context.area_context("mapping")

    assert context["code"] == [
        "app/collectors/supply_demand/usda_psd_config.py",
        "app/audits/usda_psd_tier_a_source_contract.py",
    ]
    assert "tests/test_usda_psd_tier_a_source_contract.py" in context["tests"]
    assert "app/features/weather_daily.py" not in context["code"]


def test_all_area_context_deduplicates_paths() -> None:
    context = codex_project_context.area_context("all")

    for values in context.values():
        assert len(values) == len(set(values))
    assert "docs/codex/RUNBOOKS/safe-code-review.md" in context["docs"]


def test_runtime_artifact_warning_is_bounded_to_git_status() -> None:
    warnings = codex_project_context.runtime_artifact_warnings(
        [
            "?? diagnostics/",
            "?? long_play_project_app_123.tar.gz",
            " M app/features/daily.py",
            "?? data/exports/demo_manifest.json",
        ]
    )

    assert warnings == [
        "Do not stage runtime artifact: diagnostics/",
        "Do not stage runtime artifact: long_play_project_app_123.tar.gz",
        "Do not stage runtime artifact: data/exports/demo_manifest.json",
    ]


def test_latest_export_metadata_reads_only_latest_manifest(tmp_path: Path) -> None:
    export_dir = tmp_path / "data/exports"
    export_dir.mkdir(parents=True)
    old = export_dir / "old_manifest.json"
    latest = export_dir / "latest_manifest.json"
    old.write_text(json.dumps({"row_count": 1, "git_commit": "old"}), encoding="utf-8")
    latest.write_text(
        json.dumps(
            {
                "export_name": "daily_features",
                "export_version": "daily_features_v1",
                "row_count": 140,
                "column_count": 166,
                "git_commit": "abc123",
                "sha256": {"csv": "a" * 64},
            }
        ),
        encoding="utf-8",
    )
    os.utime(old, ns=(1, 1))
    os.utime(latest, ns=(2, 2))

    metadata = codex_project_context.latest_export_metadata(tmp_path)

    assert metadata["path"] == "data/exports/latest_manifest.json"
    assert metadata["row_count"] == 140
    assert metadata["git_commit"] == "abc123"


def test_latest_export_metadata_is_robust_when_runtime_files_are_absent(tmp_path: Path) -> None:
    assert codex_project_context.latest_export_metadata(tmp_path) == {"status": "absent"}
    assert "CURRENT_STATE.md is absent" in codex_project_context.read_current_state(tmp_path)[0]


def test_git_collection_invokes_git_only(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    class Result:
        returncode = 0
        stdout = ""

    def fake_run(command, **kwargs):
        calls.append(tuple(command))
        return Result()

    monkeypatch.setattr(codex_project_context.subprocess, "run", fake_run)

    codex_project_context.collect_git_state(tmp_path)

    assert calls
    assert all(command[0] == "git" for command in calls)


def test_script_uses_standard_library_and_no_application_imports() -> None:
    path = PROJECT_ROOT / "scripts/codex_project_context.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert imported_roots <= {
        "__future__",
        "argparse",
        "collections",
        "json",
        "pathlib",
        "subprocess",
        "typing",
    }
    assert "app" not in imported_roots


def test_text_output_is_capped_and_contains_required_sections(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        codex_project_context,
        "collect_git_state",
        lambda _: {
            "branch": "main",
            "head": "abc123",
            "status": [],
            "runtime_artifact_warnings": [],
        },
    )
    context = codex_project_context.build_context(tmp_path, "mapping")
    output = codex_project_context.render_text(context)

    assert len(output.splitlines()) <= 200
    assert "## Git State" in output
    assert "## Relevant Docs" in output
    assert "## Known Blockers" in output
    assert "## Runtime Artifact Warnings" in output


def test_cli_help_and_json_are_read_only() -> None:
    help_result = subprocess.run(
        [sys.executable, "scripts/codex_project_context.py", "--help"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    json_result = subprocess.run(
        [
            sys.executable,
            "scripts/codex_project_context.py",
            "--area",
            "review",
            "--format",
            "json",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--area" in help_result.stdout
    payload = json.loads(json_result.stdout)
    assert payload["area"] == "review"
    assert len(json_result.stdout.splitlines()) == 1
