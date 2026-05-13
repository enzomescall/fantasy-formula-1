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
from datetime import datetime, timedelta, timezone
from pathlib import Path

F1_CALENDAR_API = "https://f1calendar.com/api/calendar"
OPTIMIZER_SCRIPT = Path(__file__).parent / "f1_fantasy.py"
REPO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_DIR))

from f1fantasy.logic.deadline import (  # noqa: E402
    fetch_calendar,
    find_next_race,
    get_deadline_and_pre_session,
    is_sprint_weekend,
    parse_calendar_datetime,
)

# Slack time before deadline (minutes) - how early we want to finish applying
SLACK_BEFORE_DEADLINE_MIN = 30
MODEL_UPDATE_DELAY_MIN = 45
SESSION_DURATION = timedelta(hours=1)

# How many days after the race to schedule the next meta-scheduler run
POST_RACE_FOLLOWUP_DAYS = 3


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


def compute_optimizer_runs(race: dict, *, now: datetime) -> list[tuple[str, datetime]]:
    """Return all useful pre-lock optimizer run times for a race week.

    Transfers are reversible until lock, so we prefer several guarded apply
    opportunities: a seed run before track action, then reruns after each
    information-producing session that occurs before the fantasy deadline.
    """

    deadline, pre_session_name, pre_session_end = get_deadline_and_pre_session(race)
    latest_start = deadline - timedelta(minutes=SLACK_BEFORE_DEADLINE_MIN)
    sessions = race.get("sessions", {})
    names = ["Free Practice 1"]
    if is_sprint_weekend(race):
        names.extend(["Sprint Qualifying", "Sprint Shootout"])
    else:
        names.extend(["Free Practice 2", "Free Practice 3"])

    runs: list[tuple[str, datetime]] = []
    fp1_raw = sessions.get("Free Practice 1")
    if fp1_raw:
        fp1 = parse_calendar_datetime(fp1_raw)
        seed = min(fp1 - timedelta(hours=2), latest_start)
        if seed > now:
            runs.append(("seed-before-fp1", seed))

    for name in names:
        raw = sessions.get(name)
        if not raw:
            continue
        session_end = parse_calendar_datetime(raw) + SESSION_DURATION
        run_at = session_end + timedelta(minutes=MODEL_UPDATE_DELAY_MIN)
        if name == pre_session_name:
            run_at = compute_optimal_time(session_end, deadline)
        if now < run_at < latest_start:
            runs.append((f"after-{safe_job_token(name)}", run_at))

    # Ensure a final guardrail run exists even if the calendar/session math above
    # misses a session name variant.
    final_run = min(compute_optimal_time(pre_session_end, deadline), latest_start)
    if final_run > now and all(abs((final_run - t).total_seconds()) > 300 for _, t in runs):
        runs.append(("final-pre-lock", final_run))

    return sorted(runs, key=lambda item: item[1])


def safe_job_token(name: str) -> str:
    return name.lower().replace(" ", "-")


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
        t = parse_calendar_datetime(time_str)
        print(f"  {name}: {t.strftime('%a %b %d, %H:%M UTC')}")
    print()

    # Determine deadline and pre-session
    deadline, pre_session_name, pre_session_end = get_deadline_and_pre_session(next_race)
    print(f"Pre-deadline session: {pre_session_name}")
    print(f"  Ends at: {pre_session_end.strftime('%a %b %d, %H:%M UTC')}")
    print(f"Fantasy deadline: {deadline.strftime('%a %b %d, %H:%M UTC')}")
    print()

    # Compute optimizer run times
    optimizer_runs = compute_optimizer_runs(next_race, now=now)
    print("Optimizer run plan:")
    if optimizer_runs:
        for label, run_at in optimizer_runs:
            print(f"  {label}: {run_at.strftime('%a %b %d, %H:%M UTC')}")
    else:
        print("  No pre-lock optimizer runs remain for this race")
    print()

    # Compute post-race followup time
    gp_time = parse_calendar_datetime(next_race["sessions"]["Grand Prix"])
    followup = gp_time + timedelta(days=args.schedule_followup_days)
    # Set followup to 14:00 UTC on that day (morning ET)
    followup = followup.replace(hour=14, minute=0, second=0)
    print(f"Post-race follow-up scheduled for: {followup.strftime('%a %b %d, %H:%M UTC')}")
    print()

    if args.dry_run:
        print("=== DRY RUN - No jobs scheduled ===")
        return 0

    optimizer_msg_template = (
        "Run F1 Fantasy optimizer for {race_name} (Round {round}) at checkpoint {checkpoint}.\n\n"
        "Steps:\n"
        "1. Use credentials only from .env (F1_EMAIL/F1_PASSWORD), an existing persistent "
        "Playwright profile, or manual browser login. Do not print or paste passwords.\n"
        "2. Run a report-only pass: cd /home/opc/repos/fantasy-formula-1 && "
        "python3.12 scripts/f1_fantasy.py run --team-id 1 --expected-team-name 'Pascal GP 1' "
        "--profile-dir .playwright-profile\n"
        "3. Review state/last_run.json. The transfer policy must use baseline_transfers_required, "
        "not the current-site UI diff, because midweek provisional swaps are reversible until lock.\n"
        "4. Review chip_strategy.notes plus chip_strategy.chip_math.limitless and chip_strategy.chip_math.x3_boost. "
        "If the ideal team is 4+ baseline swaps away, explicitly say 'consider Wildcard'. On Sprint weekends, "
        "compare Auto Pilot, No Negative, Limitless, and x3 subjectively; check weather because rain increases No Negative value. "
        "For x3, remember the optimizer uses a separate 3x driver and normal 2x driver.\n"
        "5. If policy_decision.apply is true and projections are fresh for this race, apply immediately unless chip/transfer planning "
        "argues for preserving 3 free transfers into an upcoming Sprint: "
        "python3.12 scripts/f1_fantasy.py run --team-id 1 --expected-team-name 'Pascal GP 1' "
        "--profile-dir .playwright-profile --apply\n"
        "6. Send the report/results to Enzo on WhatsApp.\n\n"
        "IMPORTANT: Applying early is intentional; later checkpoints can revise the team while staying "
        "within the free-transfer limit relative to the saved race-week baseline."
    )

    scheduled_optimizer_ids = []
    for label, run_at in optimizer_runs:
        optimizer_msg = optimizer_msg_template.format(
            race_name=next_race["name"],
            round=next_race["round"],
            checkpoint=label,
        )
        job_id = schedule_cron_job(
            name=f"F1 Fantasy {label} - {next_race['name']} (R{next_race['round']})",
            at_iso=format_iso(run_at),
            message=optimizer_msg,
            delete_after=True,
        )
        scheduled_optimizer_ids.append(job_id)
        print(f"✅ Optimizer job scheduled: {job_id}")
        print(f"   {label}: {run_at.strftime('%a %b %d, %H:%M UTC')}")

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
