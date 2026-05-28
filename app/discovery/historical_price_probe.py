from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import httpx
from sqlalchemy import text

from app.collectors.prices.current_price_config import CURRENT_PRICE_HEADERS, CURRENT_PRICE_INSTRUMENTS
from app.db.session import create_app_engine


EndpointAlias = Literal["historys", "kdata", "today_min", "four_days_min"]
ProbeStatus = Literal["parsed", "needs_manual_check", "not_supported", "error"]

OUTPUT_DIR = Path("diagnostics/historical_price_probe")
RAW_DIR_NAME = "raw"


@dataclass(frozen=True)
class EndpointSpec:
    alias: EndpointAlias
    endpoint: str
    params_style: str
    response_prefix: str
    data_type: str
    notes: str


@dataclass
class HistoricalRow:
    observed_at: str | None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    price: float | None = None
    volume: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductProbeResult:
    product_code: str
    external_code: str
    endpoint_alias: str
    endpoint: str
    status: ProbeStatus
    http_status: int | None = None
    content_type: str | None = None
    bytes_size: int | None = None
    raw_diagnostic_path: str | None = None
    rows_count: int = 0
    fields_detected: list[str] = field(default_factory=list)
    rows: list[HistoricalRow] = field(default_factory=list)
    sample_rows: list[HistoricalRow] = field(default_factory=list)
    notes: str = ""
    error: str | None = None


@dataclass
class ComparisonRow:
    product_code: str
    date: str | None
    historical_value: float | None
    current_price_last: float | None
    diff_abs: float | None
    diff_pct: float | None
    status: str


@dataclass
class HistoricalProbeRun:
    created_at: str
    endpoint_alias: str
    days: int
    products: list[ProductProbeResult]
    comparisons: list[ComparisonRow]
    comparison_error: str | None = None


ENDPOINTS: dict[str, EndpointSpec] = {
    "historys": EndpointSpec(
        alias="historys",
        endpoint="https://api.jijinhao.com/quoteCenter/historys.htm",
        params_style="codes",
        response_prefix="var quote_json = ",
        data_type="compact_history",
        notes="Compact history endpoint. q-field semantics still need manual confirmation.",
    ),
    "kdata": EndpointSpec(
        alias="kdata",
        endpoint="https://api.jijinhao.com/sQuoteCenter/kDataList.htm",
        params_style="code",
        response_prefix="var  KLC_KL = ",
        data_type="daily_ohlc",
        notes="Large OHLC-like endpoint discovered in public chart JavaScript.",
    ),
    "today_min": EndpointSpec(
        alias="today_min",
        endpoint="https://api.jijinhao.com/sQuoteCenter/todayMin.htm",
        params_style="code",
        response_prefix="var hq_str_ml = ",
        data_type="intraday_minutes",
        notes="Current-session minute data; not directly comparable to daily current snapshots.",
    ),
    "four_days_min": EndpointSpec(
        alias="four_days_min",
        endpoint="https://api.jijinhao.com/sQuoteCenter/fourDaysMin.htm",
        params_style="code",
        response_prefix="var KLC_ML = ",
        data_type="intraday_minutes",
        notes="Recent multi-day minute data; not directly comparable to daily bars without aggregation.",
    ),
}


def endpoint_aliases() -> tuple[str, ...]:
    return tuple(ENDPOINTS)


def probe_historical_prices(
    *,
    endpoint_alias: str,
    product_codes: tuple[str, ...] | None = None,
    days: int = 30,
    output_dir: Path = OUTPUT_DIR,
    timeout: float = 15.0,
    include_comparison: bool = True,
    http_client: httpx.Client | None = None,
) -> HistoricalProbeRun:
    if endpoint_alias not in ENDPOINTS:
        raise ValueError(f"unsupported endpoint alias: {endpoint_alias}")
    if days <= 0:
        raise ValueError("days must be positive")

    selected = _selected_instruments(product_codes)
    created_at = datetime.now(timezone.utc).isoformat()
    raw_dir = output_dir / RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    owns_client = http_client is None
    client = http_client or httpx.Client(follow_redirects=True)
    try:
        products = [_probe_product(client, instrument, endpoint_alias, days, raw_dir, timeout) for instrument in selected]
    finally:
        if owns_client:
            client.close()

    comparisons: list[ComparisonRow] = []
    comparison_error: str | None = None
    if include_comparison:
        try:
            comparisons = compare_with_current_observations(products)
        except Exception as exc:  # pragma: no cover - exercised against real deployments.
            comparison_error = str(exc)

    run = HistoricalProbeRun(
        created_at=created_at,
        endpoint_alias=endpoint_alias,
        days=days,
        products=products,
        comparisons=comparisons,
        comparison_error=comparison_error,
    )
    write_probe_outputs(run, output_dir)
    return run


