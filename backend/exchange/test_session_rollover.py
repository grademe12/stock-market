from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.urls import reverse
from prometheus_client import REGISTRY
from rest_framework.test import APITestCase

from exchange.orderbook.registry import books


SEOUL = ZoneInfo("Asia/Seoul")


@override_settings(SIMULATION_MARKET_MODE="scheduled")
class MarketSessionRolloverApiTests(APITestCase):
    def setUp(self) -> None:
        books.reset()

    def submit_order(self, current: datetime):
        with patch("exchange.market_session._utc_now", return_value=current):
            return self.client.post(
                reverse("order-create"),
                {
                    "user_id": "rollover-test",
                    "symbol": "005930",
                    "side": "BUY",
                    "price": 70_000,
                    "qty": 2,
                },
                format="json",
            )

    def test_next_trading_day_book_read_clears_previous_session(self) -> None:
        created = self.submit_order(
            datetime(2026, 9, 21, 9, 0, tzinfo=SEOUL)
        )
        self.assertEqual(created.status_code, 201)

        with patch(
            "exchange.market_session._utc_now",
            return_value=datetime(2026, 9, 22, 8, 0, tzinfo=SEOUL),
        ):
            book = self.client.get(reverse("book-detail", args=["005930"]))

        self.assertEqual(book.status_code, 200)
        self.assertEqual(book.data["bids"], [])
        self.assertEqual(book.data["asks"], [])

    def test_previous_order_id_is_closed_after_rollover(self) -> None:
        created = self.submit_order(
            datetime(2026, 9, 21, 9, 0, tzinfo=SEOUL)
        )
        order_id = created.data["order_id"]

        with patch(
            "exchange.market_session._utc_now",
            return_value=datetime(2026, 9, 22, 8, 0, tzinfo=SEOUL),
        ):
            canceled = self.client.delete(
                reverse("order-cancel", args=[order_id])
            )

        self.assertEqual(canceled.status_code, 200)
        self.assertEqual(canceled.data["status"], "ALREADY_CLOSED")

    def test_rollover_resets_orderbook_depth_metric(self) -> None:
        created = self.submit_order(
            datetime(2026, 9, 21, 9, 0, tzinfo=SEOUL)
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            REGISTRY.get_sample_value(
                "orderbook_depth",
                {"symbol": "005930", "side": "BUY"},
            ),
            2,
        )

        with patch(
            "exchange.market_session._utc_now",
            return_value=datetime(2026, 9, 22, 8, 0, tzinfo=SEOUL),
        ):
            self.client.get(reverse("book-detail", args=["005930"]))

        self.assertEqual(
            REGISTRY.get_sample_value(
                "orderbook_depth",
                {"symbol": "005930", "side": "BUY"},
            ),
            0,
        )
        self.assertEqual(
            REGISTRY.get_sample_value(
                "orderbook_depth",
                {"symbol": "005930", "side": "SELL"},
            ),
            0,
        )

    @override_settings(SIMULATION_MARKET_MODE="always_open")
    def test_always_open_does_not_roll_books_at_midnight(self) -> None:
        created = self.submit_order(
            datetime(2026, 9, 21, 23, 59, tzinfo=SEOUL)
        )
        self.assertEqual(created.status_code, 201)

        with patch(
            "exchange.market_session._utc_now",
            return_value=datetime(2026, 9, 22, 0, 1, tzinfo=SEOUL),
        ):
            book = self.client.get(reverse("book-detail", args=["005930"]))

        self.assertEqual(book.data["bids"], [{"price": 70_000, "qty": 2}])
