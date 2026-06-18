from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    Product,
    ProductSupplyDemandWeight,
    ProductTradeCodeWeight,
    ProductWeatherRegionWeight,
    Source,
    SupplyDemandCommodity,
    TradeCommodityCode,
    WeatherRegion,
)
from app.db.seed import (
    PRODUCTS,
    PRODUCT_SUPPLY_DEMAND_WEIGHTS,
    PRODUCT_TRADE_CODE_WEIGHTS,
    PRODUCT_WEATHER_REGION_WEIGHTS,
    RAPESEED_WEATHER_PRODUCT_CODES,
    RAPESEED_WEATHER_REGION_CODES,
    SOURCES,
    SOYBEAN_WEATHER_PRODUCT_CODES,
    SOYBEAN_WEATHER_REGION_CODES,
    SUPPLY_DEMAND_COMMODITIES,
    TRADE_COMMODITY_CODES,
    WEATHER_REGIONS,
    seed_database,
)


def test_seed_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        seed_database(session)
        seed_database(session)

        product_count = session.scalar(select(func.count()).select_from(Product))
        source_count = session.scalar(select(func.count()).select_from(Source))
        historical_source = session.scalar(select(Source).where(Source.code == "jijinhao_historical_prices"))
        fred_source = session.scalar(select(Source).where(Source.code == "fred_energy_prices"))
        world_bank_source = session.scalar(select(Source).where(Source.code == "world_bank_pink_sheet"))
        fao_source = session.scalar(select(Source).where(Source.code == "fao_price_indices"))
        open_meteo_source = session.scalar(select(Source).where(Source.code == "open_meteo_historical_weather"))
        nasa_power_source = session.scalar(select(Source).where(Source.code == "nasa_power_weather"))
        gdelt_2_1_source = session.scalar(select(Source).where(Source.code == "gdelt_2_1"))
        usda_reports_source = session.scalar(select(Source).where(Source.code == "usda_reports"))
        fao_news_releases_source = session.scalar(select(Source).where(Source.code == "fao_news_releases"))
        world_bank_releases_source = session.scalar(select(Source).where(Source.code == "world_bank_commodity_releases"))
        un_comtrade_source = session.scalar(select(Source).where(Source.code == "un_comtrade"))
        faostat_trade_source = session.scalar(select(Source).where(Source.code == "faostat_trade"))
        usda_fas_trade_source = session.scalar(select(Source).where(Source.code == "usda_fas_trade"))
        world_bank_wits_source = session.scalar(select(Source).where(Source.code == "world_bank_wits"))
        usda_psd_source = session.scalar(select(Source).where(Source.code == "usda_psd"))
        usda_wasde_source = session.scalar(select(Source).where(Source.code == "usda_wasde"))
        faostat_supply_demand_source = session.scalar(select(Source).where(Source.code == "faostat_supply_demand"))
        usda_nass_quickstats_source = session.scalar(select(Source).where(Source.code == "usda_nass_quickstats"))
        weather_region_count = session.scalar(select(func.count()).select_from(WeatherRegion))
        product_weather_weights_count = session.scalar(select(func.count()).select_from(ProductWeatherRegionWeight))
        trade_commodity_code_count = session.scalar(select(func.count()).select_from(TradeCommodityCode))
        product_trade_weights_count = session.scalar(select(func.count()).select_from(ProductTradeCodeWeight))
        supply_demand_commodity_count = session.scalar(select(func.count()).select_from(SupplyDemandCommodity))
        product_supply_demand_weights_count = session.scalar(select(func.count()).select_from(ProductSupplyDemandWeight))
        direct_trade_weight_count = session.scalar(
            select(func.count()).select_from(ProductTradeCodeWeight).where(ProductTradeCodeWeight.role == "direct_trade_proxy")
        )
        direct_supply_demand_weight_count = session.scalar(
            select(func.count())
            .select_from(ProductSupplyDemandWeight)
            .where(ProductSupplyDemandWeight.role == "direct_supply_demand_proxy")
        )
        supply_demand_metrics = set(session.scalars(select(SupplyDemandCommodity.metric_name)).all())
        hs_1507 = session.scalar(
            select(TradeCommodityCode).where(
                TradeCommodityCode.code_system == "HS",
                TradeCommodityCode.commodity_code == "1507",
                TradeCommodityCode.hs_revision == "generic",
            )
        )
        soybean_oil_production = session.scalar(
            select(SupplyDemandCommodity).where(
                SupplyDemandCommodity.product_code == "soybean_oil",
                SupplyDemandCommodity.metric_name == "production_volume",
            )
        )
        hs_codes = set(
            session.scalars(
                select(TradeCommodityCode.commodity_code).where(TradeCommodityCode.code_system == "HS")
            ).all()
        )
        mato_grosso_region = session.scalar(
            select(WeatherRegion).where(WeatherRegion.region_code == "br_mato_grosso_soybean")
        )
        saskatchewan_region = session.scalar(
            select(WeatherRegion).where(WeatherRegion.region_code == "ca_saskatchewan_canola")
        )
        weight_counts = {
            product_code: session.scalar(
                select(func.count())
                .select_from(ProductWeatherRegionWeight)
                .join(Product, Product.id == ProductWeatherRegionWeight.product_id)
                .where(Product.code == product_code)
            )
            for product_code in SOYBEAN_WEATHER_PRODUCT_CODES + RAPESEED_WEATHER_PRODUCT_CODES
        }
        weight_sums = {
            product_code: session.scalar(
                select(func.sum(ProductWeatherRegionWeight.weight))
                .join(Product, Product.id == ProductWeatherRegionWeight.product_id)
                .where(Product.code == product_code)
            )
            for product_code in SOYBEAN_WEATHER_PRODUCT_CODES + RAPESEED_WEATHER_PRODUCT_CODES
        }

    assert product_count == len(PRODUCTS)
    assert source_count == len(SOURCES)
    assert weather_region_count == len(WEATHER_REGIONS)
    assert product_weather_weights_count == len(PRODUCT_WEATHER_REGION_WEIGHTS)
    assert trade_commodity_code_count == len(TRADE_COMMODITY_CODES)
    assert product_trade_weights_count == len(PRODUCT_TRADE_CODE_WEIGHTS)
    assert supply_demand_commodity_count == len(SUPPLY_DEMAND_COMMODITIES)
    assert product_supply_demand_weights_count == len(PRODUCT_SUPPLY_DEMAND_WEIGHTS)
    assert direct_trade_weight_count == 4
    assert direct_supply_demand_weight_count == len(PRODUCT_SUPPLY_DEMAND_WEIGHTS)
    assert {
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
    } <= supply_demand_metrics
    assert {"1201", "1507", "2304", "1205", "1514", "2306", "1511", "1512", "1001", "1005"} <= hs_codes
    for product_code in SOYBEAN_WEATHER_PRODUCT_CODES:
        assert weight_counts[product_code] == len(SOYBEAN_WEATHER_REGION_CODES)
        assert weight_sums[product_code] == 1
    for product_code in RAPESEED_WEATHER_PRODUCT_CODES:
        assert weight_counts[product_code] == len(RAPESEED_WEATHER_REGION_CODES)
        assert weight_sums[product_code] == 1
    assert historical_source is not None
    assert historical_source.name == "Jijinhao Historical Prices"
    assert historical_source.source_type == "price_history"
    assert fred_source is not None
    assert fred_source.name == "FRED Energy Prices"
    assert fred_source.source_type == "energy"
    assert world_bank_source is not None
    assert world_bank_source.name == "World Bank Pink Sheet"
    assert world_bank_source.source_type == "benchmark"
    assert world_bank_source.base_url == "https://www.worldbank.org/en/research/commodity-markets"
    assert fao_source is not None
    assert fao_source.name == "FAO Food Price Indices"
    assert fao_source.source_type == "benchmark"
    assert open_meteo_source is not None
    assert open_meteo_source.name == "Open-Meteo Historical Weather API"
    assert open_meteo_source.source_type == "weather"
    assert open_meteo_source.base_url == "https://open-meteo.com/"
    assert nasa_power_source is not None
    assert nasa_power_source.name == "NASA POWER Weather / Agroclimatology"
    assert nasa_power_source.source_type == "weather"
    assert nasa_power_source.base_url == "https://power.larc.nasa.gov/"
    assert gdelt_2_1_source is not None
    assert gdelt_2_1_source.name == "GDELT 2.1 DOC/Event APIs"
    assert gdelt_2_1_source.source_type == "news_event"
    assert gdelt_2_1_source.base_url == "https://www.gdeltproject.org/"
    assert usda_reports_source is not None
    assert usda_reports_source.name == "USDA Reports / WASDE / PSD"
    assert usda_reports_source.source_type == "official_report"
    assert usda_reports_source.base_url == "https://www.usda.gov/oce/commodity/wasde"
    assert fao_news_releases_source is not None
    assert fao_news_releases_source.name == "FAO News / Food Price Index Releases"
    assert fao_news_releases_source.source_type == "official_release"
    assert fao_news_releases_source.base_url == "https://www.fao.org/newsroom/"
    assert world_bank_releases_source is not None
    assert world_bank_releases_source.name == "World Bank Commodity Market Releases"
    assert world_bank_releases_source.source_type == "official_release"
    assert world_bank_releases_source.base_url == "https://www.worldbank.org/en/research/commodity-markets"
    assert un_comtrade_source is not None
    assert un_comtrade_source.name == "UN Comtrade"
    assert un_comtrade_source.source_type == "trade"
    assert un_comtrade_source.base_url == "https://comtradeplus.un.org/"
    assert faostat_trade_source is not None
    assert faostat_trade_source.name == "FAOSTAT Trade / Crops and Livestock Products"
    assert faostat_trade_source.source_type == "trade"
    assert usda_fas_trade_source is not None
    assert usda_fas_trade_source.name == "USDA FAS / GATS / PSD Trade Data"
    assert usda_fas_trade_source.source_type == "official_agriculture_trade"
    assert world_bank_wits_source is not None
    assert world_bank_wits_source.name == "World Bank WITS"
    assert world_bank_wits_source.source_type == "trade"
    assert usda_psd_source is not None
    assert usda_psd_source.name == "USDA PSD / FAS PSD Online"
    assert usda_psd_source.source_type == "supply_demand"
    assert usda_wasde_source is not None
    assert usda_wasde_source.name == "USDA WASDE"
    assert usda_wasde_source.source_type == "official_report"
    assert faostat_supply_demand_source is not None
    assert faostat_supply_demand_source.name == "FAOSTAT Production / Food Balance"
    assert faostat_supply_demand_source.source_type == "supply_demand_context"
    assert usda_nass_quickstats_source is not None
    assert usda_nass_quickstats_source.name == "USDA NASS Quick Stats"
    assert usda_nass_quickstats_source.source_type == "area_yield_production"
    assert hs_1507 is not None
    assert hs_1507.product_code == "soybean_oil"
    assert hs_1507.relevance == "direct"
    assert hs_1507.metadata_json["design_phase"] == "6.5C"
    assert soybean_oil_production is not None
    assert soybean_oil_production.relevance == "direct"
    assert soybean_oil_production.metadata_json["design_phase"] == "6.7C"
    assert soybean_oil_production.metadata_json["exact_psd_code_status"] == "needs_verification"
    assert mato_grosso_region is not None
    assert mato_grosso_region.priority == "high"
    assert mato_grosso_region.commodity_family == "soybean"
    assert mato_grosso_region.is_active is True
    assert saskatchewan_region is not None
    assert saskatchewan_region.commodity_family == "rapeseed"
    assert saskatchewan_region.metadata_json["coordinate_policy"] == "first_version_point_proxy"
