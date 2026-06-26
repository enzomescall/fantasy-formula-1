from __future__ import annotations

"""Local fallback projection model for F1 Fantasy expected points.

This module is intentionally independent of f1fantasytools.com. It turns a
small JSON projection file (or future FastF1/Monte Carlo outputs) into the same
embedded-data shape consumed by the existing optimizer.

The first version is deliberately transparent rather than clever: each driver
row contains expected weekend outcomes, we apply the official F1 Fantasy scoring
rules, roll driver contributions up to constructors, then reuse the optimizer.
"""

import json
from pathlib import Path
from typing import Any

from .f1fantasytools import compute_optimal

QUALI_RESULT_POINTS = {1: 10, 2: 9, 3: 8, 4: 7, 5: 6, 6: 5, 7: 4, 8: 3, 9: 2, 10: 1}
SPRINT_RESULT_POINTS = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}
RACE_RESULT_POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}

DEFAULT_SIM_NAME = "Local backup F1 Fantasy model"


def _float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if value is None:
        return default
    return float(value)


def _prob(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _float(row, key, default)))


def _position_points(pos: float | int | None, table: dict[int, int], *, nc_points: int = 0) -> float:
    """Score an expected finishing position by linear interpolation.

    If future models produce full position distributions, this function can be
    replaced by an expectation over probabilities. Interpolation gives a stable
    first-pass score for mean/median position projections.
    """

    if pos is None:
        return 0.0
    p = float(pos)
    if p <= 0:
        return float(nc_points)
    lo = int(p)
    hi = lo + 1
    if abs(p - lo) < 1e-9:
        return float(table.get(lo, 0))
    lo_pts = float(table.get(lo, 0))
    hi_pts = float(table.get(hi, 0))
    return lo_pts + (p - lo) * (hi_pts - lo_pts)


def _q_progress_points(q_pos: float | int | None) -> tuple[float, float]:
    """Expected Q2/Q3 progression indicators for constructor bonus math."""

    if q_pos is None:
        return 0.0, 0.0
    p = float(q_pos)
    # Smooth boundary approximations: position 15.5 is half-likely Q2, 10.5 half-likely Q3.
    q2 = max(0.0, min(1.0, 16.0 - p))
    q3 = max(0.0, min(1.0, 11.0 - p))
    return q2, q3


def score_driver_projection(row: dict[str, Any]) -> dict[str, float]:
    """Return expected driver and constructor-contributing points for one driver.

    Input row fields are optional; absent stats default to zero contribution:
    - quali_pos, quali_no_time_prob
    - sprint_start, sprint_finish, sprint_overtakes, sprint_fastest_lap_prob,
      sprint_dnf_prob, sprint_dsq_prob
    - race_start, race_finish, race_overtakes, race_fastest_lap_prob,
      dotd_prob, race_dnf_prob, race_dsq_prob
    """

    quali_pos = row.get("quali_pos")
    sprint_finish = row.get("sprint_finish")
    race_finish = row.get("race_finish")

    quali = _position_points(quali_pos, QUALI_RESULT_POINTS, nc_points=-5)
    quali += -5.0 * _prob(row, "quali_no_time_prob")

    sprint_delta = 0.0
    if row.get("sprint_start") is not None and sprint_finish is not None:
        # Positive delta means positions gained. Sprint position-loss penalty is capped at -10.
        sprint_delta = _float(row, "sprint_start") - float(sprint_finish)
        sprint_delta = max(-10.0, sprint_delta)
    sprint = (
        _position_points(sprint_finish, SPRINT_RESULT_POINTS, nc_points=-10)
        + sprint_delta
        + _float(row, "sprint_overtakes")
        + 5.0 * _prob(row, "sprint_fastest_lap_prob")
        - 10.0 * (_prob(row, "sprint_dnf_prob") + _prob(row, "sprint_dsq_prob"))
    )

    race_delta = 0.0
    if row.get("race_start") is not None and race_finish is not None:
        race_delta = _float(row, "race_start") - float(race_finish)
    race_without_dotd = (
        _position_points(race_finish, RACE_RESULT_POINTS, nc_points=-20)
        + race_delta
        + _float(row, "race_overtakes")
        + 10.0 * _prob(row, "race_fastest_lap_prob")
        - 20.0 * (_prob(row, "race_dnf_prob") + _prob(row, "race_dsq_prob"))
    )
    dotd = 10.0 * _prob(row, "dotd_prob")

    q2_prob, q3_prob = _q_progress_points(quali_pos)
    return {
        "driver_points": round(quali + sprint + race_without_dotd + dotd, 3),
        # Constructors receive their drivers' weekend points except Driver of the Day.
        "constructor_driver_points": round(quali + sprint + race_without_dotd, 3),
        "quali_points": round(quali, 3),
        "sprint_points": round(sprint, 3),
        "race_points": round(race_without_dotd + dotd, 3),
        "q2_prob": round(q2_prob, 3),
        "q3_prob": round(q3_prob, 3),
    }


