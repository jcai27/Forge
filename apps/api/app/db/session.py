from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings, validate_settings_or_raise
from app.db.migrations import run_migrations

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.db import models
    from app.services.seed import seed_database

    validate_settings_or_raise()
    if settings.db_auto_create_schema:
        Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    if settings.db_seed_demo_data_on_startup:
        seed_database(SessionLocal())
