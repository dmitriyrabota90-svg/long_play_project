from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from app.collectors.prices.current_price_config import CURRENT_PRICE_HEADERS, CURRENT_PRICE_INSTRUMENTS
from app.discovery.price_instruments import BUILT_IN_CANDIDATES


AuditMode = Literal["inventory", "check-known", "search-keywords"]

SOURCE_NAME = "cngold_jijinhao"
OUTPUT_DIR = Path("diagnostics/chinese_source_audit")


@dataclass(frozen=True)
class EndpointCapability:
    data_type: str
    endpoint: str
    status: str
    usefulness_for_dataset: str
    risk: str
    recommendation: str
    notes: str
    parser_type: str | None = None
    response_prefix: str | None = None


@dataclass(frozen=True)
class KnownInstrument:
    product_code: str
    title_ru: str
    title_zh: str
    external_code: str
    endpoint: str
    parser_type: str
    response_prefix: str
    price_path_or_index: str
    status: str
    source: str


@dataclass(frozen=True)
class ProductCandidate:
    product_code: str
    title_ru: str
    title_zh: str
    external_code: str | None
    page: str | None
    endpoint: str | None
    status: str
    recommendation: str
    notes: str


@dataclass
class ProbeResult:
    name: str
    endpoint: str
    status: str
    http_status: int | None = None
    content_type: str | None = None
    bytes_size: int | None = None
    sample: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ChineseSourceAudit:
    source: str
    mode: str
    checked_at: str
    known_endpoints: list[EndpointCapability]
    known_instruments: list[KnownInstrument]
    product_candidates: list[ProductCandidate]
    data_capabilities: list[EndpointCapability]
    probes: list[ProbeResult]
    recommendations: list[str]
    telegram_bot_findings: list[str]
    search_keywords_status: str = "not_supported"


TITLE_RU_BY_PRODUCT = {
    "rapeseed_oil": "Рапсовое масло",
    "soybean_oil": "Соевое масло",
    "rapeseed_meal": "Рапсовый шрот",
    "soybean_meal": "Соевый шрот",
}

TITLE_ZH_BY_PRODUCT = {
    "rapeseed_oil": "菜籽油主力",
    "soybean_oil": "豆油主力",
    "rapeseed_meal": "菜籽粕主力",
    "soybean_meal": "豆粕主力",
}


def build_audit(mode: AuditMode, *, timeout: float = 12.0, http_client: httpx.Client | None = None) -> ChineseSourceAudit:
    checked_at = datetime.now(timezone.utc).isoformat()
    probes: list[ProbeResult] = []
    if mode == "check-known":
        owns_client = http_client is None
        client = http_client or httpx.Client(follow_redirects=True)
        try:
            probes = _run_known_probes(client, timeout=timeout)
        finally:
            if owns_client:
                client.close()
    elif mode == "search-keywords":
        probes = [
            ProbeResult(
                name="search-keywords",
                endpoint="not_supported",
                status="not_supported",
                error="Keyword search is intentionally not implemented to avoid crawler-like behavior.",
            )
        ]

    return ChineseSourceAudit(
        source=SOURCE_NAME,
        mode=mode,
        checked_at=checked_at,
        known_endpoints=known_endpoints(),
        known_instruments=known_instruments(),
        product_candidates=product_candidates(),
        data_capabilities=data_capabilities(),
        probes=probes,
        recommendations=recommendations(),
        telegram_bot_findings=telegram_bot_findings(),
        search_keywords_status="not_supported" if mode == "search-keywords" else "not_run",
    )


