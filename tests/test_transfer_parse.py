import unittest

from f1fantasy.data_sources.official_site import _parse_transfer_status_text


class TestTransferParse(unittest.TestCase):
    def test_parse_free_transfers(self):
        free, pen = _parse_transfer_status_text("You have 3 Free Transfers remaining")
        self.assertEqual(free, 3)
        self.assertIsNone(pen)

    def test_parse_stacked_free_transfers(self):
        txt = "Free Transfers\n2 of 2\nCost Cap:\n$0.6M"
        free, penalty = _parse_transfer_status_text(txt)
        self.assertEqual(free, 2)
        self.assertIsNone(penalty)

    def test_does_not_confuse_formula_1_with_free_transfer_count(self):
        txt = "Formula 1 World Championship\nFree Transfers\n2 of 2"
        free, penalty = _parse_transfer_status_text(txt)
        self.assertEqual(free, 2)
        self.assertIsNone(penalty)

    def test_parse_penalty_points(self):
        txt = "Transfer penalty -10 pts for each additional transfer. You have 2 free transfers."
        free, pen = _parse_transfer_status_text(txt)
        self.assertEqual(free, 2)
        self.assertEqual(pen, 10)


if __name__ == "__main__":
    unittest.main()
