import pytest

from config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        postgres_host="127.0.0.1",
        postgres_port=5432,
        postgres_db="f1",
        postgres_user="f1",
        postgres_password="test",
        openf1_base_url="https://api.test/v1",
        raw_uri=f"file://{tmp_path.as_posix()}/raw",
        scope_years=(2025,),
        rate_limit_per_second=3,
        rate_limit_per_minute=25,
        http_timeout_seconds=5,
        max_retry_attempts=3,
        settling_days=3,
        review_session_key=9839,
        log_level="INFO",
    )
