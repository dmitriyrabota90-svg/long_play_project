from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ParserType = Literal["json", "csv"]


@dataclass(frozen=True)
class CurrentPriceInstrument:
    product_code: str
    external_code: str
    endpoint: str
    params: dict[str, str]
    parser_type: ParserType
    response_prefix: str
    currency: str
    unit: str
    source_note: str
    price_path: tuple[str, ...] | None = None
    price_index: int | None = None


CURRENT_PRICE_INSTRUMENTS: tuple[CurrentPriceInstrument, ...] = (
    CurrentPriceInstrument(
        product_code="rapeseed_oil",
        external_code="JO_166042",
        endpoint="https://api.jijinhao.com/quoteCenter/realTime.htm",
        params={"codes": "JO_166042"},
        parser_type="json",
        response_prefix="var quote_json = ",
        price_path=("JO_166042", "q5"),
        currency="CNY",
        unit="metric_ton",
        source_note="Jijinhao current quote, rapeseed oil.",
    ),
    CurrentPriceInstrument(
        product_code="soybean_oil",
        external_code="JO_165951",
        endpoint="https://api.jijinhao.com/sQuoteCenter/realTime.htm",
        params={"codes": "JO_165951"},
        parser_type="csv",
        response_prefix="var hq_str_JO_165951 = ",
        price_index=3,
        currency="CNY",
        unit="metric_ton",
        source_note="Jijinhao current quote, soybean oil.",
    ),
    CurrentPriceInstrument(
        product_code="rapeseed_meal",
        external_code="JO_166106",
        endpoint="https://api.jijinhao.com/sQuoteCenter/realTime.htm",
        params={"codes": "JO_166106"},
        parser_type="csv",
        response_prefix="var hq_str_JO_166106 = ",
        price_index=3,
        currency="CNY",
        unit="metric_ton",
        source_note="Jijinhao current quote, rapeseed meal.",
    ),
    CurrentPriceInstrument(
        product_code="soybean_meal",
        external_code="JO_165938",
        endpoint="https://api.jijinhao.com/quoteCenter/realTime.htm",
        params={"codes": "JO_165938"},
        parser_type="json",
        response_prefix="var quote_json = ",
        price_path=("JO_165938", "q5"),
        currency="CNY",
        unit="metric_ton",
        source_note="Jijinhao current quote, soybean meal.",
    ),
)


CURRENT_PRICE_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; commodity-dataset-builder/0.1; +https://example.local)",
    "Accept": "*/*",
    "Accept-Language": "ru,en;q=0.9",
    "Referer": "https://m.cngold.org//",
}
