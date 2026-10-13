-- Pipeline state: one row per extract unit and per load partition.
-- Convention for the metadata endpoints (meetings, sessions): race_session_key holds the year.
CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.extract_state (
  endpoint          text NOT NULL,
  race_session_key  integer NOT NULL,   -- for meetings/sessions: the year
  chunk_key         text NOT NULL,
  status            text NOT NULL CHECK (status IN ('pending','done','empty','deferred','failed')),
  attempts          integer NOT NULL DEFAULT 0,
  http_status       integer,
  last_error        text,
  record_count      integer,
  sha256            text,
  raw_path          text,
  last_run_id       uuid,
  first_planned_at  timestamptz NOT NULL DEFAULT now(),
  fetched_at        timestamptz,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (endpoint, race_session_key, chunk_key)
);

CREATE TABLE IF NOT EXISTS meta.load_state (
  endpoint          text NOT NULL,
  race_session_key  integer NOT NULL,
  files_fingerprint text NOT NULL,      -- hash over sorted chunk sha256s
  row_count         integer NOT NULL,
  loaded_at         timestamptz NOT NULL DEFAULT now(),
  run_id            uuid NOT NULL,
  PRIMARY KEY (endpoint, race_session_key)
);
