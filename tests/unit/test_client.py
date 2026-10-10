import httpx
import pytest
import respx

from client import OpenF1Client

URL = "https://api.test/v1/laps"


class CountingLimiter:
    def __init__(self):
        self.calls = 0

    def try_acquire(self, name):
        self.calls += 1


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def limiter():
    return CountingLimiter()


@pytest.fixture
def client(settings, limiter, sleeps):
    c = OpenF1Client(settings, limiter=limiter, sleep=sleeps.append)
    yield c
    c.close()


@respx.mock
def test_ok_returns_exact_bytes(client):
    respx.get(URL).respond(200, content=b'[{"lap_number": 1}]')
    result = client.get("laps", {"session_key": 9839})
    assert result.status_code == 200
    assert result.content == b'[{"lap_number": 1}]'
    assert result.data == [{"lap_number": 1}]
    assert result.attempts == 1 and result.error is None
    assert "session_key=9839" in result.url


@respx.mock
def test_429_waits_retry_after(client, sleeps):
    respx.get(URL).side_effect = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json=[]),
    ]
    result = client.get("laps", {})
    assert result.status_code == 200 and result.attempts == 2
    assert sleeps == [7.0]


@respx.mock
def test_retry_after_is_capped(client, sleeps):
    respx.get(URL).side_effect = [
        httpx.Response(429, headers={"Retry-After": "9999"}),
        httpx.Response(200, json=[]),
    ]
    client.get("laps", {})
    assert sleeps == [120]


@respx.mock
def test_503_backs_off_and_retries(client, sleeps):
    respx.get(URL).side_effect = [httpx.Response(503), httpx.Response(200, json=[])]
    result = client.get("laps", {})
    assert result.status_code == 200 and result.attempts == 2
    assert len(sleeps) == 1 and 2 <= sleeps[0] <= 60


@respx.mock
def test_timeout_is_retried(client):
    respx.get(URL).side_effect = [
        httpx.ReadTimeout("slow"),
        httpx.Response(200, json=[]),
    ]
    assert client.get("laps", {}).status_code == 200


@respx.mock
def test_gives_up_after_max_attempts(client, sleeps, settings):
    respx.get(URL).respond(503)
    result = client.get("laps", {})
    assert result.attempts == settings.max_retry_attempts
    assert len(sleeps) == settings.max_retry_attempts - 1
    assert result.status_code == 503
    assert "HTTP 503 after 3 attempts" in result.error


@respx.mock
def test_connection_error_gives_up_without_response(client):
    respx.get(URL).side_effect = httpx.ConnectError("down")
    result = client.get("laps", {})
    assert result.status_code is None and result.content == b""
    assert "ConnectError" in result.error


@pytest.mark.parametrize("status", [400, 404, 422])
@respx.mock
def test_client_errors_are_not_retried(client, sleeps, status):
    respx.get(URL).respond(status, json={"detail": "x"})
    result = client.get("laps", {})
    assert result.status_code == status and result.attempts == 1
    assert sleeps == [] and result.error is None


@respx.mock
def test_limiter_is_invoked_for_every_attempt(client, limiter):
    respx.get(URL).side_effect = [
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(200, json=[]),
    ]
    client.get("laps", {})
    assert limiter.calls == 3
    assert client.requests_made == 3
