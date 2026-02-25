#!/usr/bin/env python3
"""End-to-end (2026): compute optimal team then sync official site.

Back-compat wrapper.

The implementation has moved into the f1fantasy/ package; this script keeps the old CLI stable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from f1fantasy import config
from f1fantasy.io.artifacts import ensure_state_dirs
from f1fantasy.logic.orchestrator import run_end_to_end


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Override budget cap (millions). If omitted, scrape from official site",
    )
    ap.add_argument("--team-id", type=int, default=1)
    ap.add_argument("--expected-team-name", default=config.DEFAULT_EXPECTED_TEAM_NAME)
    ap.add_argument("--ideal-out", default=str(config.BASE_DIR / "ideal_team.json"))
    ap.add_argument("--url", default=None, help="Override f1fantasytools team-calculator URL")
    ap.add_argument(
        "--boost-driver-override",
        default=None,
        help='Force a boosted driver full name (must be one of the 5 in the optimal team), e.g. "Gabriel Bortoleto"',
    )
    ap.add_argument("--no-apply", action="store_true", help="Compute ideal + show diff only")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--profile-dir", default=config.DEFAULT_PROFILE_DIR)
    args = ap.parse_args()

    ensure_state_dirs()

    bundle = run_end_to_end(
        team_id=args.team_id,
        budget=(args.budget if args.budget is not None else "auto"),
        expected_team_name=args.expected_team_name,
        ideal_out=Path(args.ideal_out),
        profile_dir=args.profile_dir,
        headful=args.headful,
        apply=(not args.no_apply),
        force=False,
        url=args.url,
        boost_driver_override=args.boost_driver_override,
    )

    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
