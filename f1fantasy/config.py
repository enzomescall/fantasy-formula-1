from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

STATE_DIR = BASE_DIR / "state"
HISTORY_DIR = STATE_DIR / "history"
ARTIFACTS_DIR = STATE_DIR / "artifacts"

FANTASY_TEAM_URL = "https://fantasy.formula1.com/en/my-team/{team_id}"
FANTASY_HOME_URL = "https://fantasy.formula1.com/en/my-team"
F1_LOGIN_URL = "https://account.formula1.com/#/en/login"

DEFAULT_PROFILE_DIR = str(BASE_DIR / ".playwright-profile")
DEFAULT_EXPECTED_TEAM_NAME = "Pascal GP 1"


def _load_local_env() -> dict[str, str]:
    env_path = BASE_DIR / ".env"
    data: dict[str, str] = {}
    if not env_path.exists():
        return data
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        data[key.strip()] = value.strip()
    return data


_LOCAL_ENV = _load_local_env()
F1_EMAIL = os.environ.get('F1_EMAIL') or _LOCAL_ENV.get('F1_EMAIL')
F1_PASSWORD = os.environ.get('F1_PASSWORD') or _LOCAL_ENV.get('F1_PASSWORD')
