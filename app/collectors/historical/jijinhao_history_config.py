from __future__ import annotations

from dataclasses import dataclass

from app.collectors.prices.current_price_config import CURRENT_PRICE_HEADERS, CURRENT_PRICE_INSTRUMENTS


SOURCE_CODE = "jijinhao_historical_prices"
COLLECTOR_NAME = "jijinhao_historical_prices_collector"
PARSER_VERSION = "jijinhao_historys_v1"
ENDPOINT_ALIAS = "historys"
ENDPOINT = "https://api.jijinhao.com/quoteCenter/historys.htm"
REQUEST_TIMEOUT = 20.0
DEFAULT_DAYS = 30
MAX_DAYS = 30
BAR_TIMEFRAME = "daily"

HEADERS = CURRENT_PRICE_HEADERS


@dataclass(frozen=True)
class HistoricalPriceInstrument:
    product_code: str
    external_code: str
    currency: str
    unit: str


HISTORICAL_PRICE_INSTRUMENTS: tuple[HistoricalPriceInstrument, ...] = tuple(
    HistoricalPriceInstrument(
        product_code=item.product_code,
        external_code=item.external_code,
        currency=item.currency,
        unit=item.unit,
    )
    for item in CURRENT_PRICE_INSTRUMENTS
)


def historys_params(external_code: str, days: int) -> dict[str, str]:
    return {"codes": external_code, "style": "3", "pageSize": str(days), "currentPage": "1"}

