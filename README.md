# fantasy-formula-1

Automation tools for the official F1 Fantasy site using Playwright plus f1fantasytools.com expected-points data.

## What this repo does
- Scrapes budget/current-team state from fantasy.formula1.com
- Computes an optimal team from f1fantasytools.com for the available budget
- Maps that result to `ideal_team.json`
- Reports the diff, transfer count, transfer policy, deadline policy, and chip-strategy watch notes
- Computes chip math for Limitless (`999.0m` budget) and x3 Boost (CSP with separate 3x and 2x drivers)
- Charges transfers against the saved race-week baseline (the previous race's locked team), not against provisional midweek edits
- Optionally applies minimal UI changes via Playwright when `--apply` is explicitly requested
- Persists changes via the required **Continue → Confirm Changes** flow
- Saves run artifacts/screenshots locally under `state/` (ignored by git)

## Requirements
- Python 3.12+
- Playwright Chromium

```bash
python3.12 -m pip install -r requirements.txt
python3.12 -m playwright install chromium
```

## Authentication and secrets
This repo intentionally does not store credentials.

Supported auth sources:
- A local `.env` file with `F1_EMAIL` and `F1_PASSWORD` (ignored by git)
- An existing persistent Playwright profile such as `.playwright-profile/` (ignored by git)
- Manual login during a headful Playwright run

Do not print, commit, or paste passwords into scripts, docs, scheduler messages, or logs.

## Main CLI
Use `scripts/f1_fantasy.py` for all current workflows.

### Report-only/default end-to-end run
`run` without `--apply` is report-only. It computes the recommendation, scrapes current site state, evaluates transfer/deadline policy, writes `state/last_run.json`, and does not mutate the official site.

```bash
python3.12 scripts/f1_fantasy.py run \
  --team-id 1 \
  --expected-team-name 'Pascal GP 1' \
  --profile-dir .playwright-profile
```

Review:
- `state/last_run.json`
- `policy_decision.apply`
- `policy_decision.reason`
- `diff.transfers_required`
- `chip_strategy.notes`
- `chip_strategy.chip_math.limitless.uplift_vs_standard`
- `chip_strategy.chip_math.x3_boost.uplift_vs_standard`

### Apply end-to-end changes
Apply is opt-in and guarded by:
- A local `state/apply.lock` so overlapping Playwright mutations cannot run concurrently
- Transfer policy (blocks paid transfers by default)
- Fantasy deadline policy (blocks apply at/after lock by default)

```bash
python3.12 scripts/f1_fantasy.py run \
  --team-id 1 \
  --expected-team-name 'Pascal GP 1' \
  --profile-dir .playwright-profile \
  --apply
```

Emergency override for deadline only:

```bash
python3.12 scripts/f1_fantasy.py run ... --apply --ignore-deadline
```

Use `--ignore-deadline` only for manual emergency verification; it does not bypass the transfer policy.

### Sync an existing ideal_team.json
Report-only sync:

```bash
python3.12 scripts/f1_fantasy.py sync \
  --team-id 1 \
  --ideal ideal_team.json \
  --expected-team-name 'Pascal GP 1' \
  --profile-dir .playwright-profile \
  --no-apply
```

Apply sync:

```bash
python3.12 scripts/f1_fantasy.py sync \
  --team-id 1 \
  --ideal ideal_team.json \
  --expected-team-name 'Pascal GP 1' \
  --profile-dir .playwright-profile
```

### Other useful commands
Scrape budget:

```bash
python3.12 scripts/f1_fantasy.py budget --team-id 1 --profile-dir .playwright-profile --write-state
```

Compute optimal team for a known budget:

```bash
python3.12 scripts/f1_fantasy.py optimal --budget 100.0 --ideal-out ideal_team.json
```

Compute optimal team using scraped budget:

```bash
python3.12 scripts/f1_fantasy.py optimal --budget auto --team-id 1 --profile-dir .playwright-profile --ideal-out ideal_team.json
```

### Transfer baseline semantics
F1 Fantasy charges free transfers against the previous race weekend's locked team, not against the currently edited provisional team. The automation now creates one immutable baseline per team/race under `state/transfer_baselines/` the first time it sees a race week. Later FP1/FP2/FP3/SQ reruns compare the proposed ideal team to that baseline for transfer policy, while still applying only the minimal UI diff from the current site state.

This means:
- Initial 2 swaps can be applied early.
- Later “half swaps” are allowed when the final team is still only 2 or 3 changes from the baseline.
- A tempting one-click edit from the current provisional team is blocked if it would make the final team exceed the free-transfer count relative to the baseline.

## Repo hygiene
The following local-only paths are ignored:
- `.env` (credentials)
- `.brv/` (local browser/session artifacts)
- `.playwright-profile/` and `.playwright-profile-headfulua/` (cookies/session)
- `state/` (artifacts, screenshots, local snapshots, lock file)
