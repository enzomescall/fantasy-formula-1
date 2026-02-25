#!/usr/bin/env python3
"""F1 Fantasy 2026: sync a team to an ideal spec.

Back-compat wrapper.

The implementation has moved into the f1fantasy/ package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from f1fantasy import config
from f1fantasy.io.artifacts import ensure_state_dirs, read_json
from f1fantasy.logic.orchestrator import sync_team_to_ideal
from f1fantasy.models import TeamSpec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--team-id", type=int, default=1)
    ap.add_argument("--ideal", required=True, help="Path to ideal_team.json")
    ap.add_argument("--profile-dir", default=config.DEFAULT_PROFILE_DIR, help="Persistent Playwright profile dir")
    ap.add_argument("--expected-team-name", default=config.DEFAULT_EXPECTED_TEAM_NAME)
    ap.add_argument("--headful", action="store_true", help="Run with a visible browser window")
    ap.add_argument("--no-apply", action="store_true", help="Do not apply changes (just compute diff)")
    ap.add_argument("--force", action="store_true", help="Apply even if local state matches ideal")
    args = ap.parse_args()

    ensure_state_dirs()

    ideal_path = Path(args.ideal)
    ideal = read_json(ideal_path)
    if not ideal:
        raise SystemExit(f"Ideal spec not found/empty: {ideal_path}")

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

    # Preserve scripts' "human" output (prints something JSON-ish)
    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
