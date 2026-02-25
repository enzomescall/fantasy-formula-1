#!/usr/bin/env python3
"""Compute optimal F1 Fantasy team under a max budget using data embedded in f1fantasytools.com/team-calculator.

Outputs JSON:
{
  "max_budget": 100.0,
  "constructors": ["MCL","FER"],
  "drivers": ["LEC","BOT","LAW","BOR","COL"],
  "boost": "LEC",
  "total_cost": 100.0,
  "expected_points": 168.0
}

Notes
- Uses the first analyst simulation preset embedded in the page (currently Rhter Sim).
- Team rules assumed: 2 constructors + 5 drivers, with exactly 1 boosted (2x) driver.
"""

import argparse
import itertools
import json
import re
import sys
from typing import Dict, List, Tuple

import urllib.request

URL = "https://f1fantasytools.com/team-calculator"


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="ignore")


def _extract_next_payload(html: str) -> str:
    """Extract and decode the largest self.__next_f.push([1,"..."]) string."""
    # There can be multiple pushes; we take the longest chunk as it usually contains the big JSON blob.
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, flags=re.DOTALL)
    if not chunks:
        raise RuntimeError("Could not find self.__next_f.push payload in HTML")
    raw = max(chunks, key=len)
    # raw is a JS string with backslash escapes (e.g. \" for quotes).
    # Decode using unicode_escape; this is usually sufficient for Next/React flight payloads.
    try:
        decoded = raw.encode("utf-8").decode("unicode_escape")
    except Exception as e:
        raise RuntimeError("Failed to decode __next_f payload: %s" % (e,))
    return decoded


def _extract_json_object_from_payload(payload: str) -> dict:
    """Payload looks like: '5:["$","$L..",null,{...}]'. Extract the {...}."""
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
                obj_str = payload[start : i + 1]
                return json.loads(obj_str)

    raise RuntimeError("Unbalanced braces while extracting JSON object")


class Pick(object):
    __slots__ = ("code", "price", "pts")

    def __init__(self, code, price, pts):
        self.code = code
        self.price = float(price)
        self.pts = float(pts)


def compute_optimal(max_budget: float, data: dict) -> dict:
    drivers_raw = data.get("drivers") or []
    constructors_raw = data.get("constructors") or []
    analyst_sims = data.get("analystSims") or []
    if not analyst_sims:
        raise RuntimeError("No analystSims found in embedded data")

    sim = analyst_sims[0]
    # Points maps
    # - constructors pts keyed by abbreviation (e.g. "MCL")
    # - drivers pts keyed by driver id (e.g. "MER_RUS")
    drv_pts: Dict[str, float] = (sim.get("drivers") or {}).get("pts") or {}
    con_pts: Dict[str, float] = (sim.get("constructors") or {}).get("pts") or {}

    # Master maps
    drv_meta: Dict[str, Tuple[str, float]] = {}  # id -> (abbr, price)
    for d in drivers_raw:
        if d.get("type") == "driver" and d.get("id") and d.get("abbreviation"):
            drv_meta[str(d["id"])] = (str(d["abbreviation"]), float(d["price"]))

    con_price: Dict[str, float] = {}
    for c in constructors_raw:
        if c.get("type") == "constructor" and c.get("abbreviation"):
            con_price[str(c["abbreviation"])] = float(c["price"])

    # Build pick lists.
    # For drivers, we use abbreviation as the pick code, but iterate using sim driver ids.
    drivers: List[Pick] = []
    for drv_id, pts in drv_pts.items():
        if drv_id in drv_meta:
            abbr, price = drv_meta[drv_id]
            drivers.append(Pick(code=abbr, price=price, pts=float(pts)))

    constructors: List[Pick] = [Pick(code=k, price=con_price[k], pts=float(v)) for k, v in con_pts.items() if k in con_price]

    if not drivers or not constructors:
        raise RuntimeError("Could not build drivers/constructors pick lists")

    best: Tuple[float, float, Tuple[str, str], Tuple[str, ...], str] | None = None
    # best = (points, cost, (C1,C2), (D1..D5), boost)

    for c1, c2 in itertools.combinations(constructors, 2):
        c_cost = c1.price + c2.price
        c_points = c1.pts + c2.pts
        if c_cost >= max_budget:
            continue

        # Choose 5 drivers
        for ds in itertools.combinations(drivers, 5):
            d_cost = sum(d.price for d in ds)
            total_cost = c_cost + d_cost
            if total_cost > max_budget + 1e-9:
                continue

            base_points = c_points + sum(d.pts for d in ds)
            # Choose boost driver among the 5
            for boost in ds:
                points = base_points + boost.pts
                if best is None or points > best[0] + 1e-9 or (abs(points - best[0]) < 1e-9 and total_cost < best[1] - 1e-9):
                    best = (
                        points,
                        total_cost,
                        tuple(sorted([c1.code, c2.code])),
                        tuple(sorted([d.code for d in ds])),
                        boost.code,
                    )

    if best is None:
        raise RuntimeError("No feasible team found under budget")

    points, cost, cons, drvs, boost = best
    return {
        "max_budget": round(max_budget, 3),
        "constructors": list(cons),
        "drivers": list(drvs),
        "boost": boost,
        "total_cost": round(cost, 3),
        "expected_points": round(points, 3),
        "sim": {
            "id": sim.get("id"),
            "name": sim.get("name"),
            "raceweek": sim.get("raceweek"),
            "season": sim.get("season"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=100.0, help="Maximum budget (e.g., 100)")
    ap.add_argument("--url", default=URL)
    args = ap.parse_args()

    html = fetch(args.url)
    payload = _extract_next_payload(html)
    data = _extract_json_object_from_payload(payload)

    out = compute_optimal(args.budget, data)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
