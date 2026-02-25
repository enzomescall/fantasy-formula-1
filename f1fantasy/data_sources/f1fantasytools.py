from __future__ import annotations

import itertools
import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Tuple

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


def extract_next_payload(html: str) -> str:
    """Extract and decode the largest self.__next_f.push([1,"..."]) string."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, flags=re.DOTALL)
    if not chunks:
        raise RuntimeError("Could not find self.__next_f.push payload in HTML")
    raw = max(chunks, key=len)
    try:
        decoded = raw.encode("utf-8").decode("unicode_escape")
    except Exception as e:
        raise RuntimeError("Failed to decode __next_f payload: %s" % (e,))
    return decoded


def extract_json_object_from_payload(payload: str) -> dict:
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


@dataclass(frozen=True)
class Pick:
    code: str
    price: float
    pts: float


def compute_optimal(max_budget: float, data: dict) -> dict:
    drivers_raw = data.get("drivers") or []
    constructors_raw = data.get("constructors") or []
    analyst_sims = data.get("analystSims") or []
    if not analyst_sims:
        raise RuntimeError("No analystSims found in embedded data")

    sim = analyst_sims[0]
    drv_pts: Dict[str, float] = (sim.get("drivers") or {}).get("pts") or {}
    con_pts: Dict[str, float] = (sim.get("constructors") or {}).get("pts") or {}

    drv_meta: Dict[str, Tuple[str, float]] = {}
    for d in drivers_raw:
        if d.get("type") == "driver" and d.get("id") and d.get("abbreviation"):
            drv_meta[str(d["id"])] = (str(d["abbreviation"]), float(d["price"]))

    con_price: Dict[str, float] = {}
    for c in constructors_raw:
        if c.get("type") == "constructor" and c.get("abbreviation"):
            con_price[str(c["abbreviation"])] = float(c["price"])

    drivers: List[Pick] = []
    for drv_id, pts in drv_pts.items():
        if drv_id in drv_meta:
            abbr, price = drv_meta[drv_id]
            drivers.append(Pick(code=abbr, price=price, pts=float(pts)))

    constructors: List[Pick] = [
        Pick(code=k, price=con_price[k], pts=float(v)) for k, v in con_pts.items() if k in con_price
    ]

    if not drivers or not constructors:
        raise RuntimeError("Could not build drivers/constructors pick lists")

    best: Tuple[float, float, Tuple[str, str], Tuple[str, ...], str] | None = None

    for c1, c2 in itertools.combinations(constructors, 2):
        c_cost = c1.price + c2.price
        c_points = c1.pts + c2.pts
        if c_cost >= max_budget:
            continue

        for ds in itertools.combinations(drivers, 5):
            d_cost = sum(d.price for d in ds)
            total_cost = c_cost + d_cost
            if total_cost > max_budget + 1e-9:
                continue

            base_points = c_points + sum(d.pts for d in ds)
            for boost in ds:
                points = base_points + boost.pts
                if best is None or points > best[0] + 1e-9 or (
                    abs(points - best[0]) < 1e-9 and total_cost < best[1] - 1e-9
                ):
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


def load_optimal_and_prices(max_budget: float, url: str | None = None) -> tuple[dict, dict]:
    """Return (optimal, price_maps).

    price_maps:
      {
        "drivers": {"LEC": 22.8, ...},
        "constructors": {"MCL": 28.9, ...}
      }
    """
    html = fetch(url or URL)
    payload = extract_next_payload(html)
    data = extract_json_object_from_payload(payload)

    drv_prices: dict[str, float] = {}
    for d in (data.get("drivers") or []):
        if d.get("type") == "driver" and d.get("abbreviation") and d.get("price") is not None:
            drv_prices[str(d["abbreviation"])] = float(d["price"])

    con_prices: dict[str, float] = {}
    for c in (data.get("constructors") or []):
        if c.get("type") == "constructor" and c.get("abbreviation") and c.get("price") is not None:
            con_prices[str(c["abbreviation"])] = float(c["price"])

    optimal = compute_optimal(max_budget, data)
    return optimal, {"drivers": drv_prices, "constructors": con_prices}
