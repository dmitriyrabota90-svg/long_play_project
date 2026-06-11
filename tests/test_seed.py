from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Product, ProductWeatherRegionWeight, Source, WeatherRegion
from app.db.seed import (
    PRODUCTS,
    PRODUCT_WEATHER_REGION_WEIGHTS,
    RAPESEED_WEATHER_PRODUCT_CODES,
    RAPESEED_WEATHER_REGION_CODES,
    SOURCES,
    SOYBEAN_WEATHER_PRODUCT_CODES,
    SOYBEAN_WEATHER_REGION_CODES,
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
        weather_region_count = session.scalar(select(func.count()).select_from(WeatherRegion))
        product_weather_weights_count = session.scalar(select(func.count()).select_from(ProductWeatherRegionWeight))
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
    assert mato_grosso_region is not None
    assert mato_grosso_region.priority == "high"
    assert mato_grosso_region.commodity_family == "soybean"
    assert mato_grosso_region.is_active is True
    assert saskatchewan_region is not None
    assert saskatchewan_region.commodity_family == "rapeseed"
    assert saskatchewan_region.metadata_json["coordinate_policy"] == "first_version_point_proxy"
