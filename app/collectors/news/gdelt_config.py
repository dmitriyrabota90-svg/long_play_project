from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from urllib.parse import urlencode


SOURCE_CODE = "gdelt_2_1"
COLLECTOR_NAME = "gdelt_news"
PARSER_VERSION = "gdelt_news_v1"
ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
SOURCE_MODE = "ArtList"
REQUEST_TIMEOUT = 30.0
DEFAULT_MAXRECORDS = 25
MAX_MAXRECORDS = 100
MAX_DATE_RANGE_DAYS = 7

HEADERS = {
    "User-Agent": "commodity-dataset-builder/0.1 (+https://github.com/dmitriyrabota90-svg/long_play_project)",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en,ru;q=0.9",
}


@dataclass(frozen=True)
class GdeltQueryPreset:
    query_key: str
    query_string: str
    commodity_family: str
    affected_products: tuple[str, ...]
    language: str | None
    maxrecords_default: int
    reason_for_ml: str


GDELT_QUERY_PRESETS: tuple[GdeltQueryPreset, ...] = (
    GdeltQueryPreset(
        query_key="soybean",
        query_string='(soybean OR soybeans OR "soybean oil" OR "soybean meal")',
        commodity_family="soybean",
        affected_products=("soybean_oil", "soybean_meal"),
        language="English",
        maxrecords_default=DEFAULT_MAXRECORDS,
        reason_for_ml="Soybean crop, crush, oil, and meal news can move soybean oil and meal price expectations.",
    ),
    GdeltQueryPreset(
        query_key="rapeseed_canola",
        query_string='(rapeseed OR canola OR "canola oil" OR "rapeseed meal")',
        commodity_family="rapeseed",
        affected_products=("rapeseed_oil", "rapeseed_meal"),
        language="English",
        maxrecords_default=DEFAULT_MAXRECORDS,
        reason_for_ml="Rapeseed and canola market news can affect rapeseed oil and meal supply expectations.",
    ),
    GdeltQueryPreset(
        query_key="vegetable_oils",
        query_string='("vegetable oil" OR "palm oil" OR "edible oil")',
        commodity_family="vegetable_oils",
        affected_products=("soybean_oil", "rapeseed_oil"),
        language="English",
        maxrecords_default=DEFAULT_MAXRECORDS,
        reason_for_ml="Vegetable oil substitution and palm oil context can influence oilseed oil prices.",
    ),
    GdeltQueryPreset(
        query_key="grain_oilseed_policy",
        query_string='("export ban" OR "export quota" OR "import duty" OR "crop forecast" OR drought OR "Black Sea" OR biofuel)',
        commodity_family="policy_context",
        affected_products=("rapeseed_oil", "soybean_oil", "rapeseed_meal", "soybean_meal"),
        language="English",
        maxrecords_default=DEFAULT_MAXRECORDS,
        reason_for_ml="Policy, weather, logistics, and biofuel shocks can create market-wide context for oils and meals.",
    ),
)

GDELT_QUERY_PRESETS_BY_KEY: dict[str, GdeltQueryPreset] = {
    item.query_key: item for item in GDELT_QUERY_PRESETS
}


def gdelt_doc_params(
    *,
    query: str,
    from_date: date,
    to_date: date,
    maxrecords: int,
) -> dict[str, str]:
    return {
        "query": query,
        "mode": SOURCE_MODE,
        "format": "json",
        "maxrecords": str(maxrecords),
        "sort": "DateDesc",
        "startdatetime": _gdelt_datetime(from_date, time.min),
        "enddatetime": _gdelt_datetime(to_date, time(23, 59, 59)),
    }


def gdelt_doc_url(*, query: str, from_date: date, to_date: date, maxrecords: int) -> str:
    return f"{ENDPOINT}?{urlencode(gdelt_doc_params(query=query, from_date=from_date, to_date=to_date, maxrecords=maxrecords))}"


def get_query_preset(query_key: str) -> GdeltQueryPreset:
    try:
        return GDELT_QUERY_PRESETS_BY_KEY[query_key]
    except KeyError as exc:
        raise ValueError(f"unknown GDELT query_key: {query_key}") from exc


def is_known_query_key(query_key: str) -> bool:
    return query_key in GDELT_QUERY_PRESETS_BY_KEY


def _gdelt_datetime(value: date, clock_time: time) -> str:
    return f"{value:%Y%m%d}{clock_time:%H%M%S}"

