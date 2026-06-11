from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.logging import setup_logging
from app.db.models import Product, ProductTradeCodeWeight, ProductWeatherRegionWeight, Source, TradeCommodityCode, WeatherRegion
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


@dataclass(frozen=True)
class ProductWeatherRegionWeightSeed:
    product_code: str
    region_code: str
    weight: Decimal
    role: str = "production_weather_proxy"
    effective_from: date = date(2020, 1, 1)
    effective_to: date | None = None
    is_active: bool = True


@dataclass(frozen=True)
class TradeCommodityCodeSeed:
    code_system: str
    commodity_code: str
    commodity_name: str
    hs_code: str | None
    hs_revision: str
    commodity_family: str
    product_code: str | None
    relevance: str
    unit_hint: str | None
    hs_description: str
    mapping_note: str
    is_active: bool = True


@dataclass(frozen=True)
class ProductTradeCodeWeightSeed:
    product_code: str
    commodity_code: str
    weight: Decimal
    relevance: str = "direct"
    role: str = "direct_trade_proxy"
    effective_from: date = date(2020, 1, 1)
    effective_to: date | None = None
    is_active: bool = True


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
    SourceSeed("gdelt_2_1", "GDELT 2.1 DOC/Event APIs", "news_event", "https://www.gdeltproject.org/"),
    SourceSeed("usda_reports", "USDA Reports / WASDE / PSD", "official_report", "https://www.usda.gov/oce/commodity/wasde"),
    SourceSeed("fao_news_releases", "FAO News / Food Price Index Releases", "official_release", "https://www.fao.org/newsroom/"),
    SourceSeed(
        "world_bank_commodity_releases",
        "World Bank Commodity Market Releases",
        "official_release",
        "https://www.worldbank.org/en/research/commodity-markets",
    ),
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
    SourceSeed("un_comtrade", "UN Comtrade", "trade", "https://comtradeplus.un.org/"),
    SourceSeed(
        "faostat_trade",
        "FAOSTAT Trade / Crops and Livestock Products",
        "trade",
        "https://www.fao.org/faostat/",
    ),
    SourceSeed(
        "usda_fas_trade",
        "USDA FAS / GATS / PSD Trade Data",
        "official_agriculture_trade",
        "https://apps.fas.usda.gov/",
    ),
    SourceSeed("world_bank_wits", "World Bank WITS", "trade", "https://wits.worldbank.org/"),
)

TRADE_COMMODITY_CODES: tuple[TradeCommodityCodeSeed, ...] = (
    TradeCommodityCodeSeed(
        "HS",
        "1201",
        "Soybeans",
        "1201",
        "generic",
        "soybean",
        None,
        "direct",
        "metric_ton",
        "Soya beans, whether or not broken",
        "Soybean seed trade proxy for China import demand and Brazil/US/Argentina export context.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "1507",
        "Soybean oil",
        "1507",
        "generic",
        "soybean",
        "soybean_oil",
        "direct",
        "metric_ton",
        "Soya-bean oil and its fractions",
        "Direct soybean oil trade mapping; subcodes may separate crude and refined oil later.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "2304",
        "Soybean meal / oilcake",
        "2304",
        "generic",
        "soybean",
        "soybean_meal",
        "direct",
        "metric_ton",
        "Oilcake and other solid residues resulting from extraction of soya-bean oil",
        "Direct soybean meal/oilcake trade mapping for feed and crush-product context.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "1205",
        "Rapeseed / canola seed",
        "1205",
        "generic",
        "rapeseed_canola",
        None,
        "context",
        "metric_ton",
        "Rape or colza seeds, whether or not broken",
        "Rapeseed/canola seed trade context for oil and meal products.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "1514",
        "Rapeseed / canola / mustard oil",
        "1514",
        "generic",
        "rapeseed_canola",
        "rapeseed_oil",
        "direct",
        "metric_ton",
        "Rape, colza or mustard oil and fractions thereof",
        "Direct rapeseed/canola oil mapping; mustard inclusion needs source-specific review.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "2306",
        "Rapeseed / canola meal / oilcake",
        "2306",
        "generic",
        "rapeseed_canola",
        "rapeseed_meal",
        "direct",
        "metric_ton",
        "Oilcake and other solid residues from vegetable fats or oils, other than soya-bean",
        "Rapeseed/canola meal mapping; relevant subcode granularity must be verified per source.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "1511",
        "Palm oil",
        "1511",
        "generic",
        "palm_oil",
        None,
        "context",
        "metric_ton",
        "Palm oil and its fractions",
        "Substitute vegetable oil context for broader oil spread features.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "1512",
        "Sunflower, safflower or cottonseed oil",
        "1512",
        "generic",
        "sunflower_oil",
        None,
        "context",
        "metric_ton",
        "Sunflower-seed, safflower or cotton-seed oil and fractions thereof",
        "Vegetable oil context; not tied to current-price sunflower instruments.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "1001",
        "Wheat",
        "1001",
        "generic",
        "wheat",
        None,
        "context",
        "metric_ton",
        "Wheat and meslin",
        "Grain/feed and Black Sea trade context.",
    ),
    TradeCommodityCodeSeed(
        "HS",
        "1005",
        "Maize / corn",
        "1005",
        "generic",
        "maize_corn",
        None,
        "context",
        "metric_ton",
        "Maize (corn)",
        "Feed and biofuel cross-market context.",
    ),
)

