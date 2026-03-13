#!/usr/bin/env python3.12
"""
F1 Fantasy Meta-Scheduler

Run on Wednesday of each race week. It:
1. Fetches the F1 calendar to find the next race and its sessions
2. Determines the Fantasy team lock deadline (before Qualifying)
3. Identifies the session right before the deadline
4. Calculates the optimal time to run the optimizer (midpoint between that session's end and the deadline)
5. Schedules a one-shot cron job at that optimal time
6. Schedules a follow-up job for ~Wednesday after the race (next race week)

Usage:
    python3.12 scripts/f1_meta_scheduler.py [--dry-run] [--schedule-followup-days N]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

F1_CALENDAR_API = "https://f1calendar.com/api/calendar"
OPTIMIZER_SCRIPT = Path(__file__).parent / "f1_fantasy.py"
REPO_DIR = Path(__file__).parent.parent

# Slack time before deadline (minutes) - how early we want to finish applying
SLACK_BEFORE_DEADLINE_MIN = 30

# How many days after the race to schedule the next meta-scheduler run
POST_RACE_FOLLOWUP_DAYS = 3


def fetch_calendar() -> list[dict]:
    """Fetch the F1 calendar from f1calendar.com."""
    req = urllib.request.Request(
        F1_CALENDAR_API,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    return data["races"]


def find_next_race(now: datetime, races: list[dict]) -> dict | None:
    """Find the next upcoming race (first race whose Grand Prix is after `now`)."""
    for race in races:
        gp_time = datetime.fromisoformat(race["sessions"]["Grand Prix"].replace("Z", "+00:00"))
        if gp_time > now:
            return race
    return None


def is_sprint_weekend(race: dict) -> bool:
    """Check if this is a sprint weekend."""
    return "Sprint" in race["sessions"] or "Sprint Qualifying" in race["sessions"]


def get_deadline_and_pre_session(race: dict) -> tuple[datetime, str, datetime]:
    """
    Determine the Fantasy team lock deadline and the session just before it.

    F1 Fantasy deadline = before the FIRST session that affects the race grid:
    - Sprint weekends: deadline before Sprint Race (Saturday)
    - Normal weekends: deadline before Qualifying (Saturday)

    The "pre-session" is the last session before the deadline, which is where
    we want the model to have updated data from.

    Returns: (deadline_utc, pre_session_name, pre_session_end_utc)
    """
    sessions = race["sessions"]

    if is_sprint_weekend(race):
        # Sprint weekend: deadline before Sprint Race
        # Pre-session is Sprint Qualifying (the session that sets the Sprint grid)
        sprint_start = datetime.fromisoformat(sessions["Sprint"].replace("Z", "+00:00"))
        sq_start = datetime.fromisoformat(sessions["Sprint Qualifying"].replace("Z", "+00:00"))
        # Sprint Qualifying typically ~1 hour
        sq_end = sq_start + timedelta(hours=1)
        # Deadline is ~30 min before Sprint Race
        deadline = sprint_start - timedelta(minutes=30)
        return deadline, "Sprint Qualifying", sq_end
    else:
        # Normal weekend: deadline before Qualifying
        # Pre-session is FP3
        qualifying_start = datetime.fromisoformat(sessions["Qualifying"].replace("Z", "+00:00"))
        fp3_start = datetime.fromisoformat(sessions["Free Practice 3"].replace("Z", "+00:00"))
        # FP sessions are typically 1 hour
        fp3_end = fp3_start + timedelta(hours=1)
        # Deadline is ~30 min before Qualifying
        deadline = qualifying_start - timedelta(minutes=30)
        return deadline, "FP3", fp3_end


def compute_optimal_time(pre_session_end: datetime, deadline: datetime) -> datetime:
    """
    Compute the optimal time to run the optimizer.
    Midpoint between pre-session end and deadline, shifted slightly toward the session end
    to give the f1fantasytools model time to update.
    """
    gap = deadline - pre_session_end
    # Optimal: 40% of the way from pre-session end toward deadline
    # (gives model ~40% of the gap to update, and 60% of the gap as slack)
    optimal = pre_session_end + gap * 0.4
    return optimal


def format_iso(dt: datetime) -> str:
    """Format datetime as ISO string for OpenClaw cron."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def schedule_cron_job(name: str, at_iso: str, message: str, delete_after: bool = True) -> str:
    """Schedule a one-shot cron job via openclaw CLI."""
    cmd = [
        "openclaw", "cron", "add",
        "--name", name,
        "--at", at_iso,
        "--message", message,
        "--session", "isolated",
        "--timeout-seconds", "300",
        "--json",
    ]
    if delete_after:
        cmd.append("--delete-after-run")

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_DIR))
    if result.returncode != 0:
        raise RuntimeError(f"Failed to schedule cron job: {result.stderr}")

    output = json.loads(result.stdout)
    return output.get("id", "unknown")


