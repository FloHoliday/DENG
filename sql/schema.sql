-- Store step: one typed column per OpenF1 field (schema-on-write). A new, renamed or
-- wrongly typed field fails the session's load instead of slipping into the table.
CREATE TABLE IF NOT EXISTS public.meetings (
    circuit_key INTEGER,
    circuit_image TEXT,
    circuit_info_url TEXT,
    circuit_short_name TEXT,
    circuit_type TEXT,
    country_code TEXT,
    country_flag TEXT,
    country_key INTEGER,
    country_name TEXT,
    date_end TIMESTAMPTZ NOT NULL,
    date_start TIMESTAMPTZ NOT NULL,
    gmt_offset INTERVAL,
    is_cancelled BOOLEAN,
    location TEXT,
    meeting_key INTEGER PRIMARY KEY,
    meeting_name TEXT NOT NULL,
    meeting_official_name TEXT,
    year INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.sessions (
    circuit_key INTEGER,
    circuit_short_name TEXT,
    country_code TEXT,
    country_key INTEGER,
    country_name TEXT,
    date_end TIMESTAMPTZ NOT NULL,
    date_start TIMESTAMPTZ NOT NULL,
    gmt_offset INTERVAL,
    is_cancelled BOOLEAN,
    location TEXT,
    meeting_key INTEGER NOT NULL,
    session_key INTEGER PRIMARY KEY,
    session_name TEXT NOT NULL,
    session_type TEXT,
    year INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One table per endpoint, keyed by the Race/Sprint session_key the rows were fetched for.
CREATE TABLE IF NOT EXISTS public.drivers (
    broadcast_name TEXT,
    country_code TEXT, -- deprecated, will be removed at the end of the 2026 season
    driver_number INTEGER NOT NULL,
    first_name TEXT,
    full_name TEXT,
    headshot_url TEXT,
    last_name TEXT,
    meeting_key INTEGER NOT NULL,
    name_acronym TEXT,
    session_key INTEGER NOT NULL,
    team_colour TEXT,
    team_name TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.laps (
    date_start TIMESTAMPTZ,
    driver_number INTEGER NOT NULL,
    duration_sector_1 DOUBLE PRECISION,
    duration_sector_2 DOUBLE PRECISION,
    duration_sector_3 DOUBLE PRECISION,
    i1_speed INTEGER,
    i2_speed INTEGER,
    is_pit_out_lap BOOLEAN,
    lap_duration DOUBLE PRECISION,
    lap_number INTEGER NOT NULL,
    meeting_key INTEGER NOT NULL,
    segments_sector_1 INTEGER[],
    segments_sector_2 INTEGER[],
    segments_sector_3 INTEGER[],
    session_key INTEGER NOT NULL,
    st_speed INTEGER,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.stints (
    compound TEXT,
    driver_number INTEGER NOT NULL,
    lap_end INTEGER,
    lap_start INTEGER,
    meeting_key INTEGER NOT NULL,
    session_key INTEGER NOT NULL,
    stint_number INTEGER NOT NULL,
    tyre_age_at_start INTEGER,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.pit (
    date TIMESTAMPTZ NOT NULL,
    driver_number INTEGER NOT NULL,
    lane_duration DOUBLE PRECISION,
    lap_number INTEGER,
    meeting_key INTEGER NOT NULL,
    pit_duration DOUBLE PRECISION, -- deprecated, same as 'lane_duration, will be removed at the end of the 2026 season
    session_key INTEGER NOT NULL,
    stop_duration DOUBLE PRECISION, -- only available from the 2024 US GP onwards
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.position (
    date TIMESTAMPTZ NOT NULL,
    driver_number INTEGER NOT NULL,
    meeting_key INTEGER NOT NULL,
    position INTEGER NOT NULL,
    session_key INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.race_control (
    category TEXT,
    date TIMESTAMPTZ NOT NULL,
    driver_number INTEGER,
    flag TEXT,
    lap_number INTEGER,
    meeting_key INTEGER NOT NULL,
    message TEXT,
    qualifying_phase INTEGER,
    scope TEXT,
    sector INTEGER,
    session_key INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- gap_to_leader / interval are seconds or text like '+1 LAP', so they stay TEXT.
CREATE TABLE IF NOT EXISTS public.session_result (
    dnf BOOLEAN,
    dns BOOLEAN,
    dsq BOOLEAN,
    driver_number INTEGER NOT NULL,
    duration DOUBLE PRECISION,
    gap_to_leader TEXT,
    number_of_laps INTEGER,
    meeting_key INTEGER NOT NULL,
    position INTEGER,
    session_key INTEGER NOT NULL,
    points DOUBLE PRECISION, -- not in docs, but present
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.weather (
    air_temperature DOUBLE PRECISION,
    date TIMESTAMPTZ NOT NULL,
    humidity DOUBLE PRECISION,
    meeting_key INTEGER NOT NULL,
    pressure DOUBLE PRECISION,
    rainfall INTEGER,
    session_key INTEGER NOT NULL,
    track_temperature DOUBLE PRECISION,
    wind_direction INTEGER,
    wind_speed DOUBLE PRECISION,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.intervals (
    date TIMESTAMPTZ NOT NULL,
    driver_number INTEGER NOT NULL,
    gap_to_leader TEXT,
    "interval" TEXT,
    meeting_key INTEGER NOT NULL,
    session_key INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- session_key is the qualifying session that set the grid, race_session_key the Race/Sprint.
CREATE TABLE IF NOT EXISTS public.starting_grid (
    driver_number INTEGER NOT NULL,
    lap_duration DOUBLE PRECISION,
    meeting_key INTEGER NOT NULL,
    position INTEGER NOT NULL,
    session_key INTEGER NOT NULL,
    race_session_key INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.car_data (
    brake INTEGER,
    date TIMESTAMPTZ NOT NULL,
    driver_number INTEGER NOT NULL,
    drs INTEGER,
    meeting_key INTEGER NOT NULL,
    n_gear INTEGER,
    rpm INTEGER,
    session_key INTEGER NOT NULL,
    speed INTEGER,
    throttle INTEGER,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS drivers_session_key ON public.drivers (session_key);
CREATE INDEX IF NOT EXISTS laps_session_key ON public.laps (session_key);
CREATE INDEX IF NOT EXISTS stints_session_key ON public.stints (session_key);
CREATE INDEX IF NOT EXISTS pit_session_key ON public.pit (session_key);
CREATE INDEX IF NOT EXISTS position_session_key ON public.position (session_key);
CREATE INDEX IF NOT EXISTS race_control_session_key ON public.race_control (session_key);
CREATE INDEX IF NOT EXISTS session_result_session_key ON public.session_result (session_key);
CREATE INDEX IF NOT EXISTS weather_session_key ON public.weather (session_key);
CREATE INDEX IF NOT EXISTS intervals_session_key ON public.intervals (session_key);
CREATE INDEX IF NOT EXISTS starting_grid_race_session_key ON public.starting_grid (race_session_key);
CREATE INDEX IF NOT EXISTS car_data_session_key ON public.car_data (session_key);

-- Which _SUCCESS marker each session was loaded from; a newer marker means reload.
CREATE TABLE IF NOT EXISTS public.loaded_sessions (
    session_key INTEGER PRIMARY KEY,
    completed_at TIMESTAMPTZ NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