def parse_historical_response(
    *,
    endpoint_alias: str,
    external_code: str,
    content: bytes,
    days: int = 30,
) -> tuple[list[HistoricalRow], list[str], str]:
    text_payload = content.decode("utf-8", errors="replace").strip()
    if not text_payload:
        return [], [], "Empty response."
    if endpoint_alias not in ENDPOINTS:
        return [], [], f"Endpoint alias {endpoint_alias} is not supported."

    spec = ENDPOINTS[endpoint_alias]
    if not text_payload.startswith(spec.response_prefix):
        return [], [], f"Expected prefix not found: {spec.response_prefix!r}."

    payload = text_payload[len(spec.response_prefix) :].strip().rstrip(";")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        return [], [], f"Response is not valid JSON after prefix removal: {exc}."

    if endpoint_alias == "historys":
        rows = _parse_historys(parsed, external_code)
    elif endpoint_alias == "kdata":
        rows = _parse_kdata(parsed)
    else:
        rows = _parse_intraday(parsed)

    rows = rows[-days:] if len(rows) > days else rows
    fields = sorted({field for row in rows for field, value in asdict(row).items() if field != "raw" and value is not None})
    notes = _parse_notes(endpoint_alias)
    return rows, fields, notes


def compare_with_current_observations(products: list[ProductProbeResult]) -> list[ComparisonRow]:
    current_prices = _load_current_price_last_by_date()
    return compare_probe_results(products, current_prices)


def compare_probe_results(
    products: list[ProductProbeResult],
    current_prices: dict[tuple[str, date], Decimal],
) -> list[ComparisonRow]:
    comparisons: list[ComparisonRow] = []
    for product in products:
        comparable_rows = [row for row in _all_rows(product) if _row_value(row) is not None and row.observed_at]
        product_comparisons = 0
        for row in comparable_rows:
            row_date = _parse_date(row.observed_at)
            if row_date is None:
                continue
            current = current_prices.get((product.product_code, row_date))
            if current is None:
                continue
            historical = Decimal(str(_row_value(row)))
            diff_abs = historical - current
            diff_pct = (diff_abs / current) if current != 0 else None
            comparisons.append(
                ComparisonRow(
                    product_code=product.product_code,
                    date=row_date.isoformat(),
                    historical_value=float(historical),
                    current_price_last=float(current),
                    diff_abs=float(diff_abs),
                    diff_pct=float(diff_pct) if diff_pct is not None else None,
                    status=_comparison_status(diff_abs, diff_pct),
                )
            )
            product_comparisons += 1
        if product_comparisons == 0:
            comparisons.append(
                ComparisonRow(
                    product_code=product.product_code,
                    date=None,
                    historical_value=None,
                    current_price_last=None,
                    diff_abs=None,
                    diff_pct=None,
                    status="no_overlap" if comparable_rows else "not_comparable",
                )
            )
    return comparisons


