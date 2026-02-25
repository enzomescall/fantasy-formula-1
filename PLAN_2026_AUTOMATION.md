# F1 Fantasy 2026 — Team Automation Script Plan

## Context / decision
- Manual UI flow proved reliable when we:
  1) Open the correct team (Pascal GP 1) and verify we’re on `/en/my-team/1` and page contains no `Pascal GP 2/3` strings.
  2) Make edits.
  3) **Persist** via **Continue → Confirm Changes** (not “Done” alone).

## Q1) Will a Python script be able to do everything we’ve done?
Yes, with browser automation.
- **Minimum viable**: Playwright (Python) driving Chromium.
- We’ll need to:
  - authenticate (reuse an existing logged-in browser profile/session)
  - interact with the DOM (click remove buttons, click drivers/constructors in the available list)
  - set Boost/2x
  - click Continue, then Confirm Changes
  - validate final state

Caveats:
- Pure `requests`/HTML scraping can’t change the team; it must be **interactive automation** (Playwright/Selenium).
- Login challenges (2FA, email verification) are best handled by reusing a persistent browser profile so the script doesn’t need credentials.

## Q2) Script spec (2026 season, not overly generalized)
### CLI
`python3 scripts/f1_2026_sync_team.py --team-id 1 --ideal ideal_team.json`

Where `ideal_team.json` contains:
```json
{
  "team_name": "Pascal GP 1",
  "drivers": ["Charles Leclerc", "Valtteri Bottas", "Liam Lawson", "Gabriel Bortoleto", "Franco Colapinto"],
  "constructors": ["McLaren", "Ferrari"],
  "boost_driver": "Gabriel Bortoleto"
}
```

### Behavior
- Load current team state from site.
- Compute diff vs ideal.
- Apply only required changes:
  - Remove only drivers/constructors not in ideal.
  - Add missing drivers/constructors.
  - If only boost differs, only change boost.
- Persist with **Continue → Confirm Changes**.
- Re-read final state from site and write to local CSV state store.

## Q3) Local CSV “state of truth” + no-op logic
### Files (recommended: JSON snapshot + historical archive)
- `fantasy-formula-1/state/team_state.json`
  - the latest known site state (source of truth for “no-op” checks)
- `fantasy-formula-1/state/history/`
  - after each successful run, copy `team_state.json` into this folder with a timestamped name, e.g.
    - `team_state_2026-02-25T19-54-00Z_team1.json`
- `fantasy-formula-1/state/last_applied.json`
  - last ideal spec applied (for auditing)

(If we later want easy spreadsheet analysis, we can additionally export a CSV, but JSON + history is simplest/most robust.)

### Check-first logic
1) Read latest row for `team_id=1` from CSV.
2) If it exactly matches ideal spec (set equality for members; strict match for boost; optionally ignore order unless you care):
   - exit 0 with “no changes”.
3) Otherwise run browser automation.
4) After successful Confirm Changes, scrape state again and append new row to CSV.

Recommendation: treat **membership as set**, but also store/display the **UI order**. Order can change on add sequence; we can enforce deterministic order by adding drivers in the desired order.

## Implementation plan (multi-step)

### Phase 0 — Hard requirements
1) Choose automation engine: **Playwright** (preferred).
2) Ensure we can run with a persistent browser profile (so we don’t handle passwords in code).
   - Option A: Playwright persistent context at a path like `fantasy-formula-1/.playwright-profile/`.
   - Option B: export cookies from existing OpenClaw browser profile (less ideal).

### Phase 1 — Project setup
1) Create:
   - `fantasy-formula-1/scripts/f1_2026_sync_team.py`
   - `fantasy-formula-1/state/`
   - `fantasy-formula-1/requirements.txt`
2) Add a “dry-run” mode:
   - `--dry-run` prints diff and intended actions.

### Phase 2 — Read state from website (idempotent)
1) Navigate to `https://fantasy.formula1.com/en/my-team/1`.
2) Validate we’re in the right team:
   - URL contains `/my-team/1`
   - page contains `Pascal GP 1`
   - page does NOT contain `Pascal GP 2` or `Pascal GP 3`
3) Scrape current:
   - selected drivers (names)
   - selected constructors
   - boost driver (look for `2x` badge)

### Phase 3 — Diff + apply changes
1) Drivers:
   - Remove drivers not in ideal (click X on selected driver cards).
   - Add missing drivers by clicking them in the **available driver list** (not the empty-slot add buttons).
2) Constructors:
   - Switch to Constructors tab.
   - Remove constructors not in ideal.
   - Add missing constructors via available list.
3) Boost:
   - If boost driver differs:
     - open boosted driver detail, remove boost if required
     - open target driver detail, click Add Boost

### Phase 4 — Persist + verify
1) Click **Continue**.
2) Wait for Team Changes modal.
3) Screenshot for debugging.
4) Click **Confirm Changes**.
5) Verify we land back on `/en/my-team` and Pascal GP 1 card shows the intended team + boost.

### Phase 5 — Local state store
1) Append scraped final state row to CSV with timestamp.
2) Write last applied spec to `last_applied.json`.

### Phase 6 — Robustness / guardrails
- Retry wrappers for flaky selectors.
- Hard timeouts.
- Always take screenshots on failure: `state/artifacts/<ts>/...png`.
- A “lock” file to prevent concurrent runs.

## Suggestions / improvements
1) **Do not automate login**: rely on a persistent profile/context already logged in.
2) Add a scheduled cron job that:
   - runs before each lock deadline
   - re-computes optimal team (your existing optimizer)
   - generates an `ideal_team.json`
   - runs sync script in `--dry-run` and messages you diff
   - only applies automatically when you reply “approve” (safety).
3) Extend CSV state to track sim ID / raceweek from f1fantasytools so we can reproduce decisions.

## Open questions for you
1) Should the CSV comparison treat driver order as significant?
2) Should the script also manage chips (none for now)?
3) Should we keep Pascal GP 2/3 untouched forever, or auto-delete them later?
