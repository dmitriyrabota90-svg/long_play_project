from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx

from app.collectors.prices.current_price_config import CURRENT_PRICE_HEADERS, CURRENT_PRICE_INSTRUMENTS
from app.collectors.prices.current_price_source import PriceParseError, parse_price_response
from app.collectors.prices.current_price_config import CurrentPriceInstrument


DiscoveryStatus = Literal["ready_to_add", "needs_manual_check", "not_found"]
CandidateProbeStatus = Literal["parsed", "rejected", "error", "not_checked"]


@dataclass(frozen=True)
class DiscoveryCandidate:
    product_code: str
    title: str
    source_code: str
    endpoint: str
    params: dict[str, str]
    external_code: str
    parser_type: Literal["json", "csv"]
    response_prefix: str
    expected_keywords: tuple[str, ...]
    price_path: tuple[str, ...] | None = None
    price_index: int | None = None
    notes: str = ""


@dataclass
class CandidateResult:
    product_code: str
    title: str
    status: DiscoveryStatus
    source_code: str
    endpoint: str | None
    params: dict[str, str]
    external_code: str | None
    parser_type: str | None
    response_prefix: str | None
    price_path: list[str] | None
    price_index: int | None
    sample_price: float | None
    parsed_name: str | None
    observed_text: str | None
    content_type: str | None
    bytes_size: int | None
    probe_status: CandidateProbeStatus
    notes: str
    checked_at: str
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)


MISSING_PRODUCTS: tuple[dict[str, str], ...] = (
    {"product_code": "soybean_meal", "title": "Соевый шрот"},
    {"product_code": "sunflower_oil", "title": "Подсолнечное масло"},
    {"product_code": "sunflower_meal", "title": "Подсолнечный шрот"},
)


BUILT_IN_CANDIDATES: tuple[DiscoveryCandidate, ...] = (
    DiscoveryCandidate(
        product_code="soybean_meal",
        title="Соевый шрот",
        source_code="current_price_source",
        endpoint="https://api.jijinhao.com/quoteCenter/realTime.htm",
        params={"codes": "JO_165938"},
        external_code="JO_165938",
        parser_type="json",
        response_prefix="var quote_json = ",
        price_path=("JO_165938", "q5"),
        price_index=None,
        expected_keywords=("豆粕",),
        notes="Found from public quheqihuo soybean meal page that calls the Jijinhao quoteCenter API.",
    ),
    DiscoveryCandidate(
        product_code="soybean_meal",
        title="Соевый шрот",
        source_code="current_price_source",
        endpoint="https://api.jijinhao.com/sQuoteCenter/realTime.htm",
        params={"codes": "JO_165950"},
        external_code="JO_165950",
        parser_type="csv",
        response_prefix="var hq_str_JO_165950 = ",
        price_path=None,
        price_index=3,
        expected_keywords=("豆粕",),
        notes="Nearby code checked during discovery; current response is empty.",
    ),
    DiscoveryCandidate(
        product_code="soybean_meal",
        title="Соевый шрот",
        source_code="current_price_source",
        endpoint="https://api.jijinhao.com/sQuoteCenter/realTime.htm",
        params={"codes": "JO_165952"},
        external_code="JO_165952",
        parser_type="csv",
        response_prefix="var hq_str_JO_165952 = ",
        price_path=None,
        price_index=3,
        expected_keywords=("豆粕",),
        notes="Nearby code checked during discovery; it resolves to soybean oil, not soybean meal.",
    ),
)


def discover_price_instruments(
    *,
    candidates: tuple[DiscoveryCandidate, ...] = BUILT_IN_CANDIDATES,
    timeout: float = 15.0,
    http_client: httpx.Client | None = None,
    checked_at: datetime | None = None,
) -> list[CandidateResult]:
    checked_at = checked_at or datetime.now(timezone.utc)
    owns_client = http_client is None
    client = http_client or httpx.Client(follow_redirects=True)
    try:
        probe_results = [_probe_candidate(client, candidate, timeout, checked_at) for candidate in candidates]
    finally:
        if owns_client:
            client.close()
    return _summarize_products(probe_results, checked_at)


