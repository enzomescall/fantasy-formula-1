import unittest

from f1fantasy.data_sources.backup_model import (
    build_projection_payload,
    load_optimal_and_prices_from_projection,
    score_driver_projection,
)


class TestBackupModel(unittest.TestCase):
    def test_driver_scoring_applies_official_weekend_rules(self):
        score = score_driver_projection(
            {
                "quali_pos": 1,
                "sprint_start": 3,
                "sprint_finish": 1,
                "sprint_overtakes": 2,
                "sprint_fastest_lap_prob": 1,
                "race_start": 5,
                "race_finish": 1,
                "race_overtakes": 3,
                "race_fastest_lap_prob": 1,
                "dotd_prob": 1,
            }
        )

        # Quali 10 + sprint (8 result +2 gained +2 overtakes +5 FL)
        # + race (25 result +4 gained +3 overtakes +10 FL +10 DOTD)
        self.assertEqual(score["driver_points"], 79.0)
        self.assertEqual(score["constructor_driver_points"], 69.0)

    def test_projection_payload_matches_existing_optimizer_shape(self):
        projection = {
            "season": 2026,
            "raceweek": 9,
            "drivers": [
                {"code": "A", "team": "X", "price": 20.0, "quali_pos": 1, "race_start": 1, "race_finish": 1},
                {"code": "B", "team": "X", "price": 19.0, "quali_pos": 2, "race_start": 2, "race_finish": 2},
                {"code": "C", "team": "Y", "price": 18.0, "quali_pos": 3, "race_start": 3, "race_finish": 3},
                {"code": "D", "team": "Y", "price": 8.0, "quali_pos": 12, "race_start": 12, "race_finish": 9},
                {"code": "E", "team": "Z", "price": 7.0, "quali_pos": 15, "race_start": 15, "race_finish": 12},
                {"code": "F", "team": "Z", "price": 1.0, "quali_pos": 20, "race_start": 20, "race_finish": 18},
            ],
            "constructors": [
                {"code": "X", "price": 25.0, "pit_stop_points": 10},
                {"code": "Y", "price": 12.0, "pit_stop_points": 2},
                {"code": "Z", "price": 1.0, "pit_stop_points": 0},
            ],
        }
        payload = build_projection_payload(projection)

        self.assertEqual(payload["analystSims"][0]["season"], 2026)
        self.assertEqual(len(payload["drivers"]), 6)
        self.assertIn("X", payload["analystSims"][0]["constructors"]["pts"])

    def test_load_projection_optimizer(self):
        import json
        import tempfile
        from pathlib import Path

        projection = {
            "drivers": [
                {"code": "A", "team": "X", "price": 20.0, "quali_pos": 1, "race_start": 1, "race_finish": 1},
                {"code": "B", "team": "X", "price": 19.0, "quali_pos": 2, "race_start": 2, "race_finish": 2},
                {"code": "C", "team": "Y", "price": 18.0, "quali_pos": 3, "race_start": 3, "race_finish": 3},
                {"code": "D", "team": "Y", "price": 10.0, "quali_pos": 4, "race_start": 4, "race_finish": 4},
                {"code": "E", "team": "Z", "price": 9.0, "quali_pos": 5, "race_start": 5, "race_finish": 5},
                {"code": "F", "team": "Z", "price": 1.0, "quali_pos": 20, "race_start": 20, "race_finish": 19},
            ],
            "constructors": [
                {"code": "X", "price": 10.0},
                {"code": "Y", "price": 9.0},
                {"code": "Z", "price": 1.0},
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "projection.json"
            path.write_text(json.dumps(projection), encoding="utf-8")
            optimal, prices = load_optimal_and_prices_from_projection(200.0, path)

        self.assertEqual(len(optimal["drivers"]), 5)
        self.assertEqual(len(optimal["constructors"]), 2)
        self.assertEqual(optimal["projection_source"], "backup_model")
        self.assertIn("A", prices["drivers"])


if __name__ == "__main__":
    unittest.main()
