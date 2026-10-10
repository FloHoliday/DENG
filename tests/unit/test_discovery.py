from datetime import UTC, datetime, timedelta

from discovery import Filters, eligible_races, live_session, qualifying_key

START = datetime(2025, 12, 7, 13, tzinfo=UTC)
END = datetime(2025, 12, 7, 15, tzinfo=UTC)


def session(key, name, start=START, end=END, cancelled=False, meeting=1276, year=2025):
    return {
        "session_key": key,
        "meeting_key": meeting,
        "session_name": name,
        "year": year,
        "date_start": start,
        "date_end": end,
        "is_cancelled": cancelled,
    }


SESSIONS = [
    session(9835, "Qualifying", START - timedelta(days=1), END - timedelta(days=1)),
    session(9836, "Sprint"),  # session_type is 'Race' too, must not be selected
    session(9839, "Race"),
    session(7000, "Race", cancelled=True, meeting=1),
    session(
        8000,
        "Race",
        START - timedelta(days=365),
        END - timedelta(days=365),
        year=2024,
        meeting=2,
    ),
]
LATER = END + timedelta(days=10)


def keys(races):
    return [r["session_key"] for r in races]


def test_selects_only_finished_uncancelled_races_in_scope():
    assert keys(eligible_races(SESSIONS, LATER, (2025,), Filters())) == [9839]
    assert keys(eligible_races(SESSIONS, LATER, (2024, 2025), Filters())) == [
        8000,
        9839,
    ]


def test_race_must_have_ended_30_minutes_ago():
    just_after = END + timedelta(minutes=30)
    assert eligible_races(SESSIONS, just_after, (2025,), Filters()) == []
    assert keys(
        eligible_races(SESSIONS, just_after + timedelta(seconds=1), (2025,), Filters())
    ) == [9839]


def test_filters():
    scope = (2024, 2025)
    assert keys(eligible_races(SESSIONS, LATER, scope, Filters(years=(2024,)))) == [
        8000
    ]
    assert keys(eligible_races(SESSIONS, LATER, scope, Filters(meeting_key=1276))) == [
        9839
    ]
    assert keys(eligible_races(SESSIONS, LATER, scope, Filters(session_key=8000))) == [
        8000
    ]


def test_qualifying_key():
    assert qualifying_key(SESSIONS, 1276) == 9835
    assert qualifying_key(SESSIONS, 999) is None


def test_live_window_boundaries():
    race = [session(9839, "Race")]
    assert live_session(race, START - timedelta(minutes=30))["session_key"] == 9839
    assert live_session(race, START - timedelta(minutes=30, seconds=1)) is None
    assert live_session(race, END + timedelta(minutes=30)) is not None
    assert live_session(race, END + timedelta(minutes=30, seconds=1)) is None


def test_cancelled_session_is_never_live():
    assert live_session([session(1, "Race", cancelled=True)], START) is None