def main() -> int:
    parser = argparse.ArgumentParser(description="F1 Fantasy Meta-Scheduler")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without scheduling")
    parser.add_argument("--schedule-followup-days", type=int, default=POST_RACE_FOLLOWUP_DAYS,
                        help="Days after race to schedule next meta-scheduler run")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    print(f"Current UTC time: {now.isoformat()}")
    print()

    # Fetch calendar
    print("Fetching F1 calendar...")
    races = fetch_calendar()
    print(f"Found {len(races)} races in calendar")
    print()

    # Find next race
    next_race = find_next_race(now, races)
    if not next_race:
        print("No upcoming race found!")
        return 1

    print(f"Next race: Round {next_race['round']} - {next_race['name']} ({next_race['location']})")
    print()

    # Print sessions
    print("Sessions:")
    for name, time_str in next_race["sessions"].items():
        t = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        print(f"  {name}: {t.strftime('%a %b %d, %H:%M UTC')}")
    print()

    # Determine deadline and pre-session
    deadline, pre_session_name, pre_session_end = get_deadline_and_pre_session(next_race)
    print(f"Pre-deadline session: {pre_session_name}")
    print(f"  Ends at: {pre_session_end.strftime('%a %b %d, %H:%M UTC')}")
    print(f"Fantasy deadline: {deadline.strftime('%a %b %d, %H:%M UTC')}")
    print()

    # Compute optimal time
    gap = deadline - pre_session_end
    optimal = compute_optimal_time(pre_session_end, deadline)
    print(f"Gap between {pre_session_name} end and deadline: {gap.total_seconds() / 3600:.1f} hours")
    print(f"Optimal optimizer run time: {optimal.strftime('%a %b %d, %H:%M UTC')}")
    print(f"  ({(optimal - pre_session_end).total_seconds() / 60:.0f} min after {pre_session_name} end)")
    print(f"  ({(deadline - optimal).total_seconds() / 60:.0f} min before deadline)")
    print()

    # Compute post-race followup time
    gp_time = datetime.fromisoformat(next_race["sessions"]["Grand Prix"].replace("Z", "+00:00"))
    followup = gp_time + timedelta(days=args.schedule_followup_days)
    # Set followup to 14:00 UTC on that day (morning ET)
    followup = followup.replace(hour=14, minute=0, second=0)
    print(f"Post-race follow-up scheduled for: {followup.strftime('%a %b %d, %H:%M UTC')}")
    print()

    if args.dry_run:
        print("=== DRY RUN - No jobs scheduled ===")
        return 0

    # Schedule the optimizer job
    optimizer_msg = (
        f"Run F1 Fantasy optimizer for {next_race['name']} (Round {next_race['round']}).\n\n"
        f"Steps:\n"
        f"1. Log into F1 Fantasy at https://account.formula1.com/#/en/login "
        f"(email: pascal.ai.inbox@gmail.com, password: aA@pascal123)\n"
        f"2. Go to https://fantasy.formula1.com/en/my-team/1 to see current team\n"
        f"3. Run: cd /home/opc/repos/fantasy-formula-1 && python3.12 scripts/f1_fantasy.py run "
        f"--team-id 1 --expected-team-name 'Pascal GP 1' --profile-dir .playwright-profile\n"
        f"4. If Playwright fails, use the OpenClaw browser to:\n"
        f"   a. Scrape current team from /en/my-team page\n"
        f"   b. Run optimizer: python3.12 -c \"from f1fantasy.data_sources.f1fantasytools import load_optimal_and_prices; ...\"\n"
        f"5. Compare current team vs optimal (accounting for -10pt penalty per extra transfer)\n"
        f"6. If beneficial transfers exist, apply them via the F1 Fantasy site\n"
        f"7. Send results to Enzo on WhatsApp\n\n"
        f"IMPORTANT: Only apply transfers if net points gain is positive after penalties."
    )

    job_id = schedule_cron_job(
        name=f"F1 Fantasy optimizer - {next_race['name']} (R{next_race['round']})",
        at_iso=format_iso(optimal),
        message=optimizer_msg,
        delete_after=True,
    )
    print(f"✅ Optimizer job scheduled: {job_id}")
    print(f"   Runs at: {optimal.strftime('%a %b %d, %H:%M UTC')}")

    # Schedule the follow-up meta-scheduler job
    followup_msg = (
        f"Run F1 Fantasy meta-scheduler for next race week.\n\n"
        f"Execute: python3.12 /home/opc/repos/fantasy-formula-1/scripts/f1_meta_scheduler.py\n"
        f"This will schedule the optimizer job for the upcoming race."
    )

    followup_id = schedule_cron_job(
        name=f"F1 Fantasy meta-scheduler (post-R{next_race['round']})",
        at_iso=format_iso(followup),
        message=followup_msg,
        delete_after=True,
    )
    print(f"✅ Follow-up job scheduled: {followup_id}")
    print(f"   Runs at: {followup.strftime('%a %b %d, %H:%M UTC')}")

    print()
    print("Done! Jobs scheduled successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
