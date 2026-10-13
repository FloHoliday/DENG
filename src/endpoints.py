"""Endpoint registry (briefing §6.2), in fetch order; the column list of each endpoint lives in sql/002_raw.sql.

metadata       ?year=Y                              one unit per year, refreshed on every run
race-level     ?session_key=<race>                  one unit per race, chunk "all"
starting_grid  ?session_key=<qualifying>            OpenF1 keys the grid on qualifying (docs/api-notes.md)
car_data       ?session_key=<race>&driver_number=D  one unit per driver, planned once `drivers` is done
"""

METADATA = ["meetings", "sessions"]
RACE_LEVEL = [
    "drivers",  # first: car_data needs the driver list
    "laps",
    "stints",
    "pit",
    "position",
    "race_control",
    "session_result",
    "weather",
    "intervals",
    "starting_grid",
]