def write_discovery_outputs(results: list[CandidateResult], output_dir: Path, *, created_at: datetime | None = None) -> None:
    created_at = created_at or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "price_instrument_candidates.json"
    report_path = output_dir / "PRICE_INSTRUMENT_DISCOVERY_REPORT.md"
    json_path.write_text(
        json.dumps([_json_safe(asdict(result)) for result in results], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(_render_report(results, created_at), encoding="utf-8")


def build_custom_candidate(
    *,
    product_code: str,
    title: str,
    endpoint: str,
    external_code: str,
    parser_type: Literal["json", "csv"],
    response_prefix: str | None = None,
    price_path: tuple[str, ...] | None = None,
    price_index: int | None = None,
    expected_keywords: tuple[str, ...] = (),
) -> DiscoveryCandidate:
    if response_prefix is None:
        response_prefix = "var quote_json = " if parser_type == "json" else f"var hq_str_{external_code} = "
    if parser_type == "json" and price_path is None:
        price_path = (external_code, "q5")
    if parser_type == "csv" and price_index is None:
        price_index = 3
    return DiscoveryCandidate(
        product_code=product_code,
        title=title,
        source_code="current_price_source",
        endpoint=endpoint,
        params={"codes": external_code},
        external_code=external_code,
        parser_type=parser_type,
        response_prefix=response_prefix,
        price_path=price_path,
        price_index=price_index,
        expected_keywords=expected_keywords,
        notes="Custom candidate supplied from CLI.",
    )


def _probe_candidate(
    client: httpx.Client,
    candidate: DiscoveryCandidate,
    timeout: float,
    checked_at: datetime,
) -> CandidateResult:
    instrument = CurrentPriceInstrument(
        product_code=candidate.product_code,
        external_code=candidate.external_code,
        endpoint=candidate.endpoint,
        params=candidate.params,
        parser_type=candidate.parser_type,
        response_prefix=candidate.response_prefix,
        price_path=candidate.price_path,
        price_index=candidate.price_index,
        currency="CNY",
        unit="metric_ton",
        source_note=candidate.notes,
    )
    try:
        response = client.get(candidate.endpoint, params=candidate.params, headers=CURRENT_PRICE_HEADERS, timeout=timeout)
    except httpx.HTTPError as exc:
        return _candidate_result(candidate, checked_at, "not_found", "error", notes=f"{candidate.notes} HTTP error: {exc}")

    content_type = response.headers.get("content-type")
    bytes_size = len(response.content)
    try:
        price = parse_price_response(instrument, response.content)
        parsed_name = extract_display_name(instrument, response.text)
        observed_text = extract_observed_text(instrument, response.text)
    except PriceParseError as exc:
        return _candidate_result(
            candidate,
            checked_at,
            "not_found",
            "rejected",
            content_type=content_type,
            bytes_size=bytes_size,
            notes=f"{candidate.notes} Parse rejected: {exc}",
        )

    keyword_match = not candidate.expected_keywords or any(
        keyword in (parsed_name or "") or keyword in response.text for keyword in candidate.expected_keywords
    )
    status: DiscoveryStatus = "ready_to_add" if keyword_match else "not_found"
    probe_status: CandidateProbeStatus = "parsed" if keyword_match else "rejected"
    notes = candidate.notes
    if not keyword_match:
        notes = f"{notes} Parsed response name did not match expected keywords: {', '.join(candidate.expected_keywords)}."

    return _candidate_result(
        candidate,
        checked_at,
        status,
        probe_status,
        sample_price=float(price),
        parsed_name=parsed_name,
        observed_text=observed_text,
        content_type=content_type,
        bytes_size=bytes_size,
        notes=notes,
    )


def extract_display_name(instrument: CurrentPriceInstrument, payload: str) -> str | None:
    body = _strip_prefix(payload, instrument.response_prefix)
    if instrument.parser_type == "json":
        root = json.loads(body)
        value: Any = root
        for key in instrument.price_path or (instrument.external_code,):
            value = value[key]
            if key == instrument.external_code:
                break
        if isinstance(value, dict):
            return str(value.get("showName") or value.get("name") or "") or None
        return None
    parts = _csv_parts(body)
    return parts[0] if parts else None


def extract_observed_text(instrument: CurrentPriceInstrument, payload: str) -> str | None:
    body = _strip_prefix(payload, instrument.response_prefix)
    if instrument.parser_type == "json":
        root = json.loads(body)
        data = root.get(instrument.external_code) if isinstance(root, dict) else None
        observed = data.get("time") if isinstance(data, dict) else None
        return str(observed) if observed is not None else None
    parts = _csv_parts(body)
    if len(parts) > 31 and parts[30] and parts[31]:
        return f"{parts[30]} {parts[31]}"
    return None


def _summarize_products(probe_results: list[CandidateResult], checked_at: datetime) -> list[CandidateResult]:
    output: list[CandidateResult] = []
    for product in MISSING_PRODUCTS:
        product_results = [result for result in probe_results if result.product_code == product["product_code"]]
        ready = next((result for result in product_results if result.status == "ready_to_add"), None)
        if ready is not None:
            ready.rejected_candidates = [_candidate_summary(result) for result in product_results if result is not ready]
            output.append(ready)
            continue
        if product_results:
            best = product_results[0]
            best.rejected_candidates = [_candidate_summary(result) for result in product_results]
            output.append(best)
            continue
        output.append(
            CandidateResult(
                product_code=product["product_code"],
                title=product["title"],
                status="not_found",
                source_code="current_price_source",
                endpoint=None,
                params={},
                external_code=None,
                parser_type=None,
                response_prefix=None,
                price_path=None,
                price_index=None,
                sample_price=None,
                parsed_name=None,
                observed_text=None,
                content_type=None,
                bytes_size=None,
                probe_status="not_checked",
                notes=_not_found_notes(product["product_code"]),
                checked_at=checked_at.isoformat(),
            )
        )
    return output


def _candidate_result(
    candidate: DiscoveryCandidate,
    checked_at: datetime,
    status: DiscoveryStatus,
    probe_status: CandidateProbeStatus,
    *,
    sample_price: float | None = None,
    parsed_name: str | None = None,
    observed_text: str | None = None,
    content_type: str | None = None,
    bytes_size: int | None = None,
    notes: str,
) -> CandidateResult:
    return CandidateResult(
        product_code=candidate.product_code,
        title=candidate.title,
        status=status,
        source_code=candidate.source_code,
        endpoint=candidate.endpoint,
        params=candidate.params,
        external_code=candidate.external_code,
        parser_type=candidate.parser_type,
        response_prefix=candidate.response_prefix,
        price_path=list(candidate.price_path) if candidate.price_path else None,
        price_index=candidate.price_index,
        sample_price=sample_price,
        parsed_name=parsed_name,
        observed_text=observed_text,
        content_type=content_type,
        bytes_size=bytes_size,
        probe_status=probe_status,
        notes=notes,
        checked_at=checked_at.isoformat(),
    )


def _candidate_summary(result: CandidateResult) -> dict[str, Any]:
    return {
        "external_code": result.external_code,
        "probe_status": result.probe_status,
        "parsed_name": result.parsed_name,
        "sample_price": result.sample_price,
        "bytes_size": result.bytes_size,
        "notes": result.notes,
    }


def _not_found_notes(product_code: str) -> str:
    if product_code == "sunflower_oil":
        return (
            "No reliable Jijinhao/Cngold instrument code was found during safe discovery. "
            "Mysteel has public sunflower oil market pages, but that is a different source and needs manual review."
        )
    if product_code == "sunflower_meal":
        return (
            "No reliable Jijinhao/Cngold instrument code was found during safe discovery. "
            "Oilchem has public sunflower meal pages, but that is a different source and needs manual review."
        )
    return "No reliable candidate was found."


def _strip_prefix(text: str, prefix: str) -> str:
    stripped = text.strip()
    if not stripped.startswith(prefix):
        raise PriceParseError(f"missing response_prefix: {prefix!r}")
    body = stripped[len(prefix) :].strip()
    if body.endswith(";"):
        body = body[:-1].strip()
    return body


def _csv_parts(body: str) -> list[str]:
    if (body.startswith('"') and body.endswith('"')) or (body.startswith("'") and body.endswith("'")):
        body = body[1:-1]
    return [part.strip() for part in next(csv.reader([body]))]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _render_report(results: list[CandidateResult], created_at: datetime) -> str:
    lines = [
        "# Price Instrument Discovery Report",
        "",
        f"Created: {created_at.isoformat()}",
        "",
        "## Current Working Products",
        "",
    ]
    for instrument in CURRENT_PRICE_INSTRUMENTS:
        lines.append(
            f"- `{instrument.product_code}`: `{instrument.external_code}`, `{instrument.parser_type}`, `{instrument.endpoint}`"
        )
    lines.extend(["", "## Missing Products", ""])
    for result in results:
        lines.extend(
            [
                f"### {result.product_code}",
                "",
                f"- title: {result.title}",
                f"- status: {result.status}",
                f"- source_code: {result.source_code}",
                f"- endpoint: {result.endpoint or 'not_found'}",
                f"- external_code: {result.external_code or 'not_found'}",
                f"- parser_type: {result.parser_type or 'not_found'}",
                f"- response_prefix: {result.response_prefix or 'not_found'}",
                f"- price_path: {'.'.join(result.price_path) if result.price_path else 'not_found'}",
                f"- price_index: {result.price_index if result.price_index is not None else 'not_found'}",
                f"- sample_price: {result.sample_price if result.sample_price is not None else 'not_found'}",
                f"- parsed_name: {result.parsed_name or 'not_found'}",
                f"- content_type: {result.content_type or 'not_found'}",
                f"- bytes_size: {result.bytes_size if result.bytes_size is not None else 'not_found'}",
                f"- observed_text: {result.observed_text or 'not_found'}",
                f"- notes: {result.notes}",
                "",
            ]
        )
        if result.rejected_candidates:
            lines.append("Rejected candidates:")
            for rejected in result.rejected_candidates:
                lines.append(
                    f"- `{rejected['external_code']}`: {rejected['probe_status']}, "
                    f"name={rejected['parsed_name']}, price={rejected['sample_price']}, notes={rejected['notes']}"
                )
            lines.append("")
    lines.extend(
        [
            "## Recommendation",
            "",
            "- `soybean_meal`: ready_to_add only after Phase 4.1 confirmation; do not add it automatically in Phase 4.0.",
            "- `sunflower_oil`: not_found in the current Jijinhao/Cngold source; evaluate a separate source such as Mysteel manually.",
            "- `sunflower_meal`: not_found in the current Jijinhao/Cngold source; evaluate a separate source such as Oilchem manually.",
            "",
            "This discovery did not write to production database tables, did not save production raw_responses, and did not change schedulers.",
            "",
            "Reference pages checked manually:",
            "- https://m.quheqihuo.com/quote/dce-mm.html",
            "- https://www.mysteel.com/zta/kuihuaziyou/",
            "- https://ncp.oilchem.net/ncp/Sunflower-meal.shtml",
            "",
        ]
    )
    return "\n".join(lines)
