import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import scripts.f1_meta_scheduler as scheduler


class TestMetaSchedulerPrompt(unittest.TestCase):
    def test_optimizer_prompt_uses_unique_report_output_path(self):
        now = datetime.now(timezone.utc)
        race = {
            "round": 99,
            "name": "Test Grand Prix",
            "location": "Testville",
            "sessions": {
                "Free Practice 1": (now + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                "Free Practice 2": (now + timedelta(days=3)).isoformat().replace("+00:00", "Z"),
                "Free Practice 3": (now + timedelta(days=4)).isoformat().replace("+00:00", "Z"),
                "Qualifying": (now + timedelta(days=4, hours=3)).isoformat().replace("+00:00", "Z"),
                "Grand Prix": (now + timedelta(days=5)).isoformat().replace("+00:00", "Z"),
            },
        }
        messages = []

        def fake_schedule(name, at_iso, message, delete_after=True):
            messages.append(message)
            return "job-id"

        with (
            patch.object(scheduler, "fetch_calendar", lambda: [race]),
            patch.object(scheduler, "schedule_cron_job", fake_schedule),
            patch("sys.argv", ["f1_meta_scheduler.py"]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(scheduler.main(), 0)

        optimizer_messages = [msg for msg in messages if "Run F1 Fantasy optimizer" in msg]
        self.assertTrue(optimizer_messages)
        self.assertIn("--out state/cron_test-grand-prix_round99_last_run.json", optimizer_messages[0])
        self.assertIn("Review state/cron_test-grand-prix_round99_last_run.json", optimizer_messages[0])


if __name__ == "__main__":
    unittest.main()
