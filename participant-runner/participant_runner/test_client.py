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

    @patch("participant_runner.client.urlopen")
    def test_fetch_ready_returns_shard_topology(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = FakeResponse(
            {
                "status": "ready",
                "database": "ok",
                "shard_index": 0,
                "shard_count": 4,
                "listen_port": 8000,
            }
        )
        client = BackendApiClient("http://backend:8000", timeout_ms=5_000)

        payload = client.fetch_ready()

        self.assertEqual(payload["shard_count"], 4)


    @patch("participant_runner.client.urlopen")
    def test_fetch_pending_market_events_parses_dispatch_contract(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = FakeResponse(
            {
                "market_open": True,
                "results": [
                    {
                        "event_id": "opendart:20260928000123:005930",
                        "symbol": "005930",
                        "event_type": "supply_contract",
                        "direction": "BUY",
                        "confidence": 0.85,
                        "impact": "high",
                        "source": "opendart",
                        "headline": "삼성전자 공급계약",
                    }
                ],
            }
        )
        client = BackendApiClient("http://backend:8000", timeout_ms=5_000)

        events = client.fetch_pending_market_events(("005930", "000660"))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "opendart:20260928000123:005930")
        self.assertEqual(events[0].direction, "BUY")
        self.assertEqual(events[0].impact, "high")
        request = mocked_urlopen.call_args.args[0]
        self.assertIn("/api/v1/events/pending/?", request.full_url)
        self.assertIn("005930", request.full_url)
        self.assertIn("000660", request.full_url)

    @patch("participant_runner.client.urlopen")
    def test_acknowledge_market_event_accepts_dispatched_state(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = FakeResponse(
            {
                "event_id": "opendart:20260928000123:005930",
                "status": "acknowledged",
                "state": "dispatched",
            }
        )
        client = BackendApiClient("http://backend:8000", timeout_ms=5_000)

        client.acknowledge_market_event("opendart:20260928000123:005930")

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertIn("/api/v1/events/", request.full_url)
        self.assertTrue(request.full_url.endswith("/ack/"))
