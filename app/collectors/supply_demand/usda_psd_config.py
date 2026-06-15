from __future__ import annotations

from dataclasses import dataclass

SOURCE_CODE = "usda_psd"
COLLECTOR_NAME = "usda_psd"
PARSER_VERSION = "usda_psd_v1"
SOURCE_SCHEMA_STATUS = "needs_verification"

BASE_URL = "https://apps.fas.usda.gov/PSDOnlineApi/api"
DOWNLOADABLE_DATASET_ENDPOINT = f"{BASE_URL}/downloadableData/GetDatasetContents"
OILSEEDS_COMMODITY_GROUP_CODE = "oil"
OILSEEDS_DATASET_FILENAME = "psd_oilseeds_csv.zip"
REQUEST_TIMEOUT = 20.0
DEFAULT_MAXRECORDS = 100
MAX_MAXRECORDS = 500
MAX_MARKETING_YEARS_PER_RUN = 3

HEADERS = {
    "User-Agent": "commodity-dataset-builder/0.1 (+https://github.com/dmitriyrabota90-svg/long_play_project)",
    "Accept": "application/json,text/plain,*/*",
}

SUPPORTED_METRICS = (
    "production_volume",
    "domestic_consumption",
    "feed_use",
    "crush_volume",
    "exports_volume",
    "imports_volume",
    "beginning_stocks",
    "ending_stocks",
    "stock_to_use_ratio",
    "planted_area",
    "harvested_area",
    "yield",
)


@dataclass(frozen=True)
class PsdCommodityFamily:
    code: str
    commodity_family: str
    product_code: str | None
    display_name: str


@dataclass(frozen=True)
class PsdDownloadableCommodity:
    source_commodity_code: str
    source_commodity_name: str
    commodity_family: str
    product_code: str


SUPPORTED_COMMODITY_FAMILIES = (
    PsdCommodityFamily("soybean", "soybean", None, "Soybean context"),
    PsdCommodityFamily("soybean_oil", "soybean", "soybean_oil", "Soybean oil"),
    PsdCommodityFamily("soybean_meal", "soybean", "soybean_meal", "Soybean meal"),
    PsdCommodityFamily("rapeseed_canola", "rapeseed_canola", None, "Rapeseed / canola context"),
    PsdCommodityFamily("rapeseed_canola_oil", "rapeseed_canola", "rapeseed_oil", "Rapeseed / canola oil"),
    PsdCommodityFamily("rapeseed_canola_meal", "rapeseed_canola", "rapeseed_meal", "Rapeseed / canola meal"),
)

COMMODITY_FAMILIES_BY_CODE = {item.code: item for item in SUPPORTED_COMMODITY_FAMILIES}

DOWNLOADABLE_OILSEEDS_COMMODITIES = (
    PsdDownloadableCommodity("0813100", "Meal, Soybean", "soybean", "soybean_meal"),
    PsdDownloadableCommodity("0813600", "Meal, Rapeseed", "rapeseed_canola", "rapeseed_meal"),
    PsdDownloadableCommodity("4232000", "Oil, Soybean", "soybean", "soybean_oil"),
    PsdDownloadableCommodity("4239100", "Oil, Rapeseed", "rapeseed_canola", "rapeseed_oil"),
)
DOWNLOADABLE_OILSEEDS_COMMODITIES_BY_CODE = {
    item.source_commodity_code: item for item in DOWNLOADABLE_OILSEEDS_COMMODITIES
}


@dataclass(frozen=True)
class PsdCountry:
    code: str
    name: str


SUPPORTED_COUNTRIES = (
    PsdCountry("WLD", "World"),
    PsdCountry("USA", "United States"),
    PsdCountry("BRA", "Brazil"),
    PsdCountry("ARG", "Argentina"),
    PsdCountry("CAN", "Canada"),
    PsdCountry("CHN", "China"),
    PsdCountry("EU", "European Union"),
)

COUNTRIES_BY_CODE = {item.code: item for item in SUPPORTED_COUNTRIES}
COUNTRY_ALIASES = {
    "R00": COUNTRIES_BY_CODE["WLD"],
    "WORLD": COUNTRIES_BY_CODE["WLD"],
    "WORLD TOTAL": COUNTRIES_BY_CODE["WLD"],
    "ALL": COUNTRIES_BY_CODE["WLD"],
    "US": COUNTRIES_BY_CODE["USA"],
    "UNITED STATES": COUNTRIES_BY_CODE["USA"],
    "UNITED STATES OF AMERICA": COUNTRIES_BY_CODE["USA"],
    "BR": COUNTRIES_BY_CODE["BRA"],
    "BRAZIL": COUNTRIES_BY_CODE["BRA"],
    "AR": COUNTRIES_BY_CODE["ARG"],
    "ARGENTINA": COUNTRIES_BY_CODE["ARG"],
    "CA": COUNTRIES_BY_CODE["CAN"],
    "CANADA": COUNTRIES_BY_CODE["CAN"],
    "CN": COUNTRIES_BY_CODE["CHN"],
    "CHINA": COUNTRIES_BY_CODE["CHN"],
    "EUROPEAN UNION": COUNTRIES_BY_CODE["EU"],
    "EU-27": COUNTRIES_BY_CODE["EU"],
}
for _country in SUPPORTED_COUNTRIES:
    COUNTRY_ALIASES[_country.code] = _country


def resolve_commodity_family(value: str) -> PsdCommodityFamily:
    normalized = value.strip().lower().replace("-", "_")
    family = COMMODITY_FAMILIES_BY_CODE.get(normalized)
    if family is None:
        supported = ", ".join(sorted(COMMODITY_FAMILIES_BY_CODE))
        raise ValueError(f"unsupported USDA PSD commodity family: {value}; supported values: {supported}")
    return family


def resolve_country(value: str) -> PsdCountry:
    normalized = value.strip().upper()
    country = COUNTRY_ALIASES.get(normalized)
    if country is None:
        supported = ", ".join(sorted(COUNTRIES_BY_CODE))
        raise ValueError(f"unsupported USDA PSD country: {value}; supported codes: {supported}")
    return country


def is_supported_metric(value: str) -> bool:
    return value in SUPPORTED_METRICS


def usda_psd_live_probe_params(
    *,
    commodity_family: PsdCommodityFamily,
    country: PsdCountry,
    from_marketing_year: int,
    to_marketing_year: int,
    maxrecords: int,
) -> dict[str, str]:
    return {
        "dataSetName": OILSEEDS_DATASET_FILENAME,
    }
