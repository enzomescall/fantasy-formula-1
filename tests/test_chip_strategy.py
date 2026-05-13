import unittest

from f1fantasy.data_sources.f1fantasytools import compute_optimal
from f1fantasy.logic.chip_strategy import build_chip_strategy_report


DATA = {
    "drivers": [
        {"type": "driver", "id": "1", "abbreviation": "A", "price": 20.0},
        {"type": "driver", "id": "2", "abbreviation": "B", "price": 19.0},
        {"type": "driver", "id": "3", "abbreviation": "C", "price": 18.0},
        {"type": "driver", "id": "4", "abbreviation": "D", "price": 10.0},
        {"type": "driver", "id": "5", "abbreviation": "E", "price": 9.0},
        {"type": "driver", "id": "6", "abbreviation": "F", "price": 1.0},
    ],
    "constructors": [
        {"type": "constructor", "abbreviation": "X", "price": 10.0},
        {"type": "constructor", "abbreviation": "Y", "price": 9.0},
        {"type": "constructor", "abbreviation": "Z", "price": 1.0},
    ],
    "analystSims": [
        {
            "id": "sim1",
            "name": "Example sim",
            "raceweek": 7,
            "season": 2026,
            "drivers": {"pts": {"1": 50, "2": 40, "3": 30, "4": 20, "5": 10, "6": 1}},
            "constructors": {"pts": {"X": 25, "Y": 15, "Z": 1}},
        }
    ],
}


class TestChipStrategy(unittest.TestCase):
    def test_x3_optimizer_uses_separate_triple_and_standard_boost(self):
        standard = compute_optimal(200.0, DATA)
        x3 = compute_optimal(200.0, DATA, scoring_mode="x3")

        self.assertEqual(standard["boost"], "A")
        self.assertEqual(x3["x3_boost"], "A")
        self.assertEqual(x3["boost"], "B")
        self.assertGreater(x3["expected_points"], standard["expected_points"])

    def test_wildcard_and_final_fix_notes_are_emitted(self):
        report = build_chip_strategy_report(
            race_context={"race_name": "Monaco Grand Prix", "round": 8},
            standard_optimal={"expected_points": 100},
            limitless_optimal={"expected_points": 110, "drivers": [], "constructors": []},
            x3_optimal={"expected_points": 115, "drivers": [], "constructors": [], "x3_boost": "A", "boost": "B"},
            transfer_policy={"baseline_transfers_required": 5},
            transfer_status={"free_transfers": 2, "penalty_points_per_extra": -10},
            site_before=None,
            ideal=None,
        )

        notes = "\n".join(report["notes"])
        self.assertIn("consider Wildcard", notes)
        self.assertIn("Final Fix watch", notes)
        self.assertTrue(report["flags"]["qualifying_heavy_race"])


if __name__ == "__main__":
    unittest.main()