def _constructor_quali_bonus(q2_probs: list[float], q3_probs: list[float]) -> float:
    if len(q2_probs) < 2 or len(q3_probs) < 2:
        return 0.0
    q2_sum = sum(q2_probs[:2])
    q3_sum = sum(q3_probs[:2])
    # Official rules are discrete; use expected bucket values for a transparent first pass.
    if q3_sum >= 1.5:
        return 10.0
    if q3_sum >= 0.5:
        return 5.0
    if q2_sum >= 1.5:
        return 3.0
    if q2_sum >= 0.5:
        return 1.0
    return -1.0


def build_projection_payload(projection: dict[str, Any]) -> dict[str, Any]:
    """Convert backup-model JSON into the optimizer's f1fantasytools-compatible shape."""

    drivers_in = projection.get("drivers") or []
    constructors_in = projection.get("constructors") or []
    if not drivers_in or not constructors_in:
        raise ValueError("backup projection requires non-empty drivers and constructors lists")

    drivers_meta: list[dict[str, Any]] = []
    driver_pts_by_id: dict[str, float] = {}
    constructor_driver_parts: dict[str, list[dict[str, float]]] = {}

    for i, row in enumerate(drivers_in, start=1):
        code = str(row.get("code") or row.get("abbreviation") or "").upper()
        if not code:
            raise ValueError(f"driver row {i} is missing code/abbreviation")
        drv_id = str(row.get("id") or code)
        team = str(row.get("team") or row.get("constructor") or "").upper()
        if not team:
            raise ValueError(f"driver {code} is missing team/constructor")
        score = score_driver_projection(row)
        drivers_meta.append({"type": "driver", "id": drv_id, "abbreviation": code, "price": float(row["price"])})
        driver_pts_by_id[drv_id] = score["driver_points"]
        constructor_driver_parts.setdefault(team, []).append(score)

    constructor_meta: list[dict[str, Any]] = []
    constructor_pts: dict[str, float] = {}
    for row in constructors_in:
        code = str(row.get("code") or row.get("abbreviation") or "").upper()
        if not code:
            raise ValueError("constructor row is missing code/abbreviation")
        parts = constructor_driver_parts.get(code, [])
        q2_probs = [p["q2_prob"] for p in parts]
        q3_probs = [p["q3_prob"] for p in parts]
        points = sum(p["constructor_driver_points"] for p in parts)
        points += _constructor_quali_bonus(q2_probs, q3_probs)
        points += _float(row, "pit_stop_points")
        points += _float(row, "fastest_pit_stop_prob") * 5.0
        points += _float(row, "pit_world_record_prob") * 15.0
        constructor_meta.append({"type": "constructor", "abbreviation": code, "price": float(row["price"])})
        constructor_pts[code] = round(points, 3)

    sim = {
        "id": str(projection.get("id") or "local-backup"),
        "name": str(projection.get("name") or DEFAULT_SIM_NAME),
        "raceweek": projection.get("raceweek"),
        "season": projection.get("season"),
        "drivers": {"pts": driver_pts_by_id},
        "constructors": {"pts": constructor_pts},
    }
    return {"drivers": drivers_meta, "constructors": constructor_meta, "analystSims": [sim]}


def load_projection(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_optimal_and_prices_from_projection(
    max_budget: float,
    projection_path: str | Path,
    *,
    scoring_mode: str = "standard",
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    payload = build_projection_payload(load_projection(projection_path))
    optimal = compute_optimal(max_budget, payload, scoring_mode=scoring_mode)
    driver_prices = {str(d["abbreviation"]): float(d["price"]) for d in payload["drivers"]}
    constructor_prices = {str(c["abbreviation"]): float(c["price"]) for c in payload["constructors"]}
    optimal["projection_source"] = "backup_model"
    return optimal, {"drivers": driver_prices, "constructors": constructor_prices}
