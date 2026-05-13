from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import config
from ..io.artifacts import read_json, safe_filename, utcstamp, write_json
from .deadline import fetch_calendar, find_next_race
from .diff import compute_diff


def current_race_context() -> dict[str, Any]:
    """Return a compact identity for the currently upcoming race.

    Transfer budgets are charged against the team from the previous race weekend,
    not against the currently edited midweek team. We therefore need a stable
    race/week key so the first scraped team for a race week can be retained as
    the baseline for all later FP/SQ optimizer runs.
    """

    races = fetch_calendar()
    race = find_next_race(__import__("datetime").datetime.now(__import__("datetime").timezone.utc), races)
    if race is None:
        raise RuntimeError("No upcoming race found in F1 calendar")
    return {
        "round": race.get("round"),
        "name": race.get("name"),
        "location": race.get("location"),
    }


def baseline_key(*, team_id: int, race_context: dict[str, Any] | None) -> str:
    if race_context and race_context.get("round") is not None:
        return f"team{team_id}_round{race_context['round']}"
    if race_context and race_context.get("name"):
        return f"team{team_id}_{safe_filename(str(race_context['name']))}"
    return f"team{team_id}_unknown"


def baseline_path(*, team_id: int, race_context: dict[str, Any] | None) -> Path:
    return config.STATE_DIR / "transfer_baselines" / f"{safe_filename(baseline_key(team_id=team_id, race_context=race_context))}.json"


def get_or_create_transfer_baseline(
    *,
    team_id: int,
    race_context: dict[str, Any] | None,
    current_state: dict[str, Any],
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Load or create the immutable transfer baseline for this team/race.

    The baseline is the previous race weekend's locked team as it appears before
    this race weekend's swaps are made. Midweek adjustments should be charged by
    comparing the *ideal* team against this baseline, not against the current
    official-site team, because the official site lets us revise provisional
    transfers without paying for the intermediate versions.
    """

    path = baseline_path(team_id=team_id, race_context=race_context)
    existing = None if force_refresh else read_json(path, default=None)
    if existing:
        existing["created"] = False
        existing["path"] = str(path)
        return existing

    baseline = {
        "schema_version": 1,
        "created": True,
        "path": str(path),
        "ts_utc": utcstamp(),
        "team_id": team_id,
        "race_context": race_context,
        "source": "site_before_first_seen_for_race_week",
        "team": {
            "drivers": list(current_state.get("drivers") or []),
            "constructors": list(current_state.get("constructors") or []),
            "boost_driver": current_state.get("boost_driver"),
        },
    }
    write_json(path, baseline)
    return baseline


def compute_baseline_transfer_policy(
    *,
    baseline: dict[str, Any],
    current_state: dict[str, Any],
    ideal: dict[str, Any],
    free_transfers: int,
) -> dict[str, Any]:
    baseline_team = baseline.get("team") or baseline
    baseline_diff = compute_diff(baseline_team, ideal)
    current_diff = compute_diff(current_state, ideal)
    baseline_transfers = int(baseline_diff.get("transfers_required") or 0)
    current_transfers = int(current_diff.get("transfers_required") or 0)
    allowed = baseline_transfers <= int(free_transfers)
    return {
        "apply": allowed,
        "reason": (
            f"Ideal team is {baseline_transfers} transfer(s) from the race-week baseline; "
            f"{free_transfers} free transfer(s) available"
            if allowed
            else f"Ideal team is {baseline_transfers} transfer(s) from the race-week baseline; "
            f"only {free_transfers} free transfer(s) available"
        ),
        "free_transfers": int(free_transfers),
        "baseline_transfers_required": baseline_transfers,
        "current_site_transfers_required": current_transfers,
        "baseline_diff": baseline_diff,
        "current_diff": current_diff,
        "baseline": baseline,
    }
