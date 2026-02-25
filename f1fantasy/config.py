from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

STATE_DIR = BASE_DIR / "state"
HISTORY_DIR = STATE_DIR / "history"
ARTIFACTS_DIR = STATE_DIR / "artifacts"

FANTASY_TEAM_URL = "https://fantasy.formula1.com/en/my-team/{team_id}"
FANTASY_HOME_URL = "https://fantasy.formula1.com/en/my-team"

DEFAULT_PROFILE_DIR = str(BASE_DIR / ".playwright-profile")
DEFAULT_EXPECTED_TEAM_NAME = "Pascal GP 1"
