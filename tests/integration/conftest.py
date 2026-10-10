import dataclasses

import psycopg
import pytest

import db
from config import load_settings
from raw_store import RawStore

TEST_DB = "f1_test"


@pytest.fixture
def db_settings(tmp_path):
    """The .env connection, but a throwaway database and raw zone: dev data is never touched."""
    try:
        base = load_settings()
    except KeyError:
        pytest.skip("Postgres settings missing (.env)")
    return dataclasses.replace(
        base,
        postgres_db=TEST_DB,
        raw_uri=f"file://{tmp_path.as_posix()}/raw",
        scope_years=(2025,),
    )


@pytest.fixture
def conn(db_settings):
    try:
        admin = db.connect(
            dataclasses.replace(db_settings, postgres_db=load_settings().postgres_db)
        )
    except psycopg.OperationalError:
        pytest.skip("compose Postgres not reachable (docker compose up -d postgres)")
    with admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    with db.connect(db_settings) as conn:
        db.apply_ddl(conn)
        yield conn


@pytest.fixture
def store(db_settings):
    return RawStore(db_settings.raw_uri)
