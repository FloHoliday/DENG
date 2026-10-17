"""
Download a small OpenF1 test dataset (one race) as raw JSON -- exactly as the API returns it.

Usage (from the project/DENG folder):
    python3 ingestion/download_sample.py                  # default: 2025 Italian GP race
    python3 ingestion/download_sample.py 2024 Monaco      # any year + country

Output:  data/raw/<year>_<country>_race/<endpoint>.json
Only uses the Python standard library (no pip install needed).
"""
import json, sys, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path

BASE = "https://api.openf1.org/v1/"
YEAR = sys.argv[1] if len(sys.argv) > 1 else "2025"
COUNTRY = sys.argv[2] if len(sys.argv) > 2 else "Canada"
RIVER_FOR_TELEMETRY = 1  # car_data is huge -> only one driver for the sample

def get(endpoint, **params):
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):                      # simple retry with backoff
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:                     # OpenF1 answers 404 when there is simply no data
                print(f"  - {endpoint}: no data (404), skipping")
                return []
            if e.code < 500 and e.code != 429:    # other client errors won't fix themselves
                raise
            wait = 2 ** attempt
            print(f"  ! {endpoint} failed ({e}), retry in {wait}s")
            time.sleep(wait)
        except Exception as e:
            wait = 2 ** attempt
            print(f"  ! {endpoint} failed ({e}), retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")

sessions = get("sessions", year=YEAR, country_name=COUNTRY, session_name="Race")
if not sessions:
    sys.exit(f"No race found for {YEAR} {COUNTRY}")
s = sessions[0]
key = s["session_key"]
out = Path("data/raw") / f"{YEAR}_{COUNTRY.lower().replace(' ', '_')}_race"
out.mkdir(parents=True, exist_ok=True)
print(f"Race: {s['circuit_short_name']} {YEAR}  (session_key={key}) -> {out}")

(out / "session.json").write_text(json.dumps(s, indent=2))
for ep in ["laps", "stints", "pit", "weather", "race_control",
           "session_result", "starting_grid", "position", "drivers"]:
    if ep == "starting_grid":
        # the grid belongs to the qualifying session, so look it up by meeting instead
        rows = get(ep, meeting_key=s["meeting_key"])
    else:
        rows = get(ep, session_key=key)
    (out / f"{ep}.json").write_text(json.dumps(rows, indent=2))
    print(f"  {ep:15s} {len(rows):>7,} rows")
    time.sleep(0.5)                                # be polite to a free API

# high-frequency telemetry: one driver only
rows = get("car_data", session_key=key, driver_number=DRIVER_FOR_TELEMETRY)
(out / f"car_data_driver{DRIVER_FOR_TELEMETRY}.json").write_text(json.dumps(rows, indent=2))
print(f"  car_data (#{DRIVER_FOR_TELEMETRY})    {len(rows):>7,} rows")

# quick preview of what the raw data looks like
print("\n--- first lap record (raw) ---")
laps = json.loads((out / "laps.json").read_text())
print(json.dumps(laps[0] if laps else {}, indent=2))
print("\nDone.")
