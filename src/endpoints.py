"""Endpoint registry (briefing §6.2): the rest of the pipeline is generic over this list.

kind decides how an endpoint is queried and chunked:
  metadata  ?year=Y                             one unit per year, refreshed on every run
  session   ?session_key=<race>                 one unit per race, chunk "all"
  grid      ?session_key=<qualifying>           OpenF1 keys the grid on the qualifying session (docs/api-notes.md)
  driver    ?session_key=<race>&driver_number=D one unit per driver, planned once `drivers` is done
The column list of each endpoint lives in sql/002_raw.sql.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    name: str
    kind: str


ENDPOINTS = [
    Endpoint("meetings", "metadata"),
    Endpoint("sessions", "metadata"),
    Endpoint("drivers", "session"),  # first: car_data needs the driver list
    Endpoint("laps", "session"),
    Endpoint("stints", "session"),
    Endpoint("pit", "session"),
    Endpoint("position", "session"),
    Endpoint("race_control", "session"),
    Endpoint("session_result", "session"),
    Endpoint("weather", "session"),
    Endpoint("intervals", "session"),
    Endpoint("starting_grid", "grid"),
    Endpoint("car_data", "driver"),
]
BY_NAME = {e.name: e for e in ENDPOINTS}
METADATA = [e for e in ENDPOINTS if e.kind == "metadata"]
RACE_LEVEL = [e for e in ENDPOINTS if e.kind in ("session", "grid")]
CAR_DATA = BY_NAME["car_data"]
