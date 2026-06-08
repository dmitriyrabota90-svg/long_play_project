from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode


SOURCE_CODE = "fred_energy_prices"
COLLECTOR_NAME = "fred_energy_prices_collector"
PARSER_VERSION = "fred_energy_v1"
ENDPOINT = "https://fred.stlouisfed.org/graph/fredgraph.csv"
REQUEST_TIMEOUT = 30.0
TRANSIENT_RETRIES = 1
RETRY_DELAY_SECONDS = 1.0

HEADERS = {
    "User-Agent": "commodity-dataset-builder/0.1 (+https://github.com/dmitriyrabota90-svg/long_play_project)",
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "en,ru;q=0.9",
}


@dataclass(frozen=True)
class FredEnergySeries:
    instrument_code: str
    external_id: str
    instrument_name: str
    instrument_category: str
    frequency: str
    currency: str | None
    unit: str
    unit_note: str | None = None
    frequency_note: str | None = None


FRED_ENERGY_SERIES: tuple[FredEnergySeries, ...] = (
    FredEnergySeries(
        instrument_code="DCOILBRENTEU",
        external_id="DCOILBRENTEU",
        instrument_name="Crude Oil Prices: Brent - Europe",
        instrument_category="crude_oil",
        frequency="daily",
        currency="USD",
        unit="USD/barrel",
    ),
    FredEnergySeries(
        instrument_code="DCOILWTICO",
        external_id="DCOILWTICO",
        instrument_name="Crude Oil Prices: West Texas Intermediate",
        instrument_category="crude_oil",
        frequency="daily",
        currency="USD",
        unit="USD/barrel",
    ),
    FredEnergySeries(
        instrument_code="DHHNGSP",
        external_id="DHHNGSP",
        instrument_name="Henry Hub Natural Gas Spot Price",
        instrument_category="natural_gas",
        frequency="daily",
        currency="USD",
        unit="USD/MMBtu",
    ),
    FredEnergySeries(
        instrument_code="GASDESW",
        external_id="GASDESW",
        instrument_name="US Diesel Proxy / FRED Series GASDESW",
        instrument_category="diesel",
        frequency="weekly",
        currency="USD",
        unit="source_unit",
        unit_note="Verify source unit before feature integration; stored as source_unit in Phase 6.1D.",
        frequency_note="FRED source cadence is weekly; exact source-period semantics need verification.",
    ),
)

FRED_ENERGY_SERIES_BY_ID: dict[str, FredEnergySeries] = {
    item.external_id: item for item in FRED_ENERGY_SERIES
}


def fred_csv_params(series_id: str, *, from_date: date | None = None, to_date: date | None = None) -> dict[str, str]:
    params = {"id": series_id}
    if from_date is not None:
        params["cosd"] = from_date.isoformat()
    if to_date is not None:
        params["coed"] = to_date.isoformat()
    return params


def fred_csv_url(series_id: str, *, from_date: date | None = None, to_date: date | None = None) -> str:
    return f"{ENDPOINT}?{urlencode(fred_csv_params(series_id, from_date=from_date, to_date=to_date))}"
