from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Product, Source
from app.db.seed import PRODUCTS, SOURCES, seed_database


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

    assert product_count == len(PRODUCTS)
    assert source_count == len(SOURCES)
    assert historical_source is not None
    assert historical_source.name == "Jijinhao Historical Prices"
    assert historical_source.source_type == "price_history"
