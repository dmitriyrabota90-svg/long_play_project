from __future__ import annotations

from dataclasses import dataclass

SOURCE_CODE = "usda_psd"
COLLECTOR_NAME = "usda_psd"
PARSER_VERSION = "usda_psd_v1"
SOURCE_SCHEMA_STATUS = "needs_verification"

BASE_URL = "https://apps.fas.usda.gov/psdonline"
DOWNLOADABLE_DATASET_ENDPOINT = f"{BASE_URL}/downloads/psd_oilseeds_csv.zip"
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
    "food_use",
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

EXPECTED_UNSUPPORTED_METRICS = {
    "total_supply": "aggregate_total_supply_not_feature_metric",
    "total_distribution": "aggregate_total_distribution_not_feature_metric",
    "industrial_dom._cons.": "industrial_use_split_not_modeled_yet",
    "feed_waste_dom._cons.": "feed_waste_split_not_modeled_yet",
    "extr._rate,_999.9999": "extraction_rate_not_modeled_yet",
}

USDA_PSD_METRIC_ALIASES = {
    "production": "production_volume",
    "production_volume": "production_volume",
    "domestic_consumption": "domestic_consumption",
    "domestic_use": "domestic_consumption",
    "dom_consumption": "domestic_consumption",
    "domestic_cons": "domestic_consumption",
    "total_domestic_consumption": "domestic_consumption",
    "total_dom_consumption": "domestic_consumption",
    "food_use": "food_use",
    "food": "food_use",
    "food_use_dom._cons.": "food_use",
    "feed_use": "feed_use",
    "feed": "feed_use",
    "crush": "crush_volume",
    "crush_volume": "crush_volume",
    "exports": "exports_volume",
    "ty_exports": "exports_volume",
    "my_exports": "exports_volume",
    "exports_volume": "exports_volume",
    "imports": "imports_volume",
    "ty_imports": "imports_volume",
    "my_imports": "imports_volume",
    "imports_volume": "imports_volume",
    "beginning_stocks": "beginning_stocks",
    "beginning_stock": "beginning_stocks",
    "ending_stocks": "ending_stocks",
    "ending_stock": "ending_stocks",
    "stock_to_use": "stock_to_use_ratio",
    "stock_to_use_ratio_pct": "stock_to_use_ratio",
    "stock_to_use_ratio": "stock_to_use_ratio",
    "planted_area": "planted_area",
    "area_planted": "planted_area",
    "harvested_area": "harvested_area",
    "area_harvested": "harvested_area",
    "yield": "yield",
    "yield_value": "yield",
}


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
    PsdCountry("US", "United States"),
    PsdCountry("BR", "Brazil"),
    PsdCountry("AR", "Argentina"),
    PsdCountry("CA", "Canada"),
    PsdCountry("CH", "China"),
    PsdCountry("EU", "European Union"),
    PsdCountry("IN", "India"),
    PsdCountry("MX", "Mexico"),
    PsdCountry("RS", "Russia"),
    PsdCountry("BL", "Bolivia"),
    PsdCountry("PA", "Paraguay"),
)

COUNTRIES_BY_CODE = {item.code: item for item in SUPPORTED_COUNTRIES}
COUNTRY_ALIASES = {
    "R00": COUNTRIES_BY_CODE["WLD"],
    "WORLD": COUNTRIES_BY_CODE["WLD"],
    "WORLD TOTAL": COUNTRIES_BY_CODE["WLD"],
    "ALL": COUNTRIES_BY_CODE["WLD"],
    "USA": COUNTRIES_BY_CODE["US"],
    "UNITED STATES": COUNTRIES_BY_CODE["US"],
    "UNITED STATES OF AMERICA": COUNTRIES_BY_CODE["US"],
    "BRA": COUNTRIES_BY_CODE["BR"],
    "BRAZIL": COUNTRIES_BY_CODE["BR"],
    "ARG": COUNTRIES_BY_CODE["AR"],
    "ARGENTINA": COUNTRIES_BY_CODE["AR"],
    "CAN": COUNTRIES_BY_CODE["CA"],
    "CANADA": COUNTRIES_BY_CODE["CA"],
    "CN": COUNTRIES_BY_CODE["CH"],
    "CHN": COUNTRIES_BY_CODE["CH"],
    "CHINA": COUNTRIES_BY_CODE["CH"],
    "EUROPEAN UNION": COUNTRIES_BY_CODE["EU"],
    "EU-27": COUNTRIES_BY_CODE["EU"],
    "INDIA": COUNTRIES_BY_CODE["IN"],
    "MEXICO": COUNTRIES_BY_CODE["MX"],
    "RUSSIA": COUNTRIES_BY_CODE["RS"],
    "BOLIVIA": COUNTRIES_BY_CODE["BL"],
    "PARAGUAY": COUNTRIES_BY_CODE["PA"],
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


def expected_unsupported_metric_reason(value: str) -> str | None:
    return EXPECTED_UNSUPPORTED_METRICS.get(value)


def normalize_usda_psd_metric(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return USDA_PSD_METRIC_ALIASES.get(normalized, normalized)


def normalize_usda_psd_column_key(value: str) -> str:
    characters = [char.lower() if char.isalnum() else "_" for char in value.strip()]
    normalized = "".join(characters)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def usda_psd_live_probe_params(
    *,
    commodity_family: PsdCommodityFamily,
    country: PsdCountry,
    from_marketing_year: int,
    to_marketing_year: int,
    maxrecords: int,
) -> dict[str, str]:
    return {}
