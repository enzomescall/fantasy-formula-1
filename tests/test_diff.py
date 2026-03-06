import unittest

from f1fantasy.logic.diff import compute_diff


class TestDiff(unittest.TestCase):
    def test_transfers_required_counts_adds(self):
        current = {
            "drivers": ["A", "B", "C", "D", "E"],
            "constructors": ["X", "Y"],
            "boost_driver": None,
        }
        ideal = {
            "drivers": ["A", "B", "C", "D", "F"],
            "constructors": ["X", "Z"],
            "boost_driver": None,
        }
        d = compute_diff(current, ideal)
        self.assertEqual(d["drivers_add"], ["F"])
        self.assertEqual(d["constructors_add"], ["Z"])
        self.assertEqual(d["transfers_required"], 2)


if __name__ == "__main__":
    unittest.main()
