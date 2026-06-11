from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Product, Source, WeatherRegion
from app.db.seed import PRODUCTS, SOURCES, WEATHER_REGIONS, seed_database


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
        weather_region_count = session.scalar(select(func.count()).select_from(WeatherRegion))
        mato_grosso_region = session.scalar(
            select(WeatherRegion).where(WeatherRegion.region_code == "br_mato_grosso_soybean")
        )
        saskatchewan_region = session.scalar(
            select(WeatherRegion).where(WeatherRegion.region_code == "ca_saskatchewan_canola")
        )

    assert product_count == len(PRODUCTS)
    assert source_count == len(SOURCES)
    assert weather_region_count == len(WEATHER_REGIONS)
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
    assert mato_grosso_region is not None
    assert mato_grosso_region.priority == "high"
    assert mato_grosso_region.commodity_family == "soybean"
    assert mato_grosso_region.is_active is True
    assert saskatchewan_region is not None
    assert saskatchewan_region.commodity_family == "rapeseed"
    assert saskatchewan_region.metadata_json["coordinate_policy"] == "first_version_point_proxy"
