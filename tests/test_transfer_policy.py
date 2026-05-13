import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from f1fantasy.logic.transfer_policy import compute_baseline_transfer_policy, get_or_create_transfer_baseline


BASELINE_TEAM = {
    "drivers": ["A", "B", "C", "D", "E"],
    "constructors": ["X", "Y"],
    "boost_driver": "A",
}


class TestTransferBaselinePolicy(unittest.TestCase):
    def test_midweek_revision_counts_against_previous_race_baseline(self):
        current_after_first_swaps = {
            "drivers": ["A", "B", "C", "F", "G"],
            "constructors": ["X", "Y"],
            "boost_driver": "A",
        }
        revised_ideal = {
            "drivers": ["A", "B", "C", "F", "H"],
            "constructors": ["X", "Y"],
            "boost_driver": "A",
        }
        policy = compute_baseline_transfer_policy(
            baseline={"team": BASELINE_TEAM},
            current_state=current_after_first_swaps,
            ideal=revised_ideal,
            free_transfers=2,
        )

        self.assertTrue(policy["apply"])
        self.assertEqual(policy["baseline_transfers_required"], 2)
        self.assertEqual(policy["current_site_transfers_required"], 1)

    def test_blocks_one_more_ui_swap_when_result_would_be_three_from_baseline(self):
        current_after_first_swaps = {
            "drivers": ["A", "B", "C", "F", "G"],
            "constructors": ["X", "Y"],
            "boost_driver": "A",
        }
        illegal_ideal = {
            "drivers": ["A", "B", "F", "G", "H"],
            "constructors": ["X", "Y"],
            "boost_driver": "A",
        }
        policy = compute_baseline_transfer_policy(
            baseline={"team": BASELINE_TEAM},
            current_state=current_after_first_swaps,
            ideal=illegal_ideal,
            free_transfers=2,
        )

        self.assertFalse(policy["apply"])
        self.assertEqual(policy["baseline_transfers_required"], 3)
        self.assertEqual(policy["current_site_transfers_required"], 1)

    def test_baseline_is_created_once_then_reused_for_same_round(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("f1fantasy.config.STATE_DIR", Path(td)):
                ctx = {"round": 7, "name": "Example GP"}
                first = get_or_create_transfer_baseline(team_id=1, race_context=ctx, current_state=BASELINE_TEAM)
                changed_current = {
                    "drivers": ["A", "B", "C", "F", "G"],
                    "constructors": ["X", "Y"],
                    "boost_driver": "A",
                }
                second = get_or_create_transfer_baseline(team_id=1, race_context=ctx, current_state=changed_current)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(second["team"], BASELINE_TEAM)


if __name__ == "__main__":
    unittest.main()
