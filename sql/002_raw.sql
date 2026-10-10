-- One table per OpenF1 endpoint, columns named exactly like the API fields (briefing §6.8).
-- Lineage columns start with "_"; fields the API adds later land in _extra instead of failing the load.
-- _race_session_key is the load partition: the race session key, or the year for meetings/sessions.
-- Polymorphic fields (number or "+1 LAP") are text. Reserved words ("position", "interval") are always quoted.
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.meetings (
  circuit_key            integer,
  circuit_info_url       text,
  circuit_image          text,
  circuit_short_name     text,
  circuit_type           text,
  country_code           text,
  country_flag           text,
  country_key            integer,
  country_name           text,
  date_end               timestamptz,
  date_start             timestamptz,
  gmt_offset             text,
  is_cancelled           boolean,
  location               text,
  meeting_key            integer,
  meeting_name           text,
  meeting_official_name  text,
  year                   integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.sessions (
  circuit_key            integer,
  circuit_short_name     text,
  country_code           text,
  country_key            integer,
  country_name           text,
  date_end               timestamptz,
  date_start             timestamptz,
  gmt_offset             text,
  is_cancelled           boolean,
  location               text,
  meeting_key            integer,
  session_key            integer,
  session_name           text,
  session_type           text,
  year                   integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.drivers (
  broadcast_name         text,
  country_code           text,          -- deprecated, removed after 2026
  driver_number          integer,
  first_name             text,
  full_name              text,
  headshot_url           text,
  last_name              text,
  meeting_key            integer,
  name_acronym           text,
  session_key            integer,
  team_colour            text,
  team_name              text,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.laps (
  date_start             timestamptz,
  driver_number          integer,
  duration_sector_1      double precision,
  duration_sector_2      double precision,
  duration_sector_3      double precision,
  i1_speed               integer,
  i2_speed               integer,
  is_pit_out_lap         boolean,
  lap_duration           double precision,
  lap_number             integer,
  meeting_key            integer,
  segments_sector_1      integer[],
  segments_sector_2      integer[],
  segments_sector_3      integer[],
  session_key            integer,
  st_speed               integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.stints (
  compound               text,
  driver_number          integer,
  lap_end                integer,
  lap_start              integer,
  meeting_key            integer,
  session_key            integer,
  stint_number           integer,
  tyre_age_at_start      integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.pit (
  date                   timestamptz,
  driver_number          integer,
  lane_duration          double precision,
  lap_number             integer,
  meeting_key            integer,
  pit_duration           double precision,  -- deprecated, removed after 2026
  session_key            integer,
  stop_duration          double precision,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.position (
  date                   timestamptz,
  driver_number          integer,
  meeting_key            integer,
  "position"             integer,
  session_key            integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.race_control (
  category               text,
  date                   timestamptz,
  driver_number          integer,
  flag                   text,
  lap_number             integer,
  meeting_key            integer,
  message                text,
  qualifying_phase       integer,
  scope                  text,
  sector                 integer,
  session_key            integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.session_result (
  dnf                    boolean,
  dns                    boolean,
  dsq                    boolean,
  driver_number          integer,
  duration               text,
  gap_to_leader          text,
  meeting_key            integer,
  number_of_laps         integer,
  points                 numeric,       -- not in the briefing's list, returned by the API (docs/api-notes.md)
  "position"             integer,
  session_key            integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.weather (
  air_temperature        double precision,
  date                   timestamptz,
  humidity               double precision,
  meeting_key            integer,
  pressure               double precision,
  rainfall               integer,       -- 0/1 in the API, not a boolean
  session_key            integer,
  track_temperature      double precision,
  wind_direction         integer,
  wind_speed             double precision,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.intervals (
  date                   timestamptz,
  driver_number          integer,
  gap_to_leader          text,
  "interval"             text,
  meeting_key            integer,
  session_key            integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.starting_grid (
  driver_number          integer,
  lap_duration           double precision,
  meeting_key            integer,
  "position"             integer,
  session_key            integer,       -- as returned: the qualifying session key
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE TABLE IF NOT EXISTS raw.car_data (
  brake                  integer,
  date                   timestamptz,
  driver_number          integer,
  drs                    integer,
  meeting_key            integer,
  n_gear                 integer,
  rpm                    integer,
  session_key            integer,
  speed                  integer,
  throttle               integer,
  _race_session_key      integer      NOT NULL,
  _raw_path              text         NOT NULL,
  _sha256                text         NOT NULL,
  _run_id                uuid         NOT NULL,
  _loaded_at             timestamptz  NOT NULL DEFAULT now(),
  _extra                 jsonb
);

CREATE INDEX IF NOT EXISTS meetings_partition ON raw.meetings (_race_session_key);
CREATE INDEX IF NOT EXISTS sessions_partition ON raw.sessions (_race_session_key);
CREATE INDEX IF NOT EXISTS drivers_partition ON raw.drivers (_race_session_key);
CREATE INDEX IF NOT EXISTS laps_partition ON raw.laps (_race_session_key);
CREATE INDEX IF NOT EXISTS stints_partition ON raw.stints (_race_session_key);
CREATE INDEX IF NOT EXISTS pit_partition ON raw.pit (_race_session_key);
CREATE INDEX IF NOT EXISTS position_partition ON raw.position (_race_session_key);
CREATE INDEX IF NOT EXISTS race_control_partition ON raw.race_control (_race_session_key);
CREATE INDEX IF NOT EXISTS session_result_partition ON raw.session_result (_race_session_key);
CREATE INDEX IF NOT EXISTS weather_partition ON raw.weather (_race_session_key);
CREATE INDEX IF NOT EXISTS intervals_partition ON raw.intervals (_race_session_key);
CREATE INDEX IF NOT EXISTS starting_grid_partition ON raw.starting_grid (_race_session_key);
-- car_data: this index also serves lookups by _race_session_key alone (leading column), so no separate one.
CREATE INDEX IF NOT EXISTS car_data_driver_date ON raw.car_data (_race_session_key, driver_number, date);