PRODUCT_TRADE_CODE_WEIGHTS: tuple[ProductTradeCodeWeightSeed, ...] = (
    ProductTradeCodeWeightSeed("soybean_oil", "1507", Decimal("1.00000000")),
    ProductTradeCodeWeightSeed("soybean_meal", "2304", Decimal("1.00000000")),
    ProductTradeCodeWeightSeed("rapeseed_oil", "1514", Decimal("1.00000000")),
    ProductTradeCodeWeightSeed("rapeseed_meal", "2306", Decimal("1.00000000")),
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

SOYBEAN_WEATHER_PRODUCT_CODES = ("soybean_oil", "soybean_meal")
SOYBEAN_WEATHER_REGION_CODES = (
    "br_mato_grosso_soybean",
    "br_parana_soybean",
    "br_goias_soybean",
    "us_iowa_soybean",
    "us_illinois_soybean",
    "us_indiana_soybean",
    "ar_buenos_aires_soybean",
    "ar_cordoba_soybean",
    "ar_santa_fe_soybean",
)
RAPESEED_WEATHER_PRODUCT_CODES = ("rapeseed_oil", "rapeseed_meal")
RAPESEED_WEATHER_REGION_CODES = (
    "ca_saskatchewan_canola",
    "ca_alberta_canola",
    "ca_manitoba_canola",
    "eu_france_rapeseed",
    "ua_black_sea_rapeseed",
)


def _equal_weights(count: int) -> tuple[Decimal, ...]:
    if count <= 0:
        return ()
    quant = Decimal("0.00000001")
    base = (Decimal("1") / Decimal(count)).quantize(quant)
    values = [base for _ in range(count)]
    values[-1] = Decimal("1") - sum(values[:-1])
    return tuple(values)


PRODUCT_WEATHER_REGION_WEIGHTS: tuple[ProductWeatherRegionWeightSeed, ...] = tuple(
    ProductWeatherRegionWeightSeed(product_code=product_code, region_code=region_code, weight=weight)
    for product_code in SOYBEAN_WEATHER_PRODUCT_CODES
    for region_code, weight in zip(
        SOYBEAN_WEATHER_REGION_CODES,
        _equal_weights(len(SOYBEAN_WEATHER_REGION_CODES)),
        strict=True,
    )
) + tuple(
    ProductWeatherRegionWeightSeed(product_code=product_code, region_code=region_code, weight=weight)
    for product_code in RAPESEED_WEATHER_PRODUCT_CODES
    for region_code, weight in zip(
        RAPESEED_WEATHER_REGION_CODES,
        _equal_weights(len(RAPESEED_WEATHER_REGION_CODES)),
        strict=True,
    )
)


def seed_database(session: Session) -> dict[str, int]:
    products_created = 0
    sources_created = 0
    weather_regions_created = 0
    product_weather_region_weights_created = 0
    trade_commodity_codes_created = 0
    product_trade_code_weights_created = 0

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

    session.flush()
    for item in TRADE_COMMODITY_CODES:
        existing_code = session.scalar(
            select(TradeCommodityCode).where(
                TradeCommodityCode.code_system == item.code_system,
                TradeCommodityCode.commodity_code == item.commodity_code,
                TradeCommodityCode.hs_revision == item.hs_revision,
            )
        )
        metadata_json = {
            "hs_description": item.hs_description,
            "design_phase": "6.5C",
            "mapping_note": item.mapping_note,
            "source": "Phase 6.5A/6.5B design",
        }
        if existing_code is None:
            session.add(
                TradeCommodityCode(
                    source_id=None,
                    code_system=item.code_system,
                    commodity_code=item.commodity_code,
                    commodity_name=item.commodity_name,
                    hs_code=item.hs_code,
                    hs_revision=item.hs_revision,
                    commodity_family=item.commodity_family,
                    product_code=item.product_code,
                    relevance=item.relevance,
                    unit_hint=item.unit_hint,
                    is_active=item.is_active,
                    metadata_json=metadata_json,
                )
            )
            trade_commodity_codes_created += 1
        else:
            existing_code.source_id = None
            existing_code.commodity_name = item.commodity_name
            existing_code.hs_code = item.hs_code
            existing_code.commodity_family = item.commodity_family
            existing_code.product_code = item.product_code
            existing_code.relevance = item.relevance
            existing_code.unit_hint = item.unit_hint
            existing_code.is_active = item.is_active
            existing_code.metadata_json = metadata_json

    session.flush()
    for item in PRODUCT_WEATHER_REGION_WEIGHTS:
        product = session.scalar(select(Product).where(Product.code == item.product_code))
        region = session.scalar(select(WeatherRegion).where(WeatherRegion.region_code == item.region_code))
        if product is None or region is None:
            logger.warning(
                "skipping product weather region weight product_code=%s region_code=%s product_exists=%s region_exists=%s",
                item.product_code,
                item.region_code,
                product is not None,
                region is not None,
            )
            continue
        existing = session.scalar(
            select(ProductWeatherRegionWeight).where(
                ProductWeatherRegionWeight.product_id == product.id,
                ProductWeatherRegionWeight.region_id == region.id,
                ProductWeatherRegionWeight.role == item.role,
                ProductWeatherRegionWeight.effective_from == item.effective_from,
            )
        )
        metadata_json = {
            "weighting_method": "equal_weight_first_version",
            "region_basis": "seeded_weather_regions",
            "note": "Replace later with production/export weights.",
        }
        if existing is None:
            session.add(
                ProductWeatherRegionWeight(
                    product_id=product.id,
                    region_id=region.id,
                    weight=item.weight,
                    role=item.role,
                    effective_from=item.effective_from,
                    effective_to=item.effective_to,
                    is_active=item.is_active,
                    metadata_json=metadata_json,
                )
            )
            product_weather_region_weights_created += 1
        else:
            existing.weight = item.weight
            existing.effective_to = item.effective_to
            existing.is_active = item.is_active
            existing.metadata_json = metadata_json

    session.flush()
    for item in PRODUCT_TRADE_CODE_WEIGHTS:
        product = session.scalar(select(Product).where(Product.code == item.product_code))
        trade_code = session.scalar(
            select(TradeCommodityCode).where(
                TradeCommodityCode.code_system == "HS",
                TradeCommodityCode.commodity_code == item.commodity_code,
                TradeCommodityCode.hs_revision == "generic",
            )
        )
        if product is None or trade_code is None:
            logger.warning(
                "skipping product trade code weight product_code=%s commodity_code=%s product_exists=%s code_exists=%s",
                item.product_code,
                item.commodity_code,
                product is not None,
                trade_code is not None,
            )
            continue
        existing_trade_weight = session.scalar(
            select(ProductTradeCodeWeight).where(
                ProductTradeCodeWeight.product_id == product.id,
                ProductTradeCodeWeight.trade_commodity_code_id == trade_code.id,
                ProductTradeCodeWeight.role == item.role,
                ProductTradeCodeWeight.effective_from == item.effective_from,
            )
        )
        metadata_json = {
            "weighting_method": "direct_only_first_version",
            "design_phase": "6.5C",
            "note": "Context trade-code weights are documented for later phases but not seeded in Phase 6.5C.",
        }
        if existing_trade_weight is None:
            session.add(
                ProductTradeCodeWeight(
                    product_id=product.id,
                    trade_commodity_code_id=trade_code.id,
                    weight=item.weight,
                    relevance=item.relevance,
                    role=item.role,
                    effective_from=item.effective_from,
                    effective_to=item.effective_to,
                    is_active=item.is_active,
                    metadata_json=metadata_json,
                )
            )
            product_trade_code_weights_created += 1
        else:
            existing_trade_weight.weight = item.weight
            existing_trade_weight.relevance = item.relevance
            existing_trade_weight.effective_to = item.effective_to
            existing_trade_weight.is_active = item.is_active
            existing_trade_weight.metadata_json = metadata_json

    session.commit()
    return {
        "products_created": products_created,
        "sources_created": sources_created,
        "weather_regions_created": weather_regions_created,
        "product_weather_region_weights_created": product_weather_region_weights_created,
        "trade_commodity_codes_created": trade_commodity_codes_created,
        "product_trade_code_weights_created": product_trade_code_weights_created,
    }


def main() -> None:
    setup_logging()
    with session_scope() as session:
        result = seed_database(session)
    logger.info("seed completed %s", result)
    print(result)


if __name__ == "__main__":
    main()
