from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from .. import config
from ..data_sources.f1fantasytools import load_optimal_and_prices
from ..data_sources.official_site import scrape_budget_snapshot
from ..io.artifacts import ensure_state_dirs, read_json, run_artifacts_dir, utcstamp, write_json, safe_filename
from ..logic.diff import compute_diff, normalize_name, as_set
from ..mappings import CONSTRUCTOR_ABBR_TO_FULL, DRIVER_ABBR_TO_FULL, map_optimal_to_ideal
from ..models import TeamSpec
from ..site.browser import launch_persistent_context
from ..site.sync import FantasySync, take_screenshot


def _combine_optimal_with_prices(*, optimal: dict, price_maps: dict) -> dict:
    opt_dr = list(optimal.get("drivers") or [])
    opt_con = list(optimal.get("constructors") or [])
    boost = optimal.get("boost")

    drivers_with_prices = [
        {
            "abbr": abbr,
            "name": DRIVER_ABBR_TO_FULL.get(abbr),
            "price_m": price_maps.get("drivers", {}).get(abbr),
            "boosted": (abbr == boost),
        }
        for abbr in opt_dr
    ]
    constructors_with_prices = [
        {
            "abbr": abbr,
            "name": CONSTRUCTOR_ABBR_TO_FULL.get(abbr),
            "price_m": price_maps.get("constructors", {}).get(abbr),
        }
        for abbr in opt_con
    ]

    total_m = 0.0
    missing: list[str] = []
    for row in drivers_with_prices + constructors_with_prices:
        pm = row.get("price_m")
        if pm is None:
            missing.append(str(row.get("abbr")))
            continue
        total_m += float(pm)

    return {
        "drivers": drivers_with_prices,
        "constructors": constructors_with_prices,
        "total_m": round(total_m, 3),
        "missing_price_abbr": missing,
    }


def sync_team_to_ideal(
    *,
    team_id: int,
    ideal: dict,
    expected_team_name: str | None,
    profile_dir: str,
    headful: bool,
    apply: bool,
    force: bool,
) -> dict:
    """Sync team state to match ideal; writes state/team_state.json and history snapshots.

    Returns a dict with keys:
      {"site_before": ..., "site_after": ..., "diff": ..., "run_dir": ...}

    Notes:
      - When apply=False, site_after is None.
      - When apply=True, site_before is scraped immediately before applying.
    """

    ensure_state_dirs()

    ts = TeamSpec.from_dict(ideal)  # validate

    state_path = config.STATE_DIR / "team_state.json"
    local = read_json(state_path, default=None)
    if local and (not force):
        local_diff = compute_diff(local, ts.to_dict())
        if local_diff.get("noop"):
            print("Local state already matches ideal; exiting without changes.", flush=True)
            return {"site_before": local, "site_after": local, "diff": local_diff, "run_dir": None}

    run_dir = run_artifacts_dir(team_id=team_id)
    write_json(run_dir / "ideal.json", ts.to_dict())

    def _sync_once(*, do_apply: bool) -> tuple[dict, dict]:
        with sync_playwright() as p:
            ctx = launch_persistent_context(playwright=p, profile_dir=profile_dir, headful=headful)
            page = ctx.new_page()
            syncer = FantasySync(page, team_id, expected_team_name, run_dir)
            try:
                state, d = syncer.sync_to_ideal(ts.to_dict(), apply=do_apply)
                return state, d
            except Exception:
                try:
                    take_screenshot(page, run_dir / "error.png")
                except Exception:
                    pass
                raise
            finally:
                ctx.close()

    if not apply:
        before, diff = _sync_once(do_apply=False)
        return {"site_before": before, "site_after": None, "diff": diff, "run_dir": str(run_dir)}

    site_before, _ = _sync_once(do_apply=False)
    site_after, diff = _sync_once(do_apply=True)

    write_json(state_path, site_after)
    hist_name = f"team_state_{safe_filename(site_after['ts_utc'])}_team{team_id}.json"
    shutil.copy2(state_path, config.HISTORY_DIR / hist_name)

    write_json(config.STATE_DIR / "last_applied.json", {"ts_utc": utcstamp(), "ideal": ts.to_dict()})

    return {"site_before": site_before, "site_after": site_after, "diff": diff, "run_dir": str(run_dir)}


