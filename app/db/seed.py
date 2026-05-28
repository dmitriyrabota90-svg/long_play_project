from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.logging import setup_logging
from app.db.models import Product, Source
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
    SourceSeed("world_bank_pink_sheet", "World Bank Pink Sheet", "benchmark", "https://www.worldbank.org/"),
    SourceSeed("cbr_fx", "Central Bank of Russia FX", "fx", "https://www.cbr.ru/"),
    SourceSeed("ecb_fx", "European Central Bank FX", "fx", "https://www.ecb.europa.eu/"),
    SourceSeed("eia_energy", "EIA energy data", "energy", "https://www.eia.gov/"),
    SourceSeed("usda_psd", "USDA FAS PSD", "fundamental", "https://apps.fas.usda.gov/psdonline/"),
    SourceSeed("gdelt_news", "GDELT news", "news", "https://www.gdeltproject.org/"),
    SourceSeed("open_meteo_weather", "Open-Meteo weather", "weather", "https://open-meteo.com/"),
    SourceSeed("faostat", "FAOSTAT", "fundamental", "https://www.fao.org/faostat/"),
)


def seed_database(session: Session) -> dict[str, int]:
    products_created = 0
    sources_created = 0

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

    session.commit()
    return {"products_created": products_created, "sources_created": sources_created}


def main() -> None:
    setup_logging()
    with session_scope() as session:
        result = seed_database(session)
    logger.info("seed completed %s", result)
    print(result)


if __name__ == "__main__":
    main()