def write_probe_outputs(run: HistoricalProbeRun, output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = _merge_runs(output_dir, run)
    (output_dir / "historical_price_probe_results.json").write_text(
        json.dumps({"runs": [_json_safe(asdict(item)) for item in runs]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_comparison_csv(runs, output_dir / "historical_price_comparison.csv")
    (output_dir / "HISTORICAL_PRICE_PROBE_REPORT.md").write_text(render_probe_report(runs), encoding="utf-8")


def render_probe_report(run_or_runs: HistoricalProbeRun | list[HistoricalProbeRun]) -> str:
    runs = run_or_runs if isinstance(run_or_runs, list) else [run_or_runs]
    latest = runs[-1]
    lines: list[str] = [
        "# Historical Price Probe Report",
        "",
        f"Created: {latest.created_at}",
        f"Endpoint aliases: {', '.join(f'`{item.endpoint_alias}`' for item in runs)}",
        f"Days requested: {', '.join(f'{item.endpoint_alias}={item.days}' for item in runs)}",
        "",
        "## Executive Summary",
        "",
        "This is a diagnostics-only probe. It stores raw diagnostic responses under `diagnostics/historical_price_probe/raw/` and does not write to PostgreSQL production tables.",
        "",
        "## Endpoints Checked",
        "",
    ]
    for run in runs:
        spec = ENDPOINTS[run.endpoint_alias]
        lines.append(f"- `{run.endpoint_alias}` -> `{spec.endpoint}`; data_type=`{spec.data_type}`; notes: {spec.notes}")

    lines.extend(["", "## Instruments Checked", ""])
    seen_instruments = sorted({(product.product_code, product.external_code) for run in runs for product in run.products})
    for product_code, external_code in seen_instruments:
        lines.append(f"- `{product_code}` / `{external_code}`")

    lines.extend(["", "## Probe Results", ""])
    for run in runs:
        lines.extend([f"### Endpoint `{run.endpoint_alias}`", ""])
        for product in run.products:
            fields = ", ".join(product.fields_detected) if product.fields_detected else "none"
            lines.extend(
                [
                    f"#### {product.product_code}",
                    "",
                    f"- status: `{product.status}`",
                    f"- external_code: `{product.external_code}`",
                    f"- http_status: `{product.http_status}`",
                    f"- response_size: `{product.bytes_size}` bytes",
                    f"- parsed_rows: `{product.rows_count}`",
                    f"- detected_fields: {fields}",
                    f"- raw_diagnostic_path: `{product.raw_diagnostic_path}`",
                    f"- notes: {product.notes}",
                    "",
                    "Sample rows:",
                    "",
                    "```json",
                    json.dumps([_json_safe(asdict(row)) for row in product.sample_rows], ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

    lines.extend(["## Comparison With Current Price Observations", ""])
    comparison_rows = [(run.endpoint_alias, item) for run in runs for item in run.comparisons]
    comparison_errors = [f"{run.endpoint_alias}: {run.comparison_error}" for run in runs if run.comparison_error]
    if comparison_errors:
        lines.append("Comparison query failed or was unavailable:")
        for error in comparison_errors:
            lines.append(f"- `{error}`")
    if comparison_rows:
        lines.append("")
        lines.append("| endpoint | product_code | date | historical_value | current_price_last | diff_abs | diff_pct | status |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for endpoint_alias, item in comparison_rows[:120]:
            lines.append(
                f"| {endpoint_alias} | {item.product_code} | {item.date or ''} | {_fmt(item.historical_value)} | {_fmt(item.current_price_last)} | {_fmt(item.diff_abs)} | {_fmt(item.diff_pct)} | {item.status} |"
            )
    elif not comparison_errors:
        lines.append("No comparison rows were produced.")

    lines.extend(
        [
            "",
            "## Endpoint Assessment",
            "",
            "- `historys.htm`: promising compact history endpoint; q-field semantics require manual confirmation before production.",
            "- `kDataList.htm`: likely richer OHLC history, but responses can be large and need strict pagination/storage policy.",
            "- `todayMin.htm` / `fourDaysMin.htm`: intraday endpoints; useful later, but not a daily historical collector.",
            "",
            "## Production Design Proposal",
            "",
            "- Do not mix historical OHLC bars with current snapshot prices without an explicit data model.",
            "- Prefer a separate `jijinhao_historical_prices` source and a future `historical_price_bars` table, or add explicit `observation_type`, `open`, `high`, `low`, `close`, and `volume` fields before writing bars into normalized storage.",
            "- Feature builder should continue using current snapshots until a deliberate source-selection rule exists.",
            "- Historical backfill must carry `fetched_at` / `as_of_at` and must not be treated as data that was available in the past.",
            "- `historys.htm` is the safer first production prototype because it is compact; `kDataList.htm` needs additional size and pagination controls.",
            "",
            "## Recommendation",
            "",
            _recommendation(runs),
            "",
        ]
    )
    return "\n".join(lines)


def _probe_product(
    client: httpx.Client,
    instrument: Any,
    endpoint_alias: str,
    days: int,
    raw_dir: Path,
    timeout: float,
) -> ProductProbeResult:
    spec = ENDPOINTS[endpoint_alias]
    params = _params_for(spec, instrument.external_code, days)
    try:
        response = client.get(spec.endpoint, params=params, headers=CURRENT_PRICE_HEADERS, timeout=timeout)
    except httpx.HTTPError as exc:
        return ProductProbeResult(
            product_code=instrument.product_code,
            external_code=instrument.external_code,
            endpoint_alias=endpoint_alias,
            endpoint=spec.endpoint,
            status="error",
            notes=spec.notes,
            error=str(exc),
        )

    raw_path = _write_raw_diagnostic(raw_dir, instrument.product_code, endpoint_alias, response.content)
    rows, fields, notes = parse_historical_response(
        endpoint_alias=endpoint_alias,
        external_code=instrument.external_code,
        content=response.content,
        days=days,
    )
    status: ProbeStatus = "parsed" if rows else "needs_manual_check"
    return ProductProbeResult(
        product_code=instrument.product_code,
        external_code=instrument.external_code,
        endpoint_alias=endpoint_alias,
        endpoint=str(response.url),
        status=status,
        http_status=response.status_code,
        content_type=response.headers.get("content-type"),
        bytes_size=len(response.content),
        raw_diagnostic_path=str(raw_path),
        rows_count=len(rows),
        fields_detected=fields,
        rows=rows,
        sample_rows=rows[:3],
        notes=notes,
    )


def _selected_instruments(product_codes: tuple[str, ...] | None) -> tuple[Any, ...]:
    if not product_codes:
        return CURRENT_PRICE_INSTRUMENTS
    wanted = set(product_codes)
    selected = tuple(item for item in CURRENT_PRICE_INSTRUMENTS if item.product_code in wanted)
    missing = wanted - {item.product_code for item in selected}
    if missing:
        raise ValueError(f"unknown product_code(s): {', '.join(sorted(missing))}")
    return selected


def _params_for(spec: EndpointSpec, external_code: str, days: int) -> dict[str, str]:
    if spec.alias == "historys":
        return {"codes": external_code, "style": "3", "pageSize": str(days), "currentPage": "1"}
    if spec.alias == "kdata":
        return {"code": external_code, "pageSize": str(days)}
    return {"code": external_code}


def _write_raw_diagnostic(raw_dir: Path, product_code: str, endpoint_alias: str, content: bytes) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    path = raw_dir / endpoint_alias / f"{product_code}_{digest[:12]}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _parse_historys(parsed: Any, external_code: str) -> list[HistoricalRow]:
    data = parsed.get("data", {}) if isinstance(parsed, dict) else {}
    raw_rows = data.get(external_code, []) if isinstance(data, dict) else []
    rows: list[HistoricalRow] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        observed_at = _timestamp_ms_to_iso(raw.get("time"))
        close = _to_float(raw.get("q2"))
        rows.append(
            HistoricalRow(
                observed_at=observed_at,
                open=_to_float(raw.get("q1")),
                high=_to_float(raw.get("q3")),
                low=_to_float(raw.get("q4")),
                close=close,
                price=close,
                volume=_to_float(raw.get("q60")),
                raw={key: raw.get(key) for key in ("q1", "q2", "q3", "q4", "q60", "q62", "time")},
            )
        )
    return rows


def _parse_kdata(parsed: Any) -> list[HistoricalRow]:
    raw_rows = _find_row_list(parsed)
    rows: list[HistoricalRow] = []
    for raw in raw_rows:
        if isinstance(raw, dict):
            rows.append(
                HistoricalRow(
                    observed_at=_dateish_to_iso(raw.get("day") or raw.get("date") or raw.get("time")),
                    open=_to_float(raw.get("open") or raw.get("o")),
                    high=_to_float(raw.get("high") or raw.get("h")),
                    low=_to_float(raw.get("low") or raw.get("l")),
                    close=_to_float(raw.get("close") or raw.get("c") or raw.get("price")),
                    price=_to_float(raw.get("close") or raw.get("c") or raw.get("price")),
                    volume=_to_float(raw.get("volume") or raw.get("vol")),
                    raw={str(key): value for key, value in list(raw.items())[:16]},
                )
            )
        elif isinstance(raw, list) and raw:
            rows.append(_parse_array_row(raw))
    return rows


def _parse_intraday(parsed: Any) -> list[HistoricalRow]:
    raw_rows = _find_row_list(parsed)
    rows: list[HistoricalRow] = []
    for raw in raw_rows:
        if isinstance(raw, dict):
            price = _to_float(raw.get("price") or raw.get("p") or raw.get("avg_price"))
            rows.append(
                HistoricalRow(
                    observed_at=_dateish_to_iso(raw.get("time") or raw.get("date")),
                    price=price,
                    close=price,
                    volume=_to_float(raw.get("volume") or raw.get("vol")),
                    raw={str(key): value for key, value in list(raw.items())[:16]},
                )
            )
        elif isinstance(raw, list) and raw:
            rows.append(_parse_array_row(raw))
    return rows


def _parse_array_row(raw: list[Any]) -> HistoricalRow:
    observed_at = _dateish_to_iso(raw[0]) if raw else None
    open_value = _to_float(raw[1] if len(raw) > 1 else None)
    high = _to_float(raw[2] if len(raw) > 2 else None)
    low = _to_float(raw[3] if len(raw) > 3 else None)
    close = _to_float(raw[4] if len(raw) > 4 else None)
    volume = _to_float(raw[9] if len(raw) > 9 else raw[5] if len(raw) > 5 else None)
    return HistoricalRow(
        observed_at=observed_at,
        open=open_value,
        high=high,
        low=low,
        close=close,
        price=close,
        volume=volume,
        raw={str(index): value for index, value in enumerate(raw[:16])},
    )


def _find_row_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return value
        nested: list[list[Any]] = []
        for item in value:
            found = _find_row_list(item)
            if found:
                nested.append(found)
        if nested:
            return max(nested, key=len)
        if value and all(isinstance(item, list) for item in value):
            return value
    if isinstance(value, dict):
        preferred = ("data", "rows", "list", "items", "kline", "klines")
        for key in preferred:
            if key in value:
                found = _find_row_list(value[key])
                if found:
                    return found
        for item in value.values():
            found = _find_row_list(item)
            if found:
                return found
    return []


def _load_current_price_last_by_date() -> dict[tuple[str, date], Decimal]:
    query = text(
        """
        SELECT p.code AS product_code, po.observed_at, po.price
        FROM price_observations po
        JOIN products p ON p.id = po.product_id
        ORDER BY p.code, po.observed_at
        """
    )
    latest: dict[tuple[str, date], tuple[datetime, Decimal]] = {}
    with create_app_engine().connect() as connection:
        for row in connection.execute(query):
            observed_at = row.observed_at
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            key = (row.product_code, observed_at.date())
            existing = latest.get(key)
            if existing is None or observed_at > existing[0]:
                latest[key] = (observed_at, Decimal(row.price))
    return {key: price for key, (_, price) in latest.items()}


def _all_rows(product: ProductProbeResult) -> list[HistoricalRow]:
    return product.rows or product.sample_rows


def _row_value(row: HistoricalRow) -> float | None:
    return row.close if row.close is not None else row.price


def _comparison_status(diff_abs: Decimal, diff_pct: Decimal | None) -> str:
    if diff_abs == 0:
        return "match_close"
    if diff_pct is not None and abs(diff_pct) <= Decimal("0.01"):
        return "small_diff"
    return "large_diff"


def _parse_notes(endpoint_alias: str) -> str:
    if endpoint_alias == "historys":
        return "Parsed q1/q2/q3/q4/q60 fields as provisional OHLC/volume mapping; needs manual confirmation."
    if endpoint_alias == "kdata":
        return "Parsed OHLC-like rows from JSON structure; endpoint may return large responses."
    return "Parsed intraday-like rows when possible; not daily OHLC."


def _timestamp_ms_to_iso(value: Any) -> str | None:
    number = _to_float(value)
    if number is None:
        return None
    try:
        return datetime.fromtimestamp(number / 1000, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _dateish_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit() and len(value) >= 12):
        return _timestamp_ms_to_iso(value)
    text_value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            parse_value = text_value[:19] if fmt == "%Y-%m-%d %H:%M:%S" else text_value[:10]
            if fmt == "%Y%m%d":
                parse_value = text_value[:8]
            return datetime.strptime(parse_value, fmt).date().isoformat()
        except ValueError:
            continue
    return text_value[:10] if len(text_value) >= 10 else text_value


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value).replace(",", ".")))
    except (InvalidOperation, ValueError):
        return None


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _write_comparison_csv(runs: list[HistoricalProbeRun], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "endpoint_alias",
                "product_code",
                "date",
                "historical_value",
                "current_price_last",
                "diff_abs",
                "diff_pct",
                "status",
            ],
        )
        writer.writeheader()
        for run in runs:
            for item in run.comparisons:
                writer.writerow({"endpoint_alias": run.endpoint_alias, **asdict(item)})


def _recommendation(runs: list[HistoricalProbeRun]) -> str:
    by_alias = {run.endpoint_alias: run for run in runs}
    historys = by_alias.get("historys")
    if historys is not None:
        parsed = [product for product in historys.products if product.status == "parsed" and product.rows_count > 0]
        if len(parsed) == len(historys.products):
            return "Recommendation: `needs_manual_check` leaning toward a future production prototype. Confirm q-field semantics before schema work."
    kdata = by_alias.get("kdata")
    if kdata is not None and any(product.status == "parsed" and product.rows_count > 0 for product in kdata.products):
        return "Recommendation: `needs_manual_check`. Richer OHLC appears possible, but response size and pagination must be controlled first."
    if len(runs) == 1 and runs[0].endpoint_alias == "historys" and all(
        product.status == "parsed" and product.rows_count > 0 for product in runs[0].products
    ):
        return "Recommendation: `needs_manual_check` leaning toward a future production prototype. Confirm q-field semantics before schema work."
    return "Recommendation: `do_not_use` for production until parsing and endpoint behavior are confirmed."


def _merge_runs(output_dir: Path, run: HistoricalProbeRun) -> list[HistoricalProbeRun]:
    existing_path = output_dir / "historical_price_probe_results.json"
    existing_runs: list[HistoricalProbeRun] = []
    if existing_path.exists():
        try:
            payload = json.loads(existing_path.read_text(encoding="utf-8"))
            raw_runs = payload.get("runs") if isinstance(payload, dict) else None
            if isinstance(raw_runs, list):
                existing_runs = [_run_from_json(item) for item in raw_runs if isinstance(item, dict)]
        except (json.JSONDecodeError, OSError, TypeError, KeyError):
            existing_runs = []
    by_alias = {item.endpoint_alias: item for item in existing_runs}
    by_alias[run.endpoint_alias] = run
    return [by_alias[key] for key in sorted(by_alias)]


def _run_from_json(payload: dict[str, Any]) -> HistoricalProbeRun:
    products = []
    for product in payload.get("products", []):
        rows = [_row_from_json(item) for item in product.get("rows", [])]
        sample_rows = [_row_from_json(item) for item in product.get("sample_rows", [])]
        products.append(
            ProductProbeResult(
                product_code=product["product_code"],
                external_code=product["external_code"],
                endpoint_alias=product["endpoint_alias"],
                endpoint=product["endpoint"],
                status=product["status"],
                http_status=product.get("http_status"),
                content_type=product.get("content_type"),
                bytes_size=product.get("bytes_size"),
                raw_diagnostic_path=product.get("raw_diagnostic_path"),
                rows_count=product.get("rows_count", 0),
                fields_detected=list(product.get("fields_detected", [])),
                rows=rows,
                sample_rows=sample_rows,
                notes=product.get("notes", ""),
                error=product.get("error"),
            )
        )
    comparisons = [
        ComparisonRow(
            product_code=item["product_code"],
            date=item.get("date"),
            historical_value=item.get("historical_value"),
            current_price_last=item.get("current_price_last"),
            diff_abs=item.get("diff_abs"),
            diff_pct=item.get("diff_pct"),
            status=item["status"],
        )
        for item in payload.get("comparisons", [])
    ]
    return HistoricalProbeRun(
        created_at=payload["created_at"],
        endpoint_alias=payload["endpoint_alias"],
        days=payload["days"],
        products=products,
        comparisons=comparisons,
        comparison_error=payload.get("comparison_error"),
    )


def _row_from_json(payload: dict[str, Any]) -> HistoricalRow:
    return HistoricalRow(
        observed_at=payload.get("observed_at"),
        open=payload.get("open"),
        high=payload.get("high"),
        low=payload.get("low"),
        close=payload.get("close"),
        price=payload.get("price"),
        volume=payload.get("volume"),
        raw=payload.get("raw", {}),
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
