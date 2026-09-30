from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import scripts.weather_recovery as cli


def _result(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        requests_completed=1,
        observations_written=2,
        observations_skipped=3,
        feature_rows_written=4,
        conflicts_count=1,
        collector_errors_count=2,
        backlog_remaining_estimate=5,
        errors=("visible",),
        plan=SimpleNamespace(
            safe_end=date(2026, 6, 10),
            lower_bound=date(2026, 6, 1),
            requests_planned=1,
            backlog_days=9,
            budget_exhausted=True,
            chunks=(),
        ),
    )


def test_cli_emits_detailed_json_and_nonzero_for_partial(monkeypatch, capsys) -> None:
    class FakeService:
        def run(self, **kwargs):
            assert kwargs["mode"] == "catchup"
            return _result("partial_success")

    monkeypatch.setattr(cli, "WeatherRecoveryService", FakeService)
    monkeypatch.setattr("sys.argv", ["weather_recovery.py", "--mode", "catchup"])

    assert cli.main() == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "partial_success"
    assert payload["conflicts_count"] == 1
    assert payload["collector_errors_count"] == 2
    assert payload["backlog_remaining_estimate"] == 5


def test_cli_status_exit_codes_distinguish_backlog_and_overlap(monkeypatch, capsys) -> None:
    for status, expected_code in (("success", 0), ("dry_run", 0), ("success_with_backlog", 3), ("skipped_overlap", 4), ("error", 1)):
        class FakeService:
            def run(self, **kwargs):
                return _result(status)

        monkeypatch.setattr(cli, "WeatherRecoveryService", FakeService)
        monkeypatch.setattr("sys.argv", ["weather_recovery.py"])
        assert cli.main() == expected_code
        capsys.readouterr()
