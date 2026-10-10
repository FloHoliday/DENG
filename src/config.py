"""Settings from environment variables (and .env), so the same code runs on the host, in a container or in an orchestrator."""

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
    openf1_base_url: str
    raw_uri: str
    scope_years: tuple[int, ...]
    rate_limit_per_second: int
    rate_limit_per_minute: int
    http_timeout_seconds: float
    max_retry_attempts: int
    settling_days: int
    review_session_key: int
    log_level: str


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
        openf1_base_url=env.get("OPENF1_BASE_URL", "https://api.openf1.org/v1"),
        raw_uri=env.get("RAW_URI", "file://./data/raw"),
        scope_years=tuple(
            int(y) for y in env.get("SCOPE_YEARS", "2023,2024,2025,2026").split(",")
        ),
        rate_limit_per_second=int(env.get("RATE_LIMIT_PER_SECOND", "3")),
        rate_limit_per_minute=int(env.get("RATE_LIMIT_PER_MINUTE", "25")),
        http_timeout_seconds=float(env.get("HTTP_TIMEOUT_SECONDS", "60")),
        max_retry_attempts=int(env.get("MAX_RETRY_ATTEMPTS", "6")),
        settling_days=int(env.get("SETTLING_DAYS", "3")),
        review_session_key=int(env.get("REVIEW_SESSION_KEY", "9839")),
        log_level=env.get("LOG_LEVEL", "INFO"),
    )
