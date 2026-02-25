#!/usr/bin/env python3
"""F1 Fantasy automation CLI.

Subcommands:
  - budget: scrape budget snapshot from official site
  - optimal: compute optimal team from f1fantasytools under a budget
  - sync: sync official team to an ideal TeamSpec JSON
  - run: end-to-end (budget -> optimal -> sync -> verify -> state/last_run.json)

This is the new entrypoint replacing the older single-purpose scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path when invoked as a script.
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from f1fantasy import config
from f1fantasy.data_sources.f1fantasytools import load_optimal_and_prices
from f1fantasy.data_sources.official_site import scrape_budget_snapshot
from f1fantasy.io.artifacts import ensure_state_dirs, write_json, read_json
from f1fantasy.logic.orchestrator import run_end_to_end, sync_team_to_ideal
from f1fantasy.mappings import map_optimal_to_ideal
from f1fantasy.models import TeamSpec


def cmd_budget(args: argparse.Namespace) -> int:
    ensure_state_dirs()
    snap = scrape_budget_snapshot(team_id=args.team_id, profile_dir=args.profile_dir, headful=args.headful)
    out = snap.to_dict()
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.write_state:
        write_json(config.STATE_DIR / "last_budget.json", out)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_optimal(args: argparse.Namespace) -> int:
    ensure_state_dirs()

    budget = args.budget
    budget_snapshot = None
    if isinstance(budget, str) and budget.lower() == "auto":
        budget_snapshot = scrape_budget_snapshot(team_id=args.team_id, profile_dir=args.profile_dir, headful=args.headful)
        budget = float(budget_snapshot.cap_m)

    optimal, price_maps = load_optimal_and_prices(float(budget), url=args.url)
    ideal = map_optimal_to_ideal(optimal)

    if args.boost_driver_override:
        if args.boost_driver_override not in ideal["drivers"]:
            raise SystemExit("boost-driver-override must be one of the 5 optimal drivers")
        ideal["boost_driver"] = args.boost_driver_override

    TeamSpec.from_dict(ideal)  # validate

    if args.ideal_out:
        Path(args.ideal_out).write_text(json.dumps(ideal, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if budget_snapshot is not None:
        write_json(config.STATE_DIR / "last_budget.json", budget_snapshot.to_dict())

    write_json(config.STATE_DIR / "last_optimal.json", optimal)

    out = {
        "budget": budget_snapshot.to_dict() if budget_snapshot else {"cap_m": float(budget)},
        "optimal": optimal,
        "ideal": ideal,
        "prices": price_maps,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    ensure_state_dirs()
    ideal = read_json(Path(args.ideal))
    if not ideal:
        raise SystemExit(f"Ideal spec not found/empty: {args.ideal}")

    TeamSpec.from_dict(ideal)  # validate

    res = sync_team_to_ideal(
        team_id=args.team_id,
        ideal=ideal,
        expected_team_name=args.expected_team_name,
        profile_dir=args.profile_dir,
        headful=args.headful,
        apply=(not args.no_apply),
        force=args.force,
    )

    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ensure_state_dirs()

    bundle = run_end_to_end(
        team_id=args.team_id,
        budget=args.budget,
        expected_team_name=args.expected_team_name,
        ideal_out=Path(args.ideal_out),
        profile_dir=args.profile_dir,
        headful=args.headful,
        apply=args.apply,
        force=args.force,
        url=args.url,
        boost_driver_override=args.boost_driver_override,
    )

    if args.out:
        Path(args.out).write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="f1_fantasy")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_budget = sub.add_parser("budget", help="Scrape budget snapshot from official site")
    p_budget.add_argument("--team-id", type=int, default=1)
    p_budget.add_argument("--profile-dir", default=config.DEFAULT_PROFILE_DIR)
    p_budget.add_argument("--headful", action="store_true")
    p_budget.add_argument("--out", default=None, help="Optional output path")
    p_budget.add_argument("--write-state", action="store_true", help="Also write state/last_budget.json")
    p_budget.set_defaults(func=cmd_budget)

    p_opt = sub.add_parser("optimal", help="Compute optimal team using f1fantasytools")
    p_opt.add_argument("--team-id", type=int, default=1, help="Used only when --budget auto")
    p_opt.add_argument("--budget", default="auto", help='Budget cap in millions, or "auto" to scrape')
    p_opt.add_argument("--profile-dir", default=config.DEFAULT_PROFILE_DIR)
    p_opt.add_argument("--headful", action="store_true")
    p_opt.add_argument("--url", default=None, help="Override f1fantasytools team-calculator URL")
    p_opt.add_argument("--ideal-out", default=str(config.BASE_DIR / "ideal_team.json"))
    p_opt.add_argument("--boost-driver-override", default=None)
    # Convenience flag (matches older workflow). Currently state JSONs are written by default.
    p_opt.add_argument("--write-state", action="store_true", help="(No-op) Kept for compatibility; state files are written by default")
    p_opt.set_defaults(func=cmd_optimal)

    p_sync = sub.add_parser("sync", help="Sync official team to an ideal JSON spec")
    p_sync.add_argument("--team-id", type=int, default=1)
    p_sync.add_argument("--ideal", required=True)
    p_sync.add_argument("--expected-team-name", default=config.DEFAULT_EXPECTED_TEAM_NAME)
    p_sync.add_argument("--profile-dir", default=config.DEFAULT_PROFILE_DIR)
    p_sync.add_argument("--headful", action="store_true")
    p_sync.add_argument("--no-apply", action="store_true")
    p_sync.add_argument("--force", action="store_true")
    p_sync.set_defaults(func=cmd_sync)

    p_run = sub.add_parser("run", help="End-to-end run (budget->optimal->sync->verify)")
    p_run.add_argument("--team-id", type=int, default=1)
    p_run.add_argument("--budget", default="auto")
    p_run.add_argument("--expected-team-name", default=config.DEFAULT_EXPECTED_TEAM_NAME)
    p_run.add_argument("--ideal-out", default=str(config.BASE_DIR / "ideal_team.json"))
    p_run.add_argument("--profile-dir", default=config.DEFAULT_PROFILE_DIR)
    p_run.add_argument("--headful", action="store_true")
    p_run.add_argument("--apply", action="store_true", help="Actually apply changes on the official site")
    p_run.add_argument("--force", action="store_true")
    p_run.add_argument("--url", default=None)
    p_run.add_argument("--boost-driver-override", default=None)
    p_run.add_argument("--out", default=None, help="Optional output path for last_run bundle")
    p_run.set_defaults(func=cmd_run)

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
