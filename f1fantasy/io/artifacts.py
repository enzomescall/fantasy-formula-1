from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any

from .. import config


def utcstamp() -> str:
    # timezone-aware UTC timestamp (avoids datetime.utcnow() deprecation warnings)
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_filename(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s or "")
    return s.strip("_") or "file"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def ensure_state_dirs() -> None:
    for d in (config.STATE_DIR, config.HISTORY_DIR, config.ARTIFACTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def run_artifacts_dir(team_id: int, ts_utc: str | None = None) -> Path:
    ts = (ts_utc or utcstamp()).replace(":", "-")
    p = config.ARTIFACTS_DIR / f"run_{ts}_team{team_id}"
    p.mkdir(parents=True, exist_ok=True)
    return p
