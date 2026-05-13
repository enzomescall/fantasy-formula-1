from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from f1fantasy.logic.deadline import can_apply_before_deadline, get_deadline_and_pre_session
from f1fantasy.logic.lock import FileLock, LockAcquisitionError


class DeadlineGuardTests(unittest.TestCase):
    def test_normal_weekend_deadline_is_before_qualifying(self):
        race = {
            "name": "Test GP",
            "sessions": {
                "Free Practice 3": "2026-05-23T10:30:00Z",
                "Qualifying": "2026-05-23T14:00:00Z",
                "Grand Prix": "2026-05-24T13:00:00Z",
            },
        }

        deadline, pre_name, pre_end = get_deadline_and_pre_session(race)

        self.assertEqual(datetime(2026, 5, 23, 13, 30, tzinfo=timezone.utc), deadline)
        self.assertEqual("Free Practice 3", pre_name)
        self.assertEqual(datetime(2026, 5, 23, 11, 30, tzinfo=timezone.utc), pre_end)

    def test_sprint_weekend_deadline_is_before_sprint(self):
        race = {
            "name": "Sprint GP",
            "sessions": {
                "Sprint Qualifying": "2026-05-02T15:30:00Z",
                "Sprint": "2026-05-03T10:00:00Z",
                "Qualifying": "2026-05-03T14:00:00Z",
                "Grand Prix": "2026-05-04T13:00:00Z",
            },
        }

        deadline, pre_name, pre_end = get_deadline_and_pre_session(race)

        self.assertEqual(datetime(2026, 5, 3, 9, 30, tzinfo=timezone.utc), deadline)
        self.assertEqual("Sprint Qualifying", pre_name)
        self.assertEqual(datetime(2026, 5, 2, 16, 30, tzinfo=timezone.utc), pre_end)

    def test_can_apply_blocks_at_or_after_deadline_by_default(self):
        deadline = datetime(2026, 5, 23, 13, 30, tzinfo=timezone.utc)

        before = can_apply_before_deadline(now=deadline - timedelta(seconds=1), deadline=deadline)
        at_deadline = can_apply_before_deadline(now=deadline, deadline=deadline)
        after = can_apply_before_deadline(now=deadline + timedelta(seconds=1), deadline=deadline)

        self.assertTrue(before.allowed)
        self.assertFalse(at_deadline.allowed)
        self.assertFalse(after.allowed)
        self.assertIn("deadline", after.reason.lower())

    def test_can_apply_honors_safety_margin(self):
        deadline = datetime(2026, 5, 23, 13, 30, tzinfo=timezone.utc)

        decision = can_apply_before_deadline(
            now=deadline - timedelta(minutes=10),
            deadline=deadline,
            safety_margin=timedelta(minutes=15),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("safety margin", decision.reason.lower())


class LockGuardTests(unittest.TestCase):
    def test_file_lock_prevents_concurrent_acquisition_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "apply.lock"
            with FileLock(lock_path):
                self.assertTrue(lock_path.exists())
                with self.assertRaises(LockAcquisitionError):
                    with FileLock(lock_path):
                        pass
            self.assertFalse(lock_path.exists())

    def test_file_lock_cleans_up_after_exception(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "apply.lock"
            with self.assertRaises(RuntimeError):
                with FileLock(lock_path):
                    raise RuntimeError("boom")
            self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
