import json
from unittest import TestCase
from unittest.mock import patch

from participant_runner.client import BackendApiClient


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class BackendApiClientTests(TestCase):
    @patch("participant_runner.client.urlopen")
    def test_fetch_book_parses_strategy_snapshot(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = FakeResponse(
            {
                "symbol": "005930",
                "bids": [{"price": 69_900, "qty": 3}],
                "asks": [{"price": 70_100, "qty": 4}],
            }
        )
        client = BackendApiClient("http://backend:8000", timeout_ms=5_000)

        snapshot = client.fetch_book("005930")

        self.assertEqual(snapshot.symbol, "005930")
        self.assertEqual(snapshot.bids[0].price, 69_900)
        self.assertEqual(snapshot.asks[0].quantity, 4)
