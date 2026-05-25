from __future__ import annotations

SOURCE_CODE = "cbr_fx"
COLLECTOR_NAME = "cbr_fx_collector"
PARSER_VERSION = "cbr_fx_v1"
ENDPOINT = "https://www.cbr.ru/scripts/XML_daily.asp"
CURRENCIES = ("USD", "EUR", "CNY")
QUOTE_CURRENCY = "RUB"
REQUEST_TIMEOUT = 20.0
HEADERS = {
    "User-Agent": "commodity-dataset-builder/0.1 (+https://github.com/dmitriyrabota90-svg/long_play_project)",
    "Accept": "application/xml,text/xml,*/*",
    "Accept-Language": "ru,en;q=0.9",
}
