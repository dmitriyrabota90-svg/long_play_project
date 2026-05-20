from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.seed import seed_database
from app.monitoring.health import run_health_check


def test_health_check_returns_status(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    raw_dir = tmp_path / "raw"
    export_dir = tmp_path / "exports"
    raw_dir.mkdir()
    export_dir.mkdir()

    with SessionLocal() as session:
        seed_database(session)
        result = run_health_check(session=session, raw_data_dir=raw_dir, export_data_dir=export_dir)

    assert result["status"] == "ok"
    assert result["database"]["ok"] is True
    assert result["products_count"] > 0
    assert result["sources_count"] > 0

