from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.urls import reverse
from prometheus_client import REGISTRY
from rest_framework.test import APITestCase
from unittest import TestCase

from exchange.market_session import MarketSession
from exchange.orderbook.registry import books


SEOUL = ZoneInfo("Asia/Seoul")


class MarketSessionTests(TestCase):
    def setUp(self) -> None:
        self.session = MarketSession("scheduled")

    def test_regular_session_boundaries(self) -> None:
        cases = (
            (datetime(2026, 9, 21, 8, 59, 59, tzinfo=SEOUL), False),
            (datetime(2026, 9, 21, 9, 0, 0, tzinfo=SEOUL), True),
            (datetime(2026, 9, 21, 15, 29, 59, tzinfo=SEOUL), True),
            (datetime(2026, 9, 21, 15, 30, 0, tzinfo=SEOUL), False),
            (datetime(2026, 9, 26, 12, 0, 0, tzinfo=SEOUL), False),
            (datetime(2026, 9, 27, 12, 0, 0, tzinfo=SEOUL), False),
        )

        for current, expected in cases:
            with self.subTest(current=current):
                self.assertEqual(self.session.is_open(current), expected)

    def test_utc_input_is_compared_in_korea_time(self) -> None:
        self.assertTrue(
            self.session.is_open(
                datetime(2026, 9, 21, 0, 0, 0, tzinfo=timezone.utc)
            )
        )

    def test_next_open_skips_weekend(self) -> None:
        friday_after_close = datetime(2026, 9, 25, 18, 0, tzinfo=SEOUL)

        self.assertEqual(
            self.session.next_open(friday_after_close),
            datetime(2026, 9, 28, 9, 0, tzinfo=SEOUL),
        )

    def test_naive_datetime_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.session.is_open(datetime(2026, 9, 21, 9, 0))

    def test_always_open_bypasses_weekday_and_clock(self) -> None:
        session = MarketSession("always_open")

        self.assertTrue(
            session.is_open(datetime(2026, 9, 27, 3, 0, tzinfo=SEOUL))
        )


@override_settings(SIMULATION_MARKET_MODE="scheduled")
class MarketSessionOrderApiTests(APITestCase):
    def setUp(self) -> None:
        books.reset()

    def submit_order(self):
        return self.client.post(
            reverse("order-create"),
            {
                "user_id": "session-test",
                "symbol": "005930",
                "side": "BUY",
                "price": 70_000,
                "qty": 1,
            },
            format="json",
        )

    def test_order_is_accepted_at_market_open(self) -> None:
        with patch(
            "exchange.market_session._utc_now",
            return_value=datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc),
        ):
            response = self.submit_order()

        self.assertEqual(response.status_code, 201)

    def test_order_is_rejected_at_market_close_and_metric_increments(self) -> None:
        rejected_before = REGISTRY.get_sample_value(
            "orders_rejected_total",
            {"reason": "market_closed"},
        ) or 0

        with patch(
            "exchange.market_session._utc_now",
            return_value=datetime(2026, 9, 21, 6, 30, tzinfo=timezone.utc),
        ):
            response = self.submit_order()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "market is closed"})
        rejected_after = REGISTRY.get_sample_value(
            "orders_rejected_total",
            {"reason": "market_closed"},
        ) or 0
        self.assertEqual(rejected_after - rejected_before, 1)

        book = self.client.get(reverse("book-detail", args=["005930"]))
        self.assertEqual(book.data["bids"], [])
        self.assertEqual(book.data["asks"], [])

    def test_cancel_remains_available_after_market_close(self) -> None:
        with self.settings(SIMULATION_MARKET_MODE="always_open"):
            created = self.submit_order()

        self.assertEqual(created.status_code, 201)
        order_id = created.data["order_id"]

        with patch(
            "exchange.market_session._utc_now",
            return_value=datetime(2026, 9, 21, 6, 30, tzinfo=timezone.utc),
        ):
            response = self.client.delete(reverse("order-cancel", args=[order_id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "CANCELED")

    @override_settings(SIMULATION_MARKET_MODE="always_open")
    def test_always_open_accepts_weekend_orders(self) -> None:
        with patch(
            "exchange.market_session._utc_now",
            return_value=datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc),
        ):
            response = self.submit_order()

        self.assertEqual(response.status_code, 201)
