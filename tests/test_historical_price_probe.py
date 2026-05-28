from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from app.discovery.historical_price_probe import (
    ENDPOINTS,
    HistoricalRow,
    ProductProbeResult,
    compare_probe_results,
    endpoint_aliases,
    parse_historical_response,
    probe_historical_prices,
)


def _historys_payload(code: str = "JO_165938") -> bytes:
    timestamp_ms = int(datetime(2026, 5, 25, tzinfo=timezone.utc).timestamp() * 1000)
    payload = {
        "style": 3,
        "data": {
            f"{code}_productName": "豆粕主力",
            f"{code}_unit": "元/吨",
            code: [
                {
                    "q1": 2998,
                    "q2": 2990,
                    "q3": 2999,
                    "q4": 2984,
                    "q60": 659103,
                    "q62": 2461397,
                    "time": timestamp_ms,
                }
            ],
        },
    }
    return ("var quote_json = " + json.dumps(payload, ensure_ascii=False)).encode()


class FakeHttpClient:
    def __init__(self, content: bytes = _historys_payload()) -> None:
        self.content = content
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        self.calls.append((url, params))
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, content=self.content, headers={"content-type": "text/html;charset=UTF-8"}, request=request)

    def close(self) -> None:
        return None


def test_endpoint_alias_mapping_contains_supported_aliases() -> None:
    assert {"historys", "kdata", "today_min", "four_days_min"} <= set(endpoint_aliases())
    assert ENDPOINTS["historys"].endpoint.endswith("/quoteCenter/historys.htm")


def test_parse_historys_sample_to_canonical_rows() -> None:
    rows, fields, notes = parse_historical_response(endpoint_alias="historys", external_code="JO_165938", content=_historys_payload())

    assert len(rows) == 1
    assert rows[0].observed_at == "2026-05-25"
    assert rows[0].open == 2998.0
    assert rows[0].high == 2999.0
    assert rows[0].low == 2984.0
    assert rows[0].close == 2990.0
    assert rows[0].price == 2990.0
    assert "close" in fields
    assert "needs manual confirmation" in notes


def test_parser_handles_empty_and_unknown_format() -> None:
    rows, fields, notes = parse_historical_response(endpoint_alias="historys", external_code="JO_165938", content=b"")
    assert rows == []
    assert fields == []
    assert "Empty" in notes

    rows, fields, notes = parse_historical_response(
        endpoint_alias="historys",
        external_code="JO_165938",
        content=b"var something_else = {}",
    )
    assert rows == []
    assert fields == []
    assert "Expected prefix" in notes


def test_parse_kdata_nested_series_to_canonical_rows() -> None:
    payload = {
        "data": [
            [
                {
                    "date": 1779667200000,
                    "open": 3000,
                    "high": 3010,
                    "low": 2980,
                    "close": 2995,
                    "day": "2026/05/24",
                    "volume": 100,
                },
                {
                    "date": 1779753600000,
                    "open": 2995,
                    "high": 3020,
                    "low": 2990,
                    "close": 3010,
                    "day": "2026/05/25",
                    "volume": 120,
                },
            ],
            [],
        ]
    }
    content = ("var  KLC_KL = " + json.dumps(payload)).encode()

    rows, fields, notes = parse_historical_response(endpoint_alias="kdata", external_code="JO_165938", content=content)

    assert len(rows) == 2
    assert rows[-1].observed_at == "2026-05-25"
    assert rows[-1].close == 3010.0
    assert rows[-1].volume == 120.0
    assert "high" in fields
    assert "large responses" in notes


def test_comparison_logic_statuses() -> None:
    product = ProductProbeResult(
        product_code="soybean_meal",
        external_code="JO_165938",
        endpoint_alias="historys",
        endpoint=ENDPOINTS["historys"].endpoint,
        status="parsed",
        rows=[
            HistoricalRow(observed_at="2026-05-25", close=2990.0, price=2990.0),
            HistoricalRow(observed_at="2026-05-26", close=3100.0, price=3100.0),
        ],
        rows_count=2,
    )

    comparisons = compare_probe_results(
        [product],
        {
            ("soybean_meal", datetime(2026, 5, 25).date()): Decimal("2990"),
            ("soybean_meal", datetime(2026, 5, 26).date()): Decimal("3000"),
        },
    )

    assert comparisons[0].status == "match_close"
    assert comparisons[1].status == "large_diff"


def test_probe_writes_raw_diagnostics_outside_production_raw(tmp_path: Path) -> None:
    run = probe_historical_prices(
        endpoint_alias="historys",
        product_codes=("soybean_meal",),
        days=30,
        output_dir=tmp_path / "diagnostics" / "historical_price_probe",
        include_comparison=False,
        http_client=FakeHttpClient(),
    )

    assert run.products[0].status == "parsed"
    raw_path = Path(run.products[0].raw_diagnostic_path or "")
    assert "diagnostics/historical_price_probe/raw" in raw_path.as_posix()
    assert "data/raw" not in raw_path.as_posix()
    assert raw_path.exists()


def test_probe_module_does_not_import_production_raw_store() -> None:
    import app.discovery.historical_price_probe as module

    assert "RawStore" not in module.__dict__


def test_cli_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/probe_historical_prices.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--endpoint" in result.stdout
