from __future__ import annotations

from typing import Any

from .diff import compute_diff

# Tracks where pre/post-qualifying decisions tend to be unusually valuable.
QUALIFYING_HEAVY_RACES = {
    "monaco": "Monaco is the clearest qualifying-first race; dry qualifying position is highly predictive.",
    "hungary": "Hungary is relatively hard to overtake, so post-qualifying corrections can be valuable.",
    "singapore": "Singapore is a street circuit with high qualifying importance and high incident risk.",
    "netherlands": "Zandvoort is relatively qualifying-sensitive and is also a sprint weekend in 2026.",
}

SPRINT_CHIP_RACES_2026 = {
    "canada": "Good Auto Pilot or No Negative candidate: sprint points plus wall/weather volatility.",
    "great britain": "Strong Limitless candidate: sprint weekend with relatively lower chaos than street circuits.",
    "netherlands": "Strong x3 candidate if a top driver is clear by then; sprint points amplify the multiplier.",
    "singapore": "Strong No Negative candidate: sprint weekend plus street-circuit chaos, heat, and safety-car risk.",
}


def race_name_key(race_context: dict[str, Any] | None) -> str:
    if not race_context:
        return ""
    name = str(race_context.get("race_name") or race_context.get("name") or "")
    return name.lower()


def is_qualifying_heavy_race(race_context: dict[str, Any] | None) -> bool:
    key = race_name_key(race_context)
    return any(token in key for token in QUALIFYING_HEAVY_RACES)


def is_sprint_chip_race(race_context: dict[str, Any] | None) -> bool:
    key = race_name_key(race_context)
    return any(token in key for token in SPRINT_CHIP_RACES_2026)


def transfer_advice(*, transfers_required: int, free_transfers: int, penalty_points_per_extra: int | None = None) -> list[str]:
    notes: list[str] = []
    if transfers_required >= 4:
        extra = max(0, transfers_required - free_transfers)
        penalty_text = ""
        if extra and penalty_points_per_extra:
            penalty_text = f" (about {abs(penalty_points_per_extra) * extra} penalty points if paid)"
        notes.append(
            f"Ideal team is {transfers_required} swaps from the race-week baseline; consider Wildcard instead of forcing paid transfers{penalty_text}."
        )
    elif transfers_required == 3 and free_transfers < 3:
        notes.append(
            "Ideal team is 3 swaps away. If a useful Sprint/x3 weekend is coming, preserving or reaching 3 free transfers may be more valuable than spending now."
        )
    elif free_transfers >= 3:
        notes.append(
            "You currently have 3 free transfers; avoid burning Wildcard unless the pecking order has materially changed or the ideal team needs 4+ baseline swaps."
        )
    return notes


def compare_chip_variants(*, standard: dict, limitless: dict | None, x3: dict | None) -> dict[str, Any]:
    standard_points = float(standard.get("expected_points") or 0)
    out: dict[str, Any] = {"standard_expected_points": round(standard_points, 3)}
    if limitless:
        lp = float(limitless.get("expected_points") or 0)
        out["limitless"] = {
            "expected_points": round(lp, 3),
            "uplift_vs_standard": round(lp - standard_points, 3),
            "drivers": limitless.get("drivers"),
            "constructors": limitless.get("constructors"),
            "boost": limitless.get("boost"),
            "total_cost": limitless.get("total_cost"),
        }
    if x3:
        xp = float(x3.get("expected_points") or 0)
        out["x3_boost"] = {
            "expected_points": round(xp, 3),
            "uplift_vs_standard": round(xp - standard_points, 3),
            "drivers": x3.get("drivers"),
            "constructors": x3.get("constructors"),
            "x3_boost": x3.get("x3_boost"),
            "standard_2x_boost": x3.get("boost"),
            "total_cost": x3.get("total_cost"),
        }
    return out


def build_chip_strategy_report(
    *,
    race_context: dict[str, Any] | None,
    standard_optimal: dict,
    transfer_policy: dict | None,
    transfer_status: dict,
    limitless_optimal: dict | None = None,
    x3_optimal: dict | None = None,
    site_before: dict | None = None,
    ideal: dict | None = None,
) -> dict[str, Any]:
    transfers_required = int((transfer_policy or {}).get("baseline_transfers_required") or 0)
    free_transfers = int(transfer_status.get("free_transfers") or 0)
    penalty = transfer_status.get("penalty_points_per_extra")
    notes = transfer_advice(
        transfers_required=transfers_required,
        free_transfers=free_transfers,
        penalty_points_per_extra=penalty,
    )

    key = race_name_key(race_context)
    sprint = is_sprint_chip_race(race_context)
    qualifying_heavy = is_qualifying_heavy_race(race_context)

    if sprint:
        for token, reason in SPRINT_CHIP_RACES_2026.items():
            if token in key:
                notes.append(f"Sprint chip watch: {reason}")
                break
        if free_transfers < 3:
            notes.append("Sprint transfer planning: if x3 is a live option for this weekend, check whether we should conserve transfers rather than spend into a low-uplift normal team.")

    if qualifying_heavy:
        for token, reason in QUALIFYING_HEAVY_RACES.items():
            if token in key:
                notes.append(f"Final Fix watch: {reason} Schedule/expect a post-qualifying one-transfer analysis.")
                break

    if key and "singapore" in key:
        notes.append("No Negative watch: Singapore combines street-circuit downside with Sprint scoring. Escalate if weather forecasts mention rain or storms.")
    elif key and "canada" in key:
        notes.append("No Negative backup watch: Canada has walls and weather volatility; rain should move No Negative up the list.")

    if site_before and ideal:
        current_vs_ideal = compute_diff(site_before, ideal)
    else:
        current_vs_ideal = None

    chip_math = compare_chip_variants(standard=standard_optimal, limitless=limitless_optimal, x3=x3_optimal)
    if chip_math.get("limitless", {}).get("uplift_vs_standard", 0) >= 10:
        notes.append("Limitless math is materially above the normal budget team; compare this uplift against the planned Silverstone/Sprint reserve before activating.")
    if chip_math.get("x3_boost", {}).get("uplift_vs_standard", 0) >= 8:
        notes.append("x3 math is materially above the normal 2x setup; use only if the top x3 driver also has low reliability/weather downside.")

    return {
        "schema_version": 1,
        "race_context": race_context,
        "flags": {
            "sprint_chip_race": sprint,
            "qualifying_heavy_race": qualifying_heavy,
        },
        "transfer_distance": {
            "baseline_transfers_required": transfers_required,
            "free_transfers": free_transfers,
            "current_site_transfers_required": (current_vs_ideal or {}).get("transfers_required"),
        },
        "chip_math": chip_math,
        "notes": notes,
    }