def run_end_to_end(
    *,
    team_id: int,
    budget: float | str | None,
    expected_team_name: str | None,
    ideal_out: Path,
    profile_dir: str,
    headful: bool,
    apply: bool,
    force: bool,
    url: str | None,
    boost_driver_override: str | None,
) -> dict[str, Any]:
    """scrape budget -> compute optimal -> map ideal -> (optional) sync -> verify -> write bundle.

    Writes under state/:
      - last_budget.json (if scraped)
      - last_optimal.json
      - last_optimal_with_budget.json
      - last_run.json

    Returns the last_run bundle.
    """

    ensure_state_dirs()
    ts_utc = utcstamp()

    budget_snapshot = None
    cap_m: float
    if budget is None or (isinstance(budget, str) and budget.lower() == "auto"):
        budget_snapshot = scrape_budget_snapshot(team_id=team_id, profile_dir=profile_dir, headful=headful)
        cap_m = float(budget_snapshot.cap_m)
    else:
        cap_m = float(budget)

    optimal, price_maps = load_optimal_and_prices(cap_m, url=url)
    ideal = map_optimal_to_ideal(optimal)

    if boost_driver_override:
        if boost_driver_override not in ideal["drivers"]:
            raise SystemExit("boost-driver-override must be one of the 5 optimal drivers")
        ideal["boost_driver"] = boost_driver_override

    TeamSpec.from_dict(ideal)  # validate

    ideal_out.parent.mkdir(parents=True, exist_ok=True)
    ideal_out.write_text(__import__("json").dumps(ideal, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if budget_snapshot:
        write_json(config.STATE_DIR / "last_budget.json", budget_snapshot.to_dict())

    write_json(config.STATE_DIR / "last_optimal.json", optimal)

    combined = {
        "ts_utc": ts_utc,
        "budget": budget_snapshot.to_dict() if budget_snapshot else {"cap_m": cap_m},
        "optimal": optimal,
        **_combine_optimal_with_prices(optimal=optimal, price_maps=price_maps),
        "remaining_m": (budget_snapshot.remaining_m if budget_snapshot else None),
        "used_m": (budget_snapshot.used_m if budget_snapshot else None),
        "cap_m": (budget_snapshot.cap_m if budget_snapshot else cap_m),
    }
    write_json(config.STATE_DIR / "last_optimal_with_budget.json", combined)

    site_before = None
    site_after = None
    diff = None
    verify = {"ok": False}

    if apply:
        res = sync_team_to_ideal(
            team_id=team_id,
            ideal=ideal,
            expected_team_name=expected_team_name,
            profile_dir=profile_dir,
            headful=headful,
            apply=True,
            force=force,
        )
        site_before = res.get("site_before")
        site_after = res.get("site_after")
        diff = res.get("diff")

        if site_after is not None:
            final_diff = compute_diff(site_after, ideal)
            verify = {"ok": bool(final_diff.get("noop")), "diff_final_vs_ideal": final_diff}

    else:
        res = sync_team_to_ideal(
            team_id=team_id,
            ideal=ideal,
            expected_team_name=expected_team_name,
            profile_dir=profile_dir,
            headful=headful,
            apply=False,
            force=True,
        )
        site_before = res.get("site_before")
        diff = res.get("diff")
        verify = {"ok": bool(diff.get("noop")), "diff_final_vs_ideal": diff}

    bundle = {
        "schema_version": 1,
        "ts_utc": ts_utc,
        "inputs": {
            "team_id": team_id,
            "budget": budget_snapshot.to_dict() if budget_snapshot else {"cap_m": cap_m},
            "price_source": "f1fantasytools",
            "sim": optimal.get("sim"),
        },
        "optimal": combined,
        "ideal": ideal,
        "site_before": site_before,
        "diff": diff,
        "site_after": site_after,
        "verify": verify,
    }

    write_json(config.STATE_DIR / "last_run.json", bundle)
    return bundle
