# Fantasy Formula 1 (F1 Fantasy) — Local Skill Notes

## Goal
- Use the OpenClaw headless browser (profile: `openclaw`) to log into **fantasy.formula1.com** using:
  - account: **pascal.ai.inbox@gmail.com**
- Create and manage an F1 Fantasy team.

## Current status
- Browser profile `openclaw` is **not logged in** (menu shows **SIGN IN / REGISTER**).

## Working log
- Session log lives at: `fantasy-formula-1/logs/f1_2026_02_26.md`

## Operating notes
- Login may require interactive steps (Google sign-in + possible 2FA). If 2FA is enabled, Enzo may need to provide the one-time code.
- After login, verify by checking the site menu for an account/profile indicator (no longer shows SIGN IN).

## Next actions checklist
1) Navigate to https://fantasy.formula1.com/
2) Click **SIGN IN**
3) Complete sign-in flow for pascal.ai.inbox@gmail.com
4) Create a team (name, drivers, constructors within budget)
5) Record steps + chosen team composition in the log

## Automation (2026)
We have a Playwright-based team sync script that can apply diffs (drivers/constructors/boost) and persist via **Continue → Confirm Changes**.

### Files
- Ideal spec: `fantasy-formula-1/ideal_team.json`
- Script: `fantasy-formula-1/scripts/f1_2026_sync_team.py`
- Latest state: `fantasy-formula-1/state/team_state.json`
- History snapshots: `fantasy-formula-1/state/history/`
- Debug artifacts (screenshots): `fantasy-formula-1/state/artifacts/`

### Install (once)
Important: Playwright requires modern Python. Use **python3.12** on this host.
- `python3.12 -m pip install -r fantasy-formula-1/requirements.txt`
- `python3.12 -m playwright install chromium`

### First-time login bootstrap (recommended)
Run headful once, log in manually in the opened Chromium, then close it:
- `python3.12 fantasy-formula-1/scripts/f1_2026_sync_team.py --team-id 1 --ideal fantasy-formula-1/ideal_team.json --headful --no-apply`

### Apply sync
- `python3.12 fantasy-formula-1/scripts/f1_2026_sync_team.py --team-id 1 --ideal fantasy-formula-1/ideal_team.json`

### Notes
- The script avoids handling passwords by relying on a persistent Playwright profile at `fantasy-formula-1/.playwright-profile/`.
- The script will no-op if `state/team_state.json` already matches the ideal spec (membership + boost).
