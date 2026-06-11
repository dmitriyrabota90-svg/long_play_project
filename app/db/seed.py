from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.logging import setup_logging
from app.db.models import Product, Source, WeatherRegion
from app.db.session import session_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductSeed:
    code: str
    name: str
    category: str
    unit: str = "metric_ton"
    currency_default: str = "USD"


@dataclass(frozen=True)
class SourceSeed:
    code: str
    name: str
    source_type: str
    base_url: str | None = None


@dataclass(frozen=True)
class WeatherRegionSeed:
    region_code: str
    region_name: str
    country: str
    country_code: str
    crop: str
    commodity_family: str
    role: str
    priority: str
    latitude: str
    longitude: str
    spatial_model: str
    aggregation_strategy: str
    reason_for_ml: str


PRODUCTS: tuple[ProductSeed, ...] = (
    ProductSeed("rapeseed_oil", "Рапсовое масло", "oil"),
    ProductSeed("soybean_oil", "Соевое масло", "oil"),
    ProductSeed("rapeseed_meal", "Рапсовый шрот", "meal"),
    ProductSeed("soybean_meal", "Соевый шрот", "meal"),
    ProductSeed("sunflower_oil", "Подсолнечное масло", "oil"),
    ProductSeed("sunflower_meal", "Подсолнечный шрот", "meal"),
)

SOURCES: tuple[SourceSeed, ...] = (
    SourceSeed("current_price_source", "Current price source", "price"),
    SourceSeed(
        "jijinhao_historical_prices",
        "Jijinhao Historical Prices",
        "price_history",
        "https://api.jijinhao.com/",
    ),
    SourceSeed(
        "world_bank_pink_sheet",
        "World Bank Pink Sheet",
        "benchmark",
        "https://www.worldbank.org/en/research/commodity-markets",
    ),
    SourceSeed(
        "fao_price_indices",
        "FAO Food Price Indices",
        "benchmark",
        "https://www.fao.org/worldfoodsituation/foodpricesindex/en/",
    ),
    SourceSeed("cbr_fx", "Central Bank of Russia FX", "fx", "https://www.cbr.ru/"),
    SourceSeed("ecb_fx", "European Central Bank FX", "fx", "https://www.ecb.europa.eu/"),
    SourceSeed("fred_energy_prices", "FRED Energy Prices", "energy", "https://fred.stlouisfed.org/"),
    SourceSeed("eia_energy", "EIA energy data", "energy", "https://www.eia.gov/"),
    SourceSeed("usda_psd", "USDA FAS PSD", "fundamental", "https://apps.fas.usda.gov/psdonline/"),
    SourceSeed("gdelt_news", "GDELT news", "news", "https://www.gdeltproject.org/"),
    SourceSeed("open_meteo_weather", "Open-Meteo weather", "weather", "https://open-meteo.com/"),
    SourceSeed(
        "open_meteo_historical_weather",
        "Open-Meteo Historical Weather API",
        "weather",
        "https://open-meteo.com/",
    ),
    SourceSeed(
        "nasa_power_weather",
        "NASA POWER Weather / Agroclimatology",
        "weather",
        "https://power.larc.nasa.gov/",
    ),
    SourceSeed("faostat", "FAOSTAT", "fundamental", "https://www.fao.org/faostat/"),
)

