from __future__ import annotations

import json
import ssl
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import certifi

F1_CALENDAR_API = "https://f1calendar.com/api/calendar"
DEFAULT_DEADLINE_OFFSET = timedelta(minutes=30)
DEFAULT_SESSION_DURATION = timedelta(hours=1)


@dataclass(frozen=True)
class DeadlineDecision:
    allowed: bool
    reason: str
    now_utc: str
    deadline_utc: str
    safety_margin_seconds: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_calendar_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_calendar() -> list[dict]:
    """Fetch F1 calendar data. Network wrapper kept separate from pure deadline logic."""
    req = urllib.request.Request(F1_CALENDAR_API, headers={"User-Agent": "Mozilla/5.0"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        data = json.loads(r.read().decode())
    return data["races"]


def find_next_race(now: datetime, races: list[dict]) -> dict | None:
    now_utc = _utc(now)
    upcoming = []
    for race in races:
        sessions = race.get("sessions", {})
        gp = sessions.get("Grand Prix")
        if not gp:
            continue
        gp_time = parse_calendar_datetime(gp)
        if gp_time > now_utc:
            upcoming.append((gp_time, race))
    if not upcoming:
        return None
    upcoming.sort(key=lambda item: item[0])
    return upcoming[0][1]


def is_sprint_weekend(race: dict) -> bool:
    sessions = race.get("sessions", {})
    return "Sprint" in sessions or "Sprint Qualifying" in sessions or "Sprint Shootout" in sessions


def get_deadline_and_pre_session(race: dict) -> tuple[datetime, str, datetime]:
    """Return (deadline_utc, pre_session_name, pre_session_end_utc).

    Current F1 Fantasy lock policy used by this automation:
    - Sprint weekends lock 30 minutes before Sprint.
    - Normal weekends lock 30 minutes before Qualifying.
    """
    sessions = race.get("sessions", {})
    if is_sprint_weekend(race):
        sprint_start_raw = sessions.get("Sprint")
        if not sprint_start_raw:
            raise ValueError("Sprint weekend calendar is missing Sprint session")
        pre_name = "Sprint Qualifying" if "Sprint Qualifying" in sessions else "Sprint Shootout"
        if pre_name not in sessions:
            raise ValueError("Sprint weekend calendar is missing Sprint Qualifying/Sprint Shootout")
        deadline = parse_calendar_datetime(sprint_start_raw) - DEFAULT_DEADLINE_OFFSET
        pre_end = parse_calendar_datetime(sessions[pre_name]) + DEFAULT_SESSION_DURATION
        return deadline, pre_name, pre_end

    if "Qualifying" not in sessions:
        raise ValueError("Calendar is missing Qualifying session")
    if "Free Practice 3" not in sessions:
        raise ValueError("Calendar is missing Free Practice 3 session")
    deadline = parse_calendar_datetime(sessions["Qualifying"]) - DEFAULT_DEADLINE_OFFSET
    pre_end = parse_calendar_datetime(sessions["Free Practice 3"]) + DEFAULT_SESSION_DURATION
    return deadline, "Free Practice 3", pre_end


def can_apply_before_deadline(
    *,
    now: datetime,
    deadline: datetime,
    safety_margin: timedelta = timedelta(0),
) -> DeadlineDecision:
    now_utc = _utc(now)
    deadline_utc = _utc(deadline)
    effective_deadline = deadline_utc - safety_margin
    allowed = now_utc < effective_deadline
    if allowed:
        reason = f"Before fantasy deadline {deadline_utc.isoformat()}"
    elif safety_margin > timedelta(0) and now_utc < deadline_utc:
        reason = (
            f"Within safety margin before fantasy deadline {deadline_utc.isoformat()} "
            f"(margin {int(safety_margin.total_seconds())}s)"
        )
    else:
        reason = f"At or after fantasy deadline {deadline_utc.isoformat()}"
    return DeadlineDecision(
        allowed=allowed,
        reason=reason,
        now_utc=now_utc.isoformat(),
        deadline_utc=deadline_utc.isoformat(),
        safety_margin_seconds=int(safety_margin.total_seconds()),
    )


def current_deadline_decision(*, now: datetime | None = None, safety_margin: timedelta = timedelta(0)) -> tuple[DeadlineDecision, dict]:
    now_utc = _utc(now or datetime.now(timezone.utc))
    races = fetch_calendar()
    race = find_next_race(now_utc, races)
    if race is None:
        raise RuntimeError("No upcoming race found in F1 calendar")
    deadline, pre_name, pre_end = get_deadline_and_pre_session(race)
    decision = can_apply_before_deadline(now=now_utc, deadline=deadline, safety_margin=safety_margin)
    context = {
        "race_name": race.get("name"),
        "round": race.get("round"),
        "deadline_utc": deadline.isoformat(),
        "pre_session_name": pre_name,
        "pre_session_end_utc": pre_end.isoformat(),
    }
    return decision, context


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
