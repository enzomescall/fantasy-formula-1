from __future__ import annotations

import json
import itertools
import re
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from f1fantasy.mappings import DRIVER_ABBR_TO_FULL, CONSTRUCTOR_ABBR_TO_FULL

URL = "https://f1fantasytools.com/team-calculator"
OUT = BASE / "state" / "miami_moves_analysis.json"

CURRENT_TEAM = {
    "drivers": ["Oliver Bearman", "Kimi Antonelli", "Liam Lawson", "Franco Colapinto", "Nico Hulkenberg"],
    "constructors": ["Ferrari", "Mercedes"],
    "boost_driver": "Kimi Antonelli",
    "budget_cap": 109.1,
    "free_transfers": 2,
    "penalty_per_extra": 10,
}

FULL_TO_DRIVER_ABBR = {v: k for k, v in DRIVER_ABBR_TO_FULL.items()}
FULL_TO_CON_ABBR = {v: k for k, v in CONSTRUCTOR_ABBR_TO_FULL.items()}


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        },
    )
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        return r.read().decode("utf-8", errors="ignore")


def extract_next_payload(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, flags=re.DOTALL)
    if not chunks:
        raise RuntimeError("Could not find self.__next_f.push payload in HTML")
    raw = max(chunks, key=len)
    return raw.encode("utf-8").decode("unicode_escape")


