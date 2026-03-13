#!/usr/bin/env python3.12
"""
Claude Code Watchdog — monitors a tmux session running Claude Code and alerts
if it gets stuck on permission prompts or is otherwise unresponsive.

Usage:
    python3.12 scripts/claude_watchdog.py [--session claude-code] [--interval 30] [--alert-webhook URL]

How it works:
1. Periodically captures tmux pane content
2. Looks for permission prompts (patterns like "Do you want to", "Allow", "Press Enter")
3. If stuck for >N checks in a row, sends an alert
4. Optionally auto-approves via tmux send-keys (configurable)

Environment:
    WATCHDOG_WHATSAPP_TO  — E.164 number to alert via OpenClaw (default: Enzo)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

# Patterns that indicate Claude Code is waiting for user input
STUCK_PATTERNS = [
    r"Do you want to",
    r"Allow\s.*\?",
    r"Press Enter to continue",
    r"Y/n",
    r"\[y/N\]",
    r"Proceed\?",
    r"Continue\?",
    r"Confirm\?",
    r"Would you like to",
    r"Enter your choice",
    r"Select an option",
    r"waiting for approval",
    r"Permission required",
]

# Patterns that indicate active work (not stuck)
ACTIVE_PATTERNS = [
    r"⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏",  # spinner
    r"Thinking",
    r"Processing",
    r"Running",
    r"Executing",
    r"Compiling",
    r"Installing",
]


def get_tmux_pane_content(session: str, window: str = "claude") -> str:
    """Capture current tmux pane content."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", f"{session}:{window}", "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def is_stuck(content: str) -> tuple[bool, str]:
    """Check if content indicates Claude is stuck on a prompt."""
    if not content.strip():
        return False, "empty"

    # Check for stuck patterns
    for pattern in STUCK_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True, pattern

    return False, "ok"


def is_active(content: str) -> bool:
    """Check if Claude appears to be actively working."""
    for pattern in ACTIVE_PATTERNS:
        if re.search(pattern, content):
            return True
    return False


def send_alert(message: str, channel: str = "whatsapp", to: str = "+19193818635"):
    """Send alert via OpenClaw message tool."""
    # Write alert to a file that can be picked up by OpenClaw
    alert_file = "/tmp/claude-watchdog-alert.json"
    with open(alert_file, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "channel": channel,
            "to": to,
        }, f)
    print(f"ALERT: {message}")
    return alert_file


def auto_approve(session: str, window: str = "claude") -> bool:
    """Send 'y' + Enter to auto-approve a prompt."""
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{session}:{window}", "y", "Enter"],
            timeout=5,
        )
        return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Code Watchdog")
    parser.add_argument("--session", default="claude-code", help="tmux session name")
    parser.add_argument("--window", default="claude", help="tmux window name")
    parser.add_argument("--interval", type=int, default=30, help="Check interval (seconds)")
    parser.add_argument("--stuck-threshold", type=int, default=3,
                        help="Consecutive stuck checks before alert")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Auto-approve permission prompts (use with caution)")
    parser.add_argument("--alert-file", default="/tmp/claude-watchdog-alert.json",
                        help="File to write alerts to")
    parser.add_argument("--dry-run", action="store_true", help="Print status without alerting")
    args = parser.parse_args()

    stuck_count = 0
    last_content = ""
    check_count = 0

    print(f"Watchdog started — monitoring tmux session '{args.session}:{args.window}'")
    print(f"Check interval: {args.interval}s, stuck threshold: {args.stuck_threshold}")
    print(f"Auto-approve: {args.auto_approve}")
    print()

    while True:
        check_count += 1
        content = get_tmux_pane_content(args.session, args.window)
        stuck, reason = is_stuck(content)
        active = is_active(content)
        now = datetime.now().strftime("%H:%M:%S")

        if stuck and not active:
            stuck_count += 1
            print(f"[{now}] STUCK ({stuck_count}/{args.stuck_threshold}) — pattern: {reason}")

            if stuck_count >= args.stuck_threshold:
                msg = f"🚨 Claude Code stuck on permission prompt ({args.session}:{args.window})\nPattern: {reason}\nLast 500 chars:\n{content[-500:]}"

                if not args.dry_run:
                    send_alert(msg)

                    if args.auto_approve:
                        print(f"[{now}] Auto-approving...")
                        auto_approve(args.session, args.window)
                        stuck_count = 0
                else:
                    print(f"[{now}] DRY RUN — would alert: {msg[:100]}...")

        elif stuck and active:
            print(f"[{now}] Prompt detected but Claude is active — not alerting")
        else:
            if stuck_count > 0:
                print(f"[{now}] Resumed! (was stuck for {stuck_count} checks)")
            stuck_count = 0

        # Only print heartbeat every 10 checks
        if check_count % 10 == 0:
            print(f"[{now}] heartbeat — {check_count} checks, status: {'stuck' if stuck else 'ok'}")

        last_content = content
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
