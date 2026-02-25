from __future__ import annotations

import re


def normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def as_set(names: list[str] | None) -> set[str]:
    return {normalize_name(n) for n in (names or [])}


def compute_diff(current_state: dict, ideal: dict) -> dict:
    cur_dr = current_state.get("drivers", [])
    cur_con = current_state.get("constructors", [])
    cur_boost = current_state.get("boost_driver")

    ideal_dr = ideal.get("drivers", [])
    ideal_con = ideal.get("constructors", [])
    ideal_boost = ideal.get("boost_driver")

    cur_dr_set = as_set(cur_dr)
    ideal_dr_set = as_set(ideal_dr)

    cur_con_set = as_set(cur_con)
    ideal_con_set = as_set(ideal_con)

    drivers_remove = [d for d in cur_dr if normalize_name(d) not in ideal_dr_set]
    drivers_add = [d for d in ideal_dr if normalize_name(d) not in cur_dr_set]

    constructors_remove = [c for c in cur_con if normalize_name(c) not in ideal_con_set]
    constructors_add = [c for c in ideal_con if normalize_name(c) not in cur_con_set]

    boost_change = (ideal_boost is not None) and (normalize_name(cur_boost) != normalize_name(ideal_boost))

    noop = cur_dr_set == ideal_dr_set and cur_con_set == ideal_con_set and (not boost_change)

    return {
        "noop": noop,
        "drivers_remove": drivers_remove,
        "drivers_add": drivers_add,
        "constructors_remove": constructors_remove,
        "constructors_add": constructors_add,
        "boost_change": boost_change,
        "current_boost": cur_boost,
        "ideal_boost": ideal_boost,
    }