def extract_json_object_from_payload(payload: str) -> dict:
    start = payload.find("{")
    if start == -1:
        raise RuntimeError("Could not locate JSON object start in payload")
    depth = 0
    for i in range(start, len(payload)):
        c = payload[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(payload[start : i + 1])
    raise RuntimeError("Unbalanced braces while extracting JSON object")


def load_data() -> dict:
    html = fetch(URL)
    payload = extract_next_payload(html)
    return extract_json_object_from_payload(payload)


def build_maps(data: dict):
    sim = (data.get("analystSims") or [])[0]
    drv_pts = (sim.get("drivers") or {}).get("pts") or {}
    con_pts = (sim.get("constructors") or {}).get("pts") or {}

    driver_rows = []
    driver_price = {}
    driver_ep = {}
    for d in data.get("drivers") or []:
        if d.get("type") != "driver":
            continue
        abbr = str(d["abbreviation"])
        did = str(d["id"])
        price = float(d["price"])
        ep = float(drv_pts.get(did, 0.0))
        name = DRIVER_ABBR_TO_FULL.get(abbr, abbr)
        driver_rows.append({"abbr": abbr, "name": name, "price": price, "expected_points": ep})
        driver_price[abbr] = price
        driver_ep[abbr] = ep

    constructor_rows = []
    constructor_price = {}
    constructor_ep = {}
    for c in data.get("constructors") or []:
        if c.get("type") != "constructor":
            continue
        abbr = str(c["abbreviation"])
        price = float(c["price"])
        ep = float(con_pts.get(abbr, 0.0))
        name = CONSTRUCTOR_ABBR_TO_FULL.get(abbr, abbr)
        constructor_rows.append({"abbr": abbr, "name": name, "price": price, "expected_points": ep})
        constructor_price[abbr] = price
        constructor_ep[abbr] = ep

    return sim, driver_rows, constructor_rows, driver_price, driver_ep, constructor_price, constructor_ep


def team_cost(driver_abbrs, constructor_abbrs, driver_price, constructor_price):
    return round(sum(driver_price[a] for a in driver_abbrs) + sum(constructor_price[a] for a in constructor_abbrs), 3)


def team_ep(driver_abbrs, constructor_abbrs, boost_abbr, driver_ep, constructor_ep):
    return round(sum(driver_ep[a] for a in driver_abbrs) + sum(constructor_ep[a] for a in constructor_abbrs) + driver_ep[boost_abbr], 3)


def diff_count(cur_dr, cur_con, new_dr, new_con):
    return len(set(new_dr) - set(cur_dr)) + len(set(new_con) - set(cur_con))


def analyze():
    data = load_data()
    sim, driver_rows, constructor_rows, driver_price, driver_ep, constructor_price, constructor_ep = build_maps(data)

    cur_dr = [FULL_TO_DRIVER_ABBR[n] for n in CURRENT_TEAM["drivers"]]
    cur_con = [FULL_TO_CON_ABBR[n] for n in CURRENT_TEAM["constructors"]]
    cur_boost = FULL_TO_DRIVER_ABBR[CURRENT_TEAM["boost_driver"]]
    budget_cap = CURRENT_TEAM["budget_cap"]
    free_transfers = CURRENT_TEAM["free_transfers"]
    penalty_per_extra = CURRENT_TEAM["penalty_per_extra"]

    current_cost = team_cost(cur_dr, cur_con, driver_price, constructor_price)
    spare_budget = round(budget_cap - current_cost, 3)
    current_ep = team_ep(cur_dr, cur_con, cur_boost, driver_ep, constructor_ep)

    all_driver_abbrs = [r["abbr"] for r in driver_rows]
    all_constructor_abbrs = [r["abbr"] for r in constructor_rows]

    best_exact_2 = []
    best_with_penalty = []

    for con_pair in itertools.combinations(all_constructor_abbrs, 2):
        con_pair = tuple(sorted(con_pair))
        con_cost = sum(constructor_price[c] for c in con_pair)
        if con_cost > budget_cap:
            continue
        for drs in itertools.combinations(all_driver_abbrs, 5):
            drs = tuple(sorted(drs))
            cost = con_cost + sum(driver_price[d] for d in drs)
            if cost > budget_cap + 1e-9:
                continue
            transfers = diff_count(cur_dr, cur_con, drs, con_pair)
            for boost in drs:
                raw_ep = team_ep(drs, con_pair, boost, driver_ep, constructor_ep)
                penalty = max(0, transfers - free_transfers) * penalty_per_extra
                net_ep = raw_ep - penalty
                record = {
                    "drivers": [DRIVER_ABBR_TO_FULL[d] for d in drs],
                    "constructors": [CONSTRUCTOR_ABBR_TO_FULL[c] for c in con_pair],
                    "boost_driver": DRIVER_ABBR_TO_FULL[boost],
                    "team_cost": round(cost, 3),
                    "spare_budget": round(budget_cap - cost, 3),
                    "raw_expected_points": raw_ep,
                    "transfers_required": transfers,
                    "penalty_points": penalty,
                    "net_expected_points": round(net_ep, 3),
                    "gain_vs_current_raw": round(raw_ep - current_ep, 3),
                    "gain_vs_current_net": round(net_ep - current_ep, 3),
                    "moves": {
                        "drivers_out": [DRIVER_ABBR_TO_FULL[d] for d in cur_dr if d not in drs],
                        "drivers_in": [DRIVER_ABBR_TO_FULL[d] for d in drs if d not in cur_dr],
                        "constructors_out": [CONSTRUCTOR_ABBR_TO_FULL[c] for c in cur_con if c not in con_pair],
                        "constructors_in": [CONSTRUCTOR_ABBR_TO_FULL[c] for c in con_pair if c not in cur_con],
                        "boost_from": CURRENT_TEAM["boost_driver"],
                        "boost_to": DRIVER_ABBR_TO_FULL[boost],
                    },
                }
                if transfers == 2:
                    best_exact_2.append(record)
                best_with_penalty.append(record)

    best_exact_2.sort(key=lambda r: (r["raw_expected_points"], r["net_expected_points"]), reverse=True)
    best_with_penalty.sort(key=lambda r: (r["net_expected_points"], r["raw_expected_points"]), reverse=True)

    out = {
        "source_url": URL,
        "sim": sim,
        "current_team": {
            "drivers": CURRENT_TEAM["drivers"],
            "constructors": CURRENT_TEAM["constructors"],
            "boost_driver": CURRENT_TEAM["boost_driver"],
            "budget_cap": budget_cap,
            "team_cost": current_cost,
            "spare_budget": spare_budget,
            "expected_points": current_ep,
            "free_transfers": free_transfers,
            "penalty_per_extra": penalty_per_extra,
        },
        "drivers": sorted(driver_rows, key=lambda r: r["abbr"]),
        "constructors": sorted(constructor_rows, key=lambda r: r["abbr"]),
        "best_exact_2_moves": best_exact_2[:20],
        "best_with_penalty": best_with_penalty[:20],
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "current_team": out["current_team"],
        "top_exact_2": best_exact_2[:5],
        "top_with_penalty": best_with_penalty[:5],
    }, indent=2))


if __name__ == "__main__":
    analyze()
