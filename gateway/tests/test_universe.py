from unittest import TestCase

from gateway.universe import tickers_from_symbols_payload


class UniverseTests(TestCase):
    def test_keeps_simulated_tickers_in_api_order(self) -> None:
        self.assertEqual(
            tickers_from_symbols_payload(
                {
                    "results": [
                        {"ticker": "000660", "simulation_enabled": True},
                        {"ticker": "005930", "simulation_enabled": False},
                        {"ticker": "009150", "simulation_enabled": True},
                    ]
                }
            ),
            ("000660", "009150"),
        )

    def test_rejects_empty_universe(self) -> None:
        with self.assertRaises(ValueError):
            tickers_from_symbols_payload({"results": []})
