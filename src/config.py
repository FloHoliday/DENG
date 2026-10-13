"""Settings from environment variables (and .env), so the same code runs on the host and in a container."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    raw_uri: str


def load_settings() -> Settings:
    """Read the settings; raises KeyError/ValueError on missing or invalid values (CLI exit code 2)."""
    # Real environment variables win over .env (e.g. POSTGRES_HOST in the compose `code` service).
    load_dotenv(override=False)
    env = os.environ
    return Settings(
        postgres_host=env.get("POSTGRES_HOST", "127.0.0.1"),
        postgres_port=int(env.get("POSTGRES_PORT", "5432")),
        postgres_db=env["POSTGRES_DB"],
        postgres_user=env["POSTGRES_USER"],
        postgres_password=env["POSTGRES_PASSWORD"],
        raw_uri=env.get("RAW_URI", "file://./data/raw"),
    )