def write_audit_outputs(audit: ChineseSourceAudit, output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "chinese_source_capabilities.json").write_text(
        json.dumps(_audit_to_json(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "CHINESE_SOURCE_CAPABILITY_REPORT.md").write_text(render_report(audit), encoding="utf-8")


def known_endpoints() -> list[EndpointCapability]:
    return [
        EndpointCapability(
            data_type="current_prices",
            endpoint="https://api.jijinhao.com/quoteCenter/realTime.htm",
            status="ready_to_collect",
            usefulness_for_dataset="high",
            risk="low",
            recommendation="Use for confirmed JSON quote_json instruments.",
            notes="Current JSON quote endpoint used by rapeseed_oil and soybean_meal.",
            parser_type="json",
            response_prefix="var quote_json = ",
        ),
        EndpointCapability(
            data_type="current_prices",
            endpoint="https://api.jijinhao.com/sQuoteCenter/realTime.htm",
            status="ready_to_collect",
            usefulness_for_dataset="high",
            risk="low",
            recommendation="Use for confirmed CSV-like hq_str instruments.",
            notes="Current CSV-like quote endpoint used by soybean_oil and rapeseed_meal.",
            parser_type="csv",
            response_prefix="var hq_str_{code} = ",
        ),
        EndpointCapability(
            data_type="historical_prices",
            endpoint="https://api.jijinhao.com/quoteCenter/historys.htm",
            status="needs_manual_check",
            usefulness_for_dataset="high",
            risk="medium",
            recommendation="Prototype a separate historical OHLC collector with conservative pagination.",
            notes="Compact historical JSON-like endpoint observed with q1/q2/q3/q4/q60/q62/time fields.",
            parser_type="json",
            response_prefix="var quote_json = ",
        ),
        EndpointCapability(
            data_type="historical_prices",
            endpoint="https://api.jijinhao.com/sQuoteCenter/kDataList.htm",
            status="needs_manual_check",
            usefulness_for_dataset="high",
            risk="medium",
            recommendation="Do not call broadly; responses can be large and need pagination/retention policy.",
            notes="Daily OHLC endpoint discovered in public chart JS; one product response was about 1.4 MB.",
            parser_type="json",
            response_prefix="var  KLC_KL = ",
        ),
        EndpointCapability(
            data_type="intraday_prices",
            endpoint="https://api.jijinhao.com/sQuoteCenter/todayMin.htm",
            status="needs_manual_check",
            usefulness_for_dataset="medium",
            risk="medium",
            recommendation="Useful for market microstructure, but not needed before daily dataset export.",
            notes="Minute-level current session endpoint discovered in public chart JS.",
            parser_type="json",
            response_prefix="var hq_str_ml = ",
        ),
        EndpointCapability(
            data_type="intraday_prices",
            endpoint="https://api.jijinhao.com/sQuoteCenter/fourDaysMin.htm",
            status="needs_manual_check",
            usefulness_for_dataset="medium",
            risk="medium",
            recommendation="Use only after defining storage volume and sampling needs.",
            notes="Recent multi-day minute endpoint discovered in public chart JS.",
            parser_type="json",
            response_prefix="var KLC_ML = ",
        ),
        EndpointCapability(
            data_type="product_pages",
            endpoint="https://m.quheqihuo.com/quote/dce-mm.html",
            status="ready_for_discovery",
            usefulness_for_dataset="medium",
            risk="medium",
            recommendation="Use manually to discover pages/codes; do not build a crawler.",
            notes="Product pages embed JO codes and links to related futures/news pages.",
            parser_type="html_js",
            response_prefix=None,
        ),
    ]


def known_instruments() -> list[KnownInstrument]:
    instruments: list[KnownInstrument] = []
    for instrument in CURRENT_PRICE_INSTRUMENTS:
        path_or_index = ".".join(instrument.price_path or ()) if instrument.price_path else str(instrument.price_index)
        instruments.append(
            KnownInstrument(
                product_code=instrument.product_code,
                title_ru=TITLE_RU_BY_PRODUCT.get(instrument.product_code, instrument.product_code),
                title_zh=TITLE_ZH_BY_PRODUCT.get(instrument.product_code, ""),
                external_code=instrument.external_code,
                endpoint=instrument.endpoint,
                parser_type=instrument.parser_type,
                response_prefix=instrument.response_prefix,
                price_path_or_index=path_or_index,
                status="collecting_in_production",
                source="dataset-builder",
            )
        )
    return instruments


def product_candidates() -> list[ProductCandidate]:
    candidates = [
        ProductCandidate(
            product_code="soybean_meal",
            title_ru="Соевый шрот",
            title_zh="豆粕",
            external_code="JO_165938",
            page="https://m.quheqihuo.com/quote/dce-mm.html",
            endpoint="https://api.jijinhao.com/quoteCenter/realTime.htm",
            status="collecting_in_production",
            recommendation="Already added in Phase 4.1; monitor scheduled collection quality.",
            notes="Discovery confirmed parsed name 豆粕主力 and price path JO_165938.q5.",
        ),
        ProductCandidate(
            product_code="sunflower_oil",
            title_ru="Подсолнечное масло",
            title_zh="葵花籽油 / 葵花油",
            external_code=None,
            page=None,
            endpoint=None,
            status="not_found",
            recommendation="Do not add to current source; investigate separate Chinese spot/industry sources.",
            notes="No reliable Jijinhao/Cngold futures/current quote instrument found.",
        ),
        ProductCandidate(
            product_code="sunflower_meal",
            title_ru="Подсолнечный шрот",
            title_zh="葵花粕 / 葵花籽粕",
            external_code=None,
            page=None,
            endpoint=None,
            status="not_found",
            recommendation="Do not add to current source; investigate separate oilseed meal industry sources.",
            notes="No reliable Jijinhao/Cngold futures/current quote instrument found.",
        ),
        ProductCandidate(
            product_code="palm_oil",
            title_ru="Пальмовое масло",
            title_zh="棕榈油",
            external_code=None,
            page="https://m.quheqihuo.com/quote/dce-pm.html",
            endpoint=None,
            status="needs_manual_check",
            recommendation="Useful related oil market; confirm JO code/page stability before adding.",
            notes="Related market link observed on soybean meal futures page.",
        ),
        ProductCandidate(
            product_code="corn",
            title_ru="Кукуруза",
            title_zh="玉米",
            external_code=None,
            page="https://m.quheqihuo.com/quote/dce-cm.html",
            endpoint=None,
            status="needs_manual_check",
            recommendation="Potential related feed/grain feature, not a core oilseed product.",
            notes="Related agricultural futures link observed on soybean meal futures page.",
        ),
        ProductCandidate(
            product_code="crude_oil",
            title_ru="Сырая нефть",
            title_zh="原油",
            external_code=None,
            page="https://m.quheqihuo.com/quote/ine-scm.html",
            endpoint=None,
            status="needs_manual_check",
            recommendation="Potential macro/energy feature; separate source design needed.",
            notes="Related energy futures link observed on soybean meal futures page.",
        ),
    ]

    for discovery_candidate in BUILT_IN_CANDIDATES:
        if discovery_candidate.external_code in {"JO_165950", "JO_165952"}:
            candidates.append(
                ProductCandidate(
                    product_code=discovery_candidate.product_code,
                    title_ru=discovery_candidate.title,
                    title_zh="豆粕",
                    external_code=discovery_candidate.external_code,
                    page=None,
                    endpoint=discovery_candidate.endpoint,
                    status="rejected",
                    recommendation="Do not use.",
                    notes=discovery_candidate.notes,
                )
            )
    return candidates


def data_capabilities() -> list[EndpointCapability]:
    return [
        *known_endpoints(),
        EndpointCapability(
            data_type="commodity_catalog",
            endpoint="https://m.quheqihuo.com/quote/dce-mm.html",
            status="needs_manual_check",
            usefulness_for_dataset="medium",
            risk="medium",
            recommendation="Use as a manual discovery aid for pages/codes/categories only.",
            notes="Page contains agricultural futures links such as 豆油, 棕榈油, 菜籽油, 菜籽粕, 玉米, 苹果, 白糖, 棉花.",
            parser_type="html",
        ),
        EndpointCapability(
            data_type="commodity_news",
            endpoint="https://m.quheqihuo.com/news/ and https://m.quheqihuo.com/qhyb/",
            status="needs_manual_check",
            usefulness_for_dataset="medium",
            risk="high",
            recommendation="Do not add before core price/history/export pipeline is stable.",
            notes="News/research links are visible on product pages; article parsing, rights, duplication, and relevance need review.",
            parser_type="html",
        ),
        EndpointCapability(
            data_type="related_energy_prices",
            endpoint="https://m.quheqihuo.com/quote/ine-scm.html",
            status="needs_manual_check",
            usefulness_for_dataset="medium",
            risk="medium",
            recommendation="Consider later as macro feature source after oilseed coverage.",
            notes="Crude oil futures page link observed; code not confirmed in this phase.",
            parser_type="html_js",
        ),
        EndpointCapability(
            data_type="related_oilseed_prices",
            endpoint="https://m.quheqihuo.com/quote/dce-pm.html",
            status="needs_manual_check",
            usefulness_for_dataset="high",
            risk="medium",
            recommendation="Investigate palm oil after sunflower source decision.",
            notes="Palm oil is a useful related vegetable-oil market, but instrument code still needs confirmation.",
            parser_type="html_js",
        ),
    ]


def recommendations() -> list[str]:
    return [
        "Do not add new production collectors in Phase 4.2; this is source mapping only.",
        "First production follow-up should be a historical daily OHLC prototype for already confirmed instruments, using quoteCenter/historys.htm with strict limits.",
        "Use product pages manually for discovery; do not crawl full category pages aggressively.",
        "Keep news/research pages out of production until rights, relevance, deduplication, and language processing are designed.",
        "Sunflower oil and sunflower meal remain not_found in the current source and should not be guessed.",
    ]


def telegram_bot_findings() -> list[str]:
    return [
        "Old Telegram bot used products.py with three Jijinhao instruments: JO_166042, JO_165951, JO_166106.",
        "Headers included User-Agent, Accept */*, Accept-Language ru/en, and Referer https://m.cngold.org//.",
        "Only current prices were fetched from the remote API; historical charts in the bot were built from local SQLite snapshots.",
        "No external history/news/catalog endpoint was implemented in the bot.",
        "TELEGRAM_TOKEN is referenced in the old bot environment, but token values were not printed.",
    ]


def _run_known_probes(client: httpx.Client, *, timeout: float) -> list[ProbeResult]:
    probes: list[ProbeResult] = []
    for instrument in CURRENT_PRICE_INSTRUMENTS:
        probes.append(_probe_current_instrument(client, instrument, timeout=timeout))
    probes.append(
        _probe_historys(
            client,
            name="historys_soybean_meal",
            code="JO_165938",
            timeout=timeout,
        )
    )
    return probes


def _probe_current_instrument(client: httpx.Client, instrument: Any, *, timeout: float) -> ProbeResult:
    try:
        response = client.get(instrument.endpoint, params=instrument.params, headers=CURRENT_PRICE_HEADERS, timeout=timeout)
        text = response.text
        sample = {
            "external_code": instrument.external_code,
            "prefix_found": text.strip().startswith(instrument.response_prefix),
        }
        if instrument.parser_type == "json":
            sample["parser_type"] = "json"
            sample["sample_price_path"] = ".".join(instrument.price_path or ())
        else:
            sample["parser_type"] = "csv"
            sample["sample_price_index"] = instrument.price_index
        return ProbeResult(
            name=f"current_{instrument.product_code}",
            endpoint=instrument.endpoint,
            status="ok" if response.status_code == 200 and sample["prefix_found"] else "needs_review",
            http_status=response.status_code,
            content_type=response.headers.get("content-type"),
            bytes_size=len(response.content),
            sample=sample,
        )
    except httpx.HTTPError as exc:
        return ProbeResult(
            name=f"current_{instrument.product_code}",
            endpoint=instrument.endpoint,
            status="error",
            error=str(exc),
        )


def _probe_historys(client: httpx.Client, *, name: str, code: str, timeout: float) -> ProbeResult:
    endpoint = "https://api.jijinhao.com/quoteCenter/historys.htm"
    params = {"codes": code, "style": "3", "pageSize": "5", "currentPage": "1"}
    try:
        response = client.get(endpoint, params=params, headers=CURRENT_PRICE_HEADERS, timeout=timeout)
        sample = _parse_historys_sample(response.text, code)
        return ProbeResult(
            name=name,
            endpoint=endpoint,
            status="ok" if response.status_code == 200 and sample.get("rows_count", 0) > 0 else "needs_review",
            http_status=response.status_code,
            content_type=response.headers.get("content-type"),
            bytes_size=len(response.content),
            sample=sample,
        )
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return ProbeResult(name=name, endpoint=endpoint, status="error", error=str(exc))


def _parse_historys_sample(text: str, code: str) -> dict[str, Any]:
    body = _strip_js_assignment(text, "var quote_json = ")
    root = json.loads(body)
    data = root.get("data", {})
    rows = data.get(code, [])
    first = rows[0] if rows else {}
    return {
        "code": code,
        "product_name": data.get(f"{code}_productName"),
        "unit": data.get(f"{code}_unit"),
        "rows_count": len(rows),
        "fields": sorted(first.keys()) if isinstance(first, dict) else [],
        "first_row": {key: first.get(key) for key in ("q1", "q2", "q3", "q4", "q60", "q62", "time")} if first else {},
    }


def _strip_js_assignment(text: str, prefix: str) -> str:
    stripped = text.strip()
    if not stripped.startswith(prefix):
        raise ValueError(f"missing JS assignment prefix: {prefix}")
    body = stripped[len(prefix) :].strip()
    if body.endswith(";"):
        body = body[:-1].strip()
    return body


def render_report(audit: ChineseSourceAudit) -> str:
    lines = [
        "# Chinese Source Capability Report",
        "",
        f"Created: {audit.checked_at}",
        f"Mode: `{audit.mode}`",
        "",
        "## Executive Summary",
        "",
        "The Cngold/Jijinhao source is useful for confirmed current futures quotes and appears to expose historical OHLC and intraday chart endpoints. It should be treated as a market-data source, not a broad news or fundamentals source yet.",
        "",
        "No production collectors or database tables were modified by this audit.",
        "",
        "## Telegram Bot Findings",
        "",
    ]
    lines.extend(f"- {item}" for item in audit.telegram_bot_findings)
    lines.extend(["", "## Confirmed Endpoints", ""])
    for endpoint in audit.known_endpoints:
        lines.append(f"- `{endpoint.endpoint}`: {endpoint.data_type}, status={endpoint.status}, risk={endpoint.risk}. {endpoint.notes}")
    lines.extend(["", "## Current Production Instruments", ""])
    lines.append("| product_code | title_ru | title_zh | external_code | endpoint | parser_type | price_path/index | status |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for instrument in audit.known_instruments:
        lines.append(
            f"| {instrument.product_code} | {instrument.title_ru} | {instrument.title_zh} | {instrument.external_code} | {instrument.endpoint} | {instrument.parser_type} | {instrument.price_path_or_index} | {instrument.status} |"
        )
    lines.extend(["", "## Product Candidates", ""])
    for candidate in audit.product_candidates:
        lines.append(
            f"- `{candidate.product_code}` ({candidate.title_zh}): status={candidate.status}, code={candidate.external_code or 'not_found'}, recommendation={candidate.recommendation}"
        )
    lines.extend(["", "## Data Capability Matrix", ""])
    lines.append("| data_type | endpoint/page | status | usefulness_for_dataset | risk | recommendation |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for capability in audit.data_capabilities:
        lines.append(
            f"| {capability.data_type} | {capability.endpoint} | {capability.status} | {capability.usefulness_for_dataset} | {capability.risk} | {capability.recommendation} |"
        )
    lines.extend(["", "## Probe Results", ""])
    if audit.probes:
        for probe in audit.probes:
            lines.append(
                f"- `{probe.name}`: status={probe.status}, http={probe.http_status}, bytes={probe.bytes_size}, endpoint={probe.endpoint}, sample={json.dumps(probe.sample, ensure_ascii=False)}"
            )
            if probe.error:
                lines.append(f"  error: {probe.error}")
    else:
        lines.append("- No network probes were run in this mode.")
    lines.extend(["", "## Recommendations", ""])
    lines.extend(f"- {item}" for item in audit.recommendations)
    lines.extend(
        [
            "",
            "## Not Found / Do Not Use Yet",
            "",
            "- `sunflower_oil`: not found in current Cngold/Jijinhao quote source.",
            "- `sunflower_meal`: not found in current Cngold/Jijinhao quote source.",
            "- Keyword search is not implemented to avoid crawler-like behavior.",
            "",
        ]
    )
    return "\n".join(lines)


def _audit_to_json(audit: ChineseSourceAudit) -> dict[str, Any]:
    return {
        "source": audit.source,
        "mode": audit.mode,
        "checked_at": audit.checked_at,
        "known_endpoints": [asdict(item) for item in audit.known_endpoints],
        "known_instruments": [asdict(item) for item in audit.known_instruments],
        "product_candidates": [asdict(item) for item in audit.product_candidates],
        "data_capabilities": [asdict(item) for item in audit.data_capabilities],
        "probes": [asdict(item) for item in audit.probes],
        "recommendations": audit.recommendations,
        "telegram_bot_findings": audit.telegram_bot_findings,
        "search_keywords_status": audit.search_keywords_status,
    }
