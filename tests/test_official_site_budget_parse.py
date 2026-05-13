import unittest

from f1fantasy.data_sources.official_site import _best_selected_price_values, _parse_selected_price_values


class TestSelectedPriceParse(unittest.TestCase):
    def test_scoped_selected_prices_ignore_cost_cap(self):
        txt = """
        Cost Cap: $7.5M
        Driver A
        $30.0M
        Driver B
        $24.5M
        Driver C
        $18.0M
        Driver D
        $12.0M
        Driver E
        $9.5M
        Constructor X
        $25.0M
        Constructor Y
        $15.0M
        """
        self.assertEqual(
            _parse_selected_price_values(txt),
            [30.0, 24.5, 18.0, 12.0, 9.5, 25.0, 15.0],
        )

    def test_selected_region_with_asset_price_and_value_delta(self):
        txt = """
        Cost Cap:
        $0.6M
        2X
        C.LECLERC
        $24.0M
        $0.3M
        E.OCON
        $9.7M
        $0.6M
        L.LAWSON
        $8.1M
        $0.6M
        F.COLAPINTO
        $8.2M
        $0.6M
        N.HULKENBERG
        $4.4M
        $0.6M
        Ferrari
        $24.5M
        $0.3M
        Mercedes
        $30.5M
        $0.3M
        """
        self.assertEqual(
            _parse_selected_price_values(txt),
            [24.0, 9.7, 8.1, 8.2, 4.4, 24.5, 30.5],
        )

    def test_market_list_fails_safe_when_not_exact_team(self):
        txt = """
        Available Drivers
        Pick a driver $30.0M
        Driver B $24.5M
        Driver C $18.0M
        Driver D $12.0M
        Driver E $9.5M
        Driver F $8.0M
        Driver G $7.0M
        Driver H $6.0M
        """
        self.assertEqual(_parse_selected_price_values(txt), [])

    def test_best_selected_price_values_does_not_fall_back_to_body_market(self):
        body_like_market = "\n".join(f"Market Driver {i} ${i}.0M" for i in range(1, 15))
        selected_region = "\n".join([
            "Driver A $30.0M",
            "Driver B $24.0M",
            "Driver C $18.0M",
            "Driver D $12.0M",
            "Driver E $9.0M",
            "Constructor X $25.0M",
            "Constructor Y $15.0M",
        ])
        self.assertEqual(
            _best_selected_price_values([body_like_market, selected_region]),
            [30.0, 24.0, 18.0, 12.0, 9.0, 25.0, 15.0],
        )


if __name__ == "__main__":
    unittest.main()