WEATHER_REGIONS: tuple[WeatherRegionSeed, ...] = (
    WeatherRegionSeed(
        "br_mato_grosso_soybean",
        "Mato Grosso soybean belt",
        "Brazil",
        "BR",
        "soybean",
        "soybean",
        "production_export",
        "high",
        "-12.600000",
        "-55.700000",
        "centroid",
        "single_point",
        "Largest Brazilian soybean production area; weather shocks can move soybean oil and meal supply expectations.",
    ),
    WeatherRegionSeed(
        "br_parana_soybean",
        "Parana soybean belt",
        "Brazil",
        "BR",
        "soybean",
        "soybean",
        "production_export",
        "high",
        "-24.900000",
        "-51.600000",
        "centroid",
        "single_point",
        "Major southern Brazil soybean region with drought and frost sensitivity.",
    ),
    WeatherRegionSeed(
        "br_goias_soybean",
        "Goias soybean belt",
        "Brazil",
        "BR",
        "soybean",
        "soybean",
        "production_export",
        "medium",
        "-16.000000",
        "-49.500000",
        "centroid",
        "single_point",
        "Central Brazil soybean weather proxy that complements Mato Grosso and Parana.",
    ),
    WeatherRegionSeed(
        "us_iowa_soybean",
        "Iowa soybean belt",
        "United States",
        "US",
        "soybean",
        "soybean",
        "production_export",
        "high",
        "42.000000",
        "-93.500000",
        "centroid",
        "single_point",
        "Core US soybean state; precipitation and heat stress influence global oilseed expectations.",
    ),
    WeatherRegionSeed(
        "us_illinois_soybean",
        "Illinois soybean belt",
        "United States",
        "US",
        "soybean",
        "soybean",
        "production_processing",
        "high",
        "40.000000",
        "-89.200000",
        "centroid",
        "single_point",
        "Core US soybean processing and production state; useful alongside Iowa.",
    ),
    WeatherRegionSeed(
        "us_indiana_soybean",
        "Indiana soybean belt",
        "United States",
        "US",
        "soybean",
        "soybean",
        "production",
        "medium",
        "40.000000",
        "-86.100000",
        "centroid",
        "single_point",
        "Eastern US soybean belt weather proxy for broader Midwest coverage.",
    ),
    WeatherRegionSeed(
        "ar_buenos_aires_soybean",
        "Buenos Aires soybean region",
        "Argentina",
        "AR",
        "soybean",
        "soybean",
        "production_export",
        "high",
        "-36.700000",
        "-60.000000",
        "centroid",
        "single_point",
        "Argentina soybean production/export weather signal; drought and heat shocks affect meal and oil exports.",
    ),
    WeatherRegionSeed(
        "ar_cordoba_soybean",
        "Cordoba soybean region",
        "Argentina",
        "AR",
        "soybean",
        "soybean",
        "production_export",
        "high",
        "-31.400000",
        "-64.200000",
        "centroid",
        "single_point",
        "Central Argentina soybean region and drought/heat stress proxy.",
    ),
    WeatherRegionSeed(
        "ar_santa_fe_soybean",
        "Santa Fe soybean region",
        "Argentina",
        "AR",
        "soybean",
        "soybean",
        "production_processing_export",
        "high",
        "-31.600000",
        "-60.700000",
        "centroid",
        "single_point",
        "Argentina soybean crush/export hub weather proxy.",
    ),
    WeatherRegionSeed(
        "ca_saskatchewan_canola",
        "Saskatchewan canola belt",
        "Canada",
        "CA",
        "canola",
        "rapeseed",
        "production_export",
        "high",
        "52.100000",
        "-106.700000",
        "centroid",
        "single_point",
        "Largest Canadian canola production province; directly relevant to rapeseed oil and meal context.",
    ),
    WeatherRegionSeed(
        "ca_alberta_canola",
        "Alberta canola belt",
        "Canada",
        "CA",
        "canola",
        "rapeseed",
        "production_export",
        "high",
        "53.900000",
        "-113.500000",
        "centroid",
        "single_point",
        "Major Canadian canola region complementing Saskatchewan.",
    ),
    WeatherRegionSeed(
        "ca_manitoba_canola",
        "Manitoba canola belt",
        "Canada",
        "CA",
        "canola",
        "rapeseed",
        "production_export",
        "medium",
        "50.400000",
        "-98.700000",
        "centroid",
        "single_point",
        "Eastern prairie canola coverage and moisture/heat contrast.",
    ),
    WeatherRegionSeed(
        "eu_france_rapeseed",
        "France rapeseed region",
        "France",
        "FR",
        "rapeseed",
        "rapeseed",
        "production",
        "medium",
        "47.400000",
        "2.400000",
        "centroid",
        "single_point",
        "Important EU rapeseed producer and European oilseed supply context.",
    ),
    WeatherRegionSeed(
        "ua_black_sea_rapeseed",
        "Ukraine / Black Sea rapeseed region",
        "Ukraine",
        "UA",
        "rapeseed",
        "rapeseed",
        "production_export",
        "high",
        "49.000000",
        "31.000000",
        "centroid",
        "single_point",
        "Black Sea rapeseed export weather is relevant for regional oilseed supply and price pressure.",
    ),
)


def seed_database(session: Session) -> dict[str, int]:
    products_created = 0
    sources_created = 0
    weather_regions_created = 0

    for item in PRODUCTS:
        product = session.scalar(select(Product).where(Product.code == item.code))
        if product is None:
            session.add(
                Product(
                    code=item.code,
                    name=item.name,
                    category=item.category,
                    unit=item.unit,
                    currency_default=item.currency_default,
                    is_active=True,
                )
            )
            products_created += 1
        else:
            product.name = item.name
            product.category = item.category
            product.unit = item.unit
            product.currency_default = item.currency_default
            product.is_active = True

    for item in SOURCES:
        source = session.scalar(select(Source).where(Source.code == item.code))
        if source is None:
            session.add(
                Source(
                    code=item.code,
                    name=item.name,
                    source_type=item.source_type,
                    base_url=item.base_url,
                    is_active=True,
                )
            )
            sources_created += 1
        else:
            source.name = item.name
            source.source_type = item.source_type
            source.base_url = item.base_url
            source.is_active = True

    for item in WEATHER_REGIONS:
        region = session.scalar(select(WeatherRegion).where(WeatherRegion.region_code == item.region_code))
        if region is None:
            session.add(
                WeatherRegion(
                    region_code=item.region_code,
                    region_name=item.region_name,
                    country=item.country,
                    country_code=item.country_code,
                    crop=item.crop,
                    commodity_family=item.commodity_family,
                    role=item.role,
                    priority=item.priority,
                    latitude=Decimal(item.latitude),
                    longitude=Decimal(item.longitude),
                    spatial_model=item.spatial_model,
                    aggregation_strategy=item.aggregation_strategy,
                    is_active=True,
                    metadata_json={"reason_for_ml": item.reason_for_ml, "coordinate_policy": "first_version_point_proxy"},
                )
            )
            weather_regions_created += 1
        else:
            region.region_name = item.region_name
            region.country = item.country
            region.country_code = item.country_code
            region.crop = item.crop
            region.commodity_family = item.commodity_family
            region.role = item.role
            region.priority = item.priority
            region.latitude = Decimal(item.latitude)
            region.longitude = Decimal(item.longitude)
            region.spatial_model = item.spatial_model
            region.aggregation_strategy = item.aggregation_strategy
            region.is_active = True
            region.metadata_json = {"reason_for_ml": item.reason_for_ml, "coordinate_policy": "first_version_point_proxy"}

    session.commit()
    return {
        "products_created": products_created,
        "sources_created": sources_created,
        "weather_regions_created": weather_regions_created,
    }


def main() -> None:
    setup_logging()
    with session_scope() as session:
        result = seed_database(session)
    logger.info("seed completed %s", result)
    print(result)


if __name__ == "__main__":
    main()
