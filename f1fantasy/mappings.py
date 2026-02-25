from __future__ import annotations

# Drivers (2026 preseason set as observed). Adjust as needed.
DRIVER_ABBR_TO_FULL: dict[str, str] = {
    "VER": "Max Verstappen",
    "RUS": "George Russell",
    "NOR": "Lando Norris",
    "PIA": "Oscar Piastri",
    "ANT": "Kimi Antonelli",
    "LEC": "Charles Leclerc",
    "HAM": "Lewis Hamilton",
    "HAD": "Isack Hadjar",
    "GAS": "Pierre Gasly",
    "SAI": "Carlos Sainz",
    "ALB": "Alexander Albon",
    "ALO": "Fernando Alonso",
    "STR": "Lance Stroll",
    "BEA": "Oliver Bearman",
    "OCO": "Esteban Ocon",
    "HUL": "Nico Hulkenberg",
    "LAW": "Liam Lawson",
    "BOR": "Gabriel Bortoleto",
    "LIN": "Arvid Lindblad",
    "COL": "Franco Colapinto",
    "PER": "Sergio Perez",
    "BOT": "Valtteri Bottas",
}

CONSTRUCTOR_ABBR_TO_FULL: dict[str, str] = {
    "MCL": "McLaren",
    "FER": "Ferrari",
    "MER": "Mercedes",
    "RBR": "Red Bull Racing",
    "ALP": "Alpine",
    "WIL": "Williams",
    "AST": "Aston Martin",
    "HAA": "Haas F1 Team",
    "AUD": "Audi",
    "RB": "Racing Bulls",
    "CAD": "Cadillac",
}


def map_optimal_to_ideal(optimal: dict) -> dict:
    drivers: list[str] = []
    for abbr in optimal.get("drivers") or []:
        if abbr not in DRIVER_ABBR_TO_FULL:
            raise RuntimeError(f"Unknown driver abbreviation '{abbr}'. Add it to DRIVER_ABBR_TO_FULL.")
        drivers.append(DRIVER_ABBR_TO_FULL[abbr])

    constructors: list[str] = []
    for abbr in optimal.get("constructors") or []:
        if abbr not in CONSTRUCTOR_ABBR_TO_FULL:
            raise RuntimeError(f"Unknown constructor abbreviation '{abbr}'. Add it to CONSTRUCTOR_ABBR_TO_FULL.")
        constructors.append(CONSTRUCTOR_ABBR_TO_FULL[abbr])

    boost_abbr = optimal.get("boost")
    boost_driver = None
    if boost_abbr:
        if boost_abbr not in DRIVER_ABBR_TO_FULL:
            raise RuntimeError(f"Unknown boost abbreviation '{boost_abbr}'.")
        boost_driver = DRIVER_ABBR_TO_FULL[boost_abbr]

    return {"drivers": drivers, "constructors": constructors, "boost_driver": boost_driver}
