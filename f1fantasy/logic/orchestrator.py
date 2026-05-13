from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from .. import config
from ..data_sources.f1fantasytools import compute_optimal, load_embedded_data, load_optimal_and_prices, price_maps_from_data
from ..data_sources.official_site import scrape_budget_snapshot, scrape_transfer_status
from ..io.artifacts import ensure_state_dirs, read_json, run_artifacts_dir, utcstamp, write_json, safe_filename
from ..logic.deadline import current_deadline_decision
from ..logic.diff import compute_diff, normalize_name, as_set
from ..logic.transfer_policy import (
    compute_baseline_transfer_policy,
    current_race_context,
    get_or_create_transfer_baseline,
)
from ..logic.chip_strategy import build_chip_strategy_report
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
    ignore_deadline: bool = False,
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

    data = load_embedded_data(url)
    price_maps = price_maps_from_data(data)
    optimal = compute_optimal(cap_m, data, scoring_mode="standard")
    limitless_optimal = compute_optimal(999.0, data, scoring_mode="standard")
    x3_optimal = compute_optimal(cap_m, data, scoring_mode="x3")
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
    write_json(config.STATE_DIR / "last_limitless_optimal.json", limitless_optimal)
    write_json(config.STATE_DIR / "last_x3_optimal.json", x3_optimal)

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

    # Always fetch the current site state + diff first so we can make a transfer policy decision.
    pre = sync_team_to_ideal(
        team_id=team_id,
        ideal=ideal,
        expected_team_name=expected_team_name,
        profile_dir=profile_dir,
        headful=headful,
        apply=False,
        force=True,
    )
    site_before = pre.get("site_before")
    diff = pre.get("diff")

    transfer_status = scrape_transfer_status(team_id=team_id, profile_dir=profile_dir, headful=headful)

    race_context: dict[str, Any] | None = None
    baseline_error: str | None = None
    try:
        race_context = current_race_context()
    except Exception as exc:
        baseline_error = f"Could not identify current race for transfer baseline: {exc}"

    transfer_policy = None
    if site_before is not None:
        baseline = get_or_create_transfer_baseline(
            team_id=team_id,
            race_context=race_context,
            current_state=site_before,
        )
        transfer_policy = compute_baseline_transfer_policy(
            baseline=baseline,
            current_state=site_before,
            ideal=ideal,
            free_transfers=int(transfer_status.free_transfers),
        )

    # UI work still diffs current site -> ideal, but transfer policy must diff
    # previous-race baseline -> ideal. This allows repeated midweek revisions
    # without accumulating provisional swap costs, and blocks accidental drift to
    # 3+ baseline changes even if the latest edit is only one UI swap away.
    transfers_required = int(
        (transfer_policy or {}).get("baseline_transfers_required")
        if transfer_policy is not None
        else (diff.get("transfers_required") or 0)
    )
    free_transfers = int(transfer_status.free_transfers)
    apply_allowed = bool((transfer_policy or {}).get("apply", transfers_required <= free_transfers))
    if baseline_error:
        apply_allowed = False
    deadline_policy: dict[str, Any] = {"apply": True, "reason": "Not checked (apply not requested)"}
    if apply:
        if ignore_deadline:
            deadline_policy = {"apply": True, "reason": "Deadline guard bypassed by --ignore-deadline"}
        else:
            try:
                deadline_decision, deadline_context = current_deadline_decision()
                deadline_policy = {
                    "apply": bool(deadline_decision.allowed),
                    "reason": deadline_decision.reason,
                    "decision": deadline_decision.to_dict(),
                    "context": deadline_context,
                }
                apply_allowed = apply_allowed and bool(deadline_decision.allowed)
            except Exception as exc:
                deadline_policy = {
                    "apply": False,
                    "reason": f"Deadline guard could not verify current lock status; blocking apply by default: {exc}",
                }
                apply_allowed = False
    transfer_reason = (transfer_policy or {}).get("reason")
    if baseline_error:
        transfer_reason = baseline_error
    policy_decision = {
        "apply": bool(apply_allowed),
        "reason": (
            f"{transfer_reason}; before fantasy deadline"
            if apply_allowed and transfer_reason
            else (
                transfer_reason
                if transfer_reason and not apply_allowed
                else (
                    f"Would require {transfers_required} transfers; only {free_transfers} free transfers available"
                    if transfers_required > free_transfers
                    else deadline_policy.get("reason", "Apply blocked by policy")
                )
            )
        ),
        "transfers_required": transfers_required,
        "free_transfers": free_transfers,
        "deadline": deadline_policy,
        "transfer_policy": transfer_policy,
        "baseline_error": baseline_error,
    }

    chip_strategy = build_chip_strategy_report(
        race_context=race_context,
        standard_optimal=optimal,
        limitless_optimal=limitless_optimal,
        x3_optimal=x3_optimal,
        transfer_policy=transfer_policy,
        transfer_status=transfer_status.to_dict(),
        site_before=site_before,
        ideal=ideal,
    )

    site_after = None
    verify = {"ok": False}

    if apply and apply_allowed:
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
        # Not applying (either --apply was not requested or policy blocked it).
        verify = {"ok": bool(diff.get("noop")), "diff_final_vs_ideal": diff}

    bundle = {
        "schema_version": 1,
        "ts_utc": ts_utc,
        "inputs": {
            "team_id": team_id,
            "budget": budget_snapshot.to_dict() if budget_snapshot else {"cap_m": cap_m},
            "price_source": "f1fantasytools",
            "sim": optimal.get("sim"),
            "apply_requested": bool(apply),
            "race_context": race_context,
        },
        "optimal": combined,
        "chip_variants": {
            "limitless": limitless_optimal,
            "x3_boost": x3_optimal,
        },
        "chip_strategy": chip_strategy,
        "ideal": ideal,
        "site_before": site_before,
        "transfer_status": transfer_status.to_dict(),
        "diff": diff,
        "policy_decision": policy_decision,
        "site_after": site_after,
        "verify": verify,
    }

    write_json(config.STATE_DIR / "last_run.json", bundle)
    return bundle
