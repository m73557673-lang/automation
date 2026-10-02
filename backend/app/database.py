import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DEFAULT_DATABASE_URL = "sqlite:///./backend/data/incident_commander.db"
DATABASE_URL = os.getenv("INCIDENT_DATABASE_URL", DEFAULT_DATABASE_URL)


class Base(DeclarativeBase):
    pass


def create_sqlite_engine(database_url: str) -> Engine:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("This prototype currently supports SQLite URLs only.")

    database_path = database_url.removeprefix("sqlite:///")
    if database_path not in (":memory:", "") and not database_path.startswith("/"):
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    db_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(db_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return db_engine


engine = create_sqlite_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _archive_legacy_schema(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    if "services" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("services")}
    if "environment" in columns:
        return

    existing = set(inspector.get_table_names())
    legacy_names = ("evidence", "remediations", "postmortems", "runbooks", "services", "incidents")
    with db_engine.begin() as connection:
        for table_name in legacy_names:
            archive_name = f"legacy_{table_name}"
            if table_name in existing and archive_name not in existing:
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table_name}" RENAME TO "{archive_name}"'
                )


def initialize_database(db_engine: Engine = engine) -> None:
    """Create the normalized schema and preserve/copy records from the first prototype."""
    if db_engine.dialect.name != "sqlite":
        raise RuntimeError("The incident commander database must use SQLite in this phase.")

    from . import models  # noqa: F401 - registers all mapped tables with Base.metadata

    _archive_legacy_schema(db_engine)
    Base.metadata.create_all(bind=db_engine)
    with db_engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(120) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
            """
        )

    from .migrations import migrate_legacy_records

    migrate_legacy_records(db_engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()