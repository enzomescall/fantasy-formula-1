#!/usr/bin/env python3
"""Export F1 Fantasy state to web dashboard data directory.

Reads state/*.json from the repo and writes clean, dashboard-ready JSON
to /var/www/enzom/f1-fantasy/data/.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_ROOT / "state"
WEB_DATA_DIR = Path("/var/www/enzom/f1-fantasy/data")


def load_json(path):
    """Load a JSON file, returning None if missing or invalid."""
    if not path.exists():
        return None
    try:
        with open(str(path)) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_json(path, data):
    """Write JSON with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def export_current(last_run, team_state):
    """Build current team JSON from best available source."""
    # Prefer site_before from last_run (most recent snapshot)
    if last_run and "site_before" in last_run and last_run["site_before"]:
        sb = last_run["site_before"]
        budget = None
        if "inputs" in last_run and "budget" in last_run["inputs"]:
            budget = last_run["inputs"]["budget"]
        return {
            "team_name": sb.get("team_name", "Pascal GP 1"),
            "team_id": sb.get("team_id", 1),
            "drivers": [
                {"name": d, "boosted": d == sb.get("boost_driver")}
                for d in sb.get("drivers", [])
            ],
            "constructors": sb.get("constructors", []),
            "boost_driver": sb.get("boost_driver"),
            "budget": {
                "remaining_m": budget.get("remaining_m", 0) if budget else 0,
                "used_m": budget.get("used_m", 0) if budget else 0,
                "cap_m": budget.get("cap_m", 105.4) if budget else 105.4,
            } if budget else None,
            "updated_utc": sb.get("ts_utc", ""),
        }

    # Fallback to team_state.json
    if team_state:
        return {
            "team_name": team_state.get("team_name", "Pascal GP 1"),
            "team_id": team_state.get("team_id", 1),
            "drivers": [
                {"name": d, "boosted": d == team_state.get("boost_driver")}
                for d in team_state.get("drivers", [])
            ],
            "constructors": team_state.get("constructors", []),
            "boost_driver": team_state.get("boost_driver"),
            "budget": None,
            "updated_utc": team_state.get("ts_utc", ""),
        }

    # No data at all
    return {
        "team_name": "Pascal GP 1",
        "team_id": 1,
        "drivers": [],
        "constructors": [],
        "boost_driver": None,
        "budget": None,
        "updated_utc": "",
    }


def export_optimal(last_optimal):
    """Build optimal team JSON."""
    if not last_optimal:
        return {"drivers": [], "constructors": [], "optimal": {}, "ts_utc": ""}

    return {
        "drivers": last_optimal.get("drivers", []),
        "constructors": last_optimal.get("constructors", []),
        "optimal": last_optimal.get("optimal", {}),
        "budget": last_optimal.get("budget", {}),
        "remaining_m": last_optimal.get("remaining_m", 0),
        "total_m": last_optimal.get("total_m", 0),
        "used_m": last_optimal.get("used_m", 0),
        "cap_m": last_optimal.get("cap_m", 105.4),
        "ts_utc": last_optimal.get("ts_utc", ""),
    }


def export_diff(last_run):
    """Build diff/changes-needed JSON."""
    if not last_run:
        return {"noop": True, "drivers_remove": [], "drivers_add": [],
                "constructors_remove": [], "constructors_add": [],
                "boost_change": False, "transfers_required": 0, "policy": None}

    diff = last_run.get("diff", {})
    policy = last_run.get("policy_decision", {})
    transfer_status = last_run.get("transfer_status", {})

    return {
        "noop": diff.get("noop", True),
        "drivers_remove": diff.get("drivers_remove", []),
        "drivers_add": diff.get("drivers_add", []),
        "constructors_remove": diff.get("constructors_remove", []),
        "constructors_add": diff.get("constructors_add", []),
        "boost_change": diff.get("boost_change", False),
        "current_boost": diff.get("current_boost"),
        "ideal_boost": diff.get("ideal_boost"),
        "transfers_required": diff.get("transfers_required", 0),
        "policy": {
            "apply": policy.get("apply", False),
            "reason": policy.get("reason", ""),
            "free_transfers": transfer_status.get("free_transfers"),
        },
        "ts_utc": last_run.get("ts_utc", ""),
    }


def export_history():
    """Compile history snapshots from state/history/."""
    history_dir = STATE_DIR / "history"
    snapshots = []

    if history_dir.exists():
        for f in sorted(history_dir.glob("*.json")):
            data = load_json(f)
            if data:
                snapshots.append({
                    "ts_utc": data.get("ts_utc", ""),
                    "drivers": data.get("drivers", []),
                    "constructors": data.get("constructors", []),
                    "boost_driver": data.get("boost_driver"),
                    "budget_remaining_m": (data.get("budget", {}) or {}).get("remaining_m"),
                    "source_file": f.name,
                })

    return {"snapshots": snapshots}


def export_meta(last_run):
    """Build meta info JSON."""
    sim = {}
    if last_run:
        sim = last_run.get("inputs", {}).get("sim", {})

    return {
        "exported_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": sim.get("season", 2026),
        "raceweek": sim.get("raceweek"),
        "sim_name": sim.get("name", ""),
        "source": "f1fantasytools + fantasy.formula1.com",
    }


def main():
    # Ensure output dir exists
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load source files
    last_run = load_json(STATE_DIR / "last_run.json")
    team_state = load_json(STATE_DIR / "team_state.json")
    last_optimal = load_json(STATE_DIR / "last_optimal_with_budget.json")

    # Export each data file
    write_json(WEB_DATA_DIR / "current.json", export_current(last_run, team_state))
    write_json(WEB_DATA_DIR / "optimal.json", export_optimal(last_optimal))
    write_json(WEB_DATA_DIR / "diff.json", export_diff(last_run))
    write_json(WEB_DATA_DIR / "history.json", export_history())
    write_json(WEB_DATA_DIR / "meta.json", export_meta(last_run))

    print("Exported to %s" % WEB_DATA_DIR)
    for f in sorted(WEB_DATA_DIR.glob("*.json")):
        print("  %s (%d bytes)" % (f.name, f.stat().st_size))


if __name__ == "__main__":
    main()
