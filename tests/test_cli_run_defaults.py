import unittest

from f1fantasy import config
from scripts.f1_fantasy import build_parser


class TestCliRunDefaults(unittest.TestCase):
    def test_report_only_run_writes_generated_ideal_under_ignored_state_by_default(self):
        parser = build_parser()

        args = parser.parse_args(["run"])

        self.assertEqual(args.ideal_out, str(config.STATE_DIR / "ideal_team.json"))


if __name__ == "__main__":
    unittest.main()
