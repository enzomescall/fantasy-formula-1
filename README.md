# fantasy-formula-1

Automation tools for the official F1 Fantasy site (2026 team builder).

## What this repo does
- Scrapes current team state (drivers, constructors, boost)
- Computes diffs vs an `ideal_team.json`
- Applies minimal UI changes via Playwright
- Persists changes via the required **Continue → Confirm Changes** flow
- Saves run artifacts/screenshots locally (ignored by git)

## Requirements
- Python 3.12+
- Playwright Chromium

```bash
python3.12 -m pip install -r requirements.txt
python3.12 -m playwright install chromium
```

## Usage
Create/edit `ideal_team.json`:
```json
{
  "drivers": ["...", "...", "...", "...", "..."],
  "constructors": ["McLaren", "Ferrari"],
  "boost_driver": "Gabriel Bortoleto"
}
```

Run a diff-only check:
```bash
python3.12 scripts/f1_2026_sync_team.py --team-id 1 --ideal ideal_team.json --no-apply
```

Apply changes:
```bash
python3.12 scripts/f1_2026_sync_team.py --team-id 1 --ideal ideal_team.json
```

## Security notes
- This repo intentionally **does not** store credentials.
- Authentication is expected to come from a **local persistent Playwright profile** (ignored by git).

## Repo hygiene
The following are ignored:
- `.playwright-profile/` (cookies/session)
- `state/` (artifacts, screenshots, local snapshots)
