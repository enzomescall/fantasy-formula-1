#!/usr/bin/env python3
"""End-to-end: compute the best team from f1fantasytools, then sync F1 Fantasy team to match.

Flow:
1) Fetch+compute optimal team under a budget (drivers/constructors/boost) from f1fantasytools.com/team-calculator
2) Map abbreviations (e.g. LEC, MCL) -> site display names (e.g. "Charles Leclerc", "McLaren")
3) Write ideal spec (default: ideal_team.json)
4) Call the Playwright sync script to apply and verify.

Notes
- Requires an authenticated persistent Playwright profile (see f1_2026_sync_team.py).
- This script does not store credentials.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

# --- mappings ---
# Drivers (2026 preseason set as observed). Adjust as needed.
DRIVER_ABBR_TO_FULL = {
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

CONSTRUCTOR_ABBR_TO_FULL = {
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


def _load_optimizer_json(budget: float, url: str | None) -> dict:
    # Import optimizer logic directly (avoids parsing CLI output)
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import f1fantasytools_optimal_team as opt  # type: ignore

    html = opt.fetch(url or opt.URL)
    payload = opt._extract_next_payload(html)
    data = opt._extract_json_object_from_payload(payload)
    return opt.compute_optimal(budget, data)


def _map_team(optimal: dict) -> dict:
    drivers = []
    for abbr in optimal.get("drivers") or []:
        if abbr not in DRIVER_ABBR_TO_FULL:
            raise RuntimeError(f"Unknown driver abbreviation '{abbr}'. Add it to DRIVER_ABBR_TO_FULL.")
        drivers.append(DRIVER_ABBR_TO_FULL[abbr])

    constructors = []
    for abbr in optimal.get("constructors") or []:
        if abbr not in CONSTRUCTOR_ABBR_TO_FULL:
            raise RuntimeError(
                f"Unknown constructor abbreviation '{abbr}'. Add it to CONSTRUCTOR_ABBR_TO_FULL."
            )
        constructors.append(CONSTRUCTOR_ABBR_TO_FULL[abbr])

    boost_abbr = optimal.get("boost")
    boost_driver = None
    if boost_abbr:
        if boost_abbr not in DRIVER_ABBR_TO_FULL:
            raise RuntimeError(f"Unknown boost abbreviation '{boost_abbr}'.")
        boost_driver = DRIVER_ABBR_TO_FULL[boost_abbr]

    return {
        "drivers": drivers,
        "constructors": constructors,
        "boost_driver": boost_driver,
        "optimizer": optimal,
    }


def _parse_money_millions(text: str) -> float | None:
    # Accept patterns like "$14.8M" or "14.8 million"
    if not text:
        return None
    import re

    m = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*M", text, flags=re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*million", text, flags=re.I)
    if m:
        return float(m.group(1))
    return None


def _scrape_site_budget(team_id: int, profile_dir: str, headful: bool) -> dict:
    """Scrape remaining budget and infer total cap from the official F1 Fantasy team page.

    We infer total cap as:
      cap ≈ remaining + sum(selected driver/constructor prices)

    This is robust even if the site changes wording, as long as selected cards show prices.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

    url = f"https://fantasy.formula1.com/en/my-team/{team_id}"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=(not headful),
            viewport={"width": 900, "height": 1600},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector('text=Cost Cap', timeout=60000)
        except PwTimeout:
            # fall back: likely logged out
            raise RuntimeError(f"Could not load team page / budget widget. Are we logged in? URL={page.url}")

        # Remaining budget is shown as "Cost Cap: $X.XM" in the budget widget.
        remaining = None
        try:
            # This matches the <em>$8.8M</em> next to the Cost Cap label.
            txt = page.locator("text=Cost Cap").first.locator("xpath=ancestor::section[1]").inner_text()
            remaining = _parse_money_millions(txt)
        except Exception:
            remaining = None

        if remaining is None:
            # Fallback: parse from HTML around the label
            html = page.content()
            import re

            m = re.search(r"Cost\s*Cap:\s*</span><em>\$\s*([0-9]+(?:\.[0-9]+)?)\s*M", html, flags=re.I)
            if m:
                remaining = float(m.group(1))

        # Selected prices: sum prices visible in selected container ($x.xM)
        selected_sum = page.evaluate(
            r"""() => {
              const cont = document.querySelector('div.si-formation__container') || document.body;
              const txt = cont.innerText || '';
              const matches = [...txt.matchAll(/\$\s*([0-9]+(?:\.[0-9]+)?)\s*M/gi)];
              const nums = matches.map(m => parseFloat(m[1])).filter(n => Number.isFinite(n));
              return nums;
            }"""
        )
        used = float(sum(selected_sum or []))

        if remaining is None:
            raise RuntimeError("Could not parse remaining Cost Cap from page")

        cap = remaining + used
        ctx.close()

    return {
        "remaining_m": round(remaining, 3),
        "used_m": round(used, 3),
        "cap_m": round(cap, 3),
        "source": "fantasy.formula1.com",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=None, help="Override budget cap (millions). If omitted, scrape from official site")
    ap.add_argument("--team-id", type=int, default=1)
    ap.add_argument("--expected-team-name", default="Pascal GP 1")
    ap.add_argument("--ideal-out", default=str(BASE_DIR / "ideal_team.json"))
    ap.add_argument("--url", default=None, help="Override f1fantasytools team-calculator URL")
    ap.add_argument(
        "--boost-driver-override",
        default=None,
        help='Force a boosted driver full name (must be one of the 5 in the optimal team), e.g. "Gabriel Bortoleto"',
    )
    ap.add_argument("--no-apply", action="store_true", help="Compute ideal + show diff only")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--profile-dir", default=str(BASE_DIR / ".playwright-profile"))
    args = ap.parse_args()

    budget = args.budget
    budget_meta = None
    if budget is None:
        budget_meta = _scrape_site_budget(args.team_id, args.profile_dir, args.headful)
        budget = float(budget_meta["cap_m"])

    optimal = _load_optimizer_json(budget, args.url)
    mapped = _map_team(optimal)

    if args.boost_driver_override:
        bd = args.boost_driver_override
        if bd not in mapped["drivers"]:
            raise SystemExit("boost-driver-override must be one of the 5 optimal drivers")
        mapped["boost_driver"] = bd

    ideal = {
        "drivers": mapped["drivers"],
        "constructors": mapped["constructors"],
        "boost_driver": mapped["boost_driver"],
    }

    out_path = Path(args.ideal_out)
    out_path.write_text(json.dumps(ideal, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Save scrape + optimizer outputs (ignored by git if under state/)
    state_dir = BASE_DIR / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    if budget_meta:
        (state_dir / "last_budget.json").write_text(
            json.dumps(budget_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    (state_dir / "last_optimal.json").write_text(
        json.dumps(mapped["optimizer"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    cmd = [
        sys.executable,
        str(BASE_DIR / "scripts" / "f1_2026_sync_team.py"),
        "--team-id",
        str(args.team_id),
        "--ideal",
        str(out_path),
        "--expected-team-name",
        args.expected_team_name,
        "--profile-dir",
        args.profile_dir,
    ]
    if args.no_apply:
        cmd.append("--no-apply")
    if args.headful:
        cmd.append("--headful")

    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
