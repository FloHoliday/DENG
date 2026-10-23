"""Step 1, check source: fail early if OpenF1 is unreachable or locked by a live session."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import fetch

if __name__ == "__main__":
    fetch.check_source()
