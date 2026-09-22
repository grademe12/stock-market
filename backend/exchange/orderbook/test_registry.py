from datetime import date

from django.test import SimpleTestCase

from exchange.orderbook import Order, OrderNotFoundError, OrderSide
from exchange.orderbook.registry import OrderBookRegistry


class OrderBookRegistrySessionTests(SimpleTestCase):
    symbol = "005930"

    def setUp(self) -> None:
        self.registry = OrderBookRegistry()
        self.registry.rollover(date(2026, 9, 21))

    def order(self) -> Order:
        return Order(
            user_id="session-test",
            symbol=self.symbol,
            side=OrderSide.BUY,
            price=70_000,
            quantity=3,
        )

    def test_same_session_keeps_existing_book(self) -> None:
        order = self.order()
        self.registry.submit(order)

        cleared = self.registry.rollover(date(2026, 9, 21))

        self.assertEqual(cleared, ())
        snapshot = self.registry.get(self.symbol).snapshot()
        self.assertEqual(snapshot.bids[0].quantity, 3)

    def test_newer_session_clears_books_and_order_id_map(self) -> None:
        order = self.order()
        self.registry.submit(order)

        cleared = self.registry.rollover(date(2026, 9, 22))

        self.assertEqual(cleared, (self.symbol,))
        snapshot = self.registry.get(self.symbol).snapshot()
        self.assertEqual(snapshot.bids, ())
        self.assertEqual(snapshot.asks, ())
        with self.assertRaises(OrderNotFoundError):
            self.registry.cancel(order.order_id)

    def test_older_session_date_does_not_roll_state_back(self) -> None:
        order = self.order()
        self.registry.submit(order)
        self.registry.rollover(date(2026, 9, 22))

        replacement = self.order()
        self.registry.submit(replacement)

        cleared = self.registry.rollover(date(2026, 9, 21))

        self.assertEqual(cleared, ())
        self.assertIsNotNone(
            self.registry.get(self.symbol).get_open_order(replacement.order_id)
        )

    def test_reset_books_does_not_require_symbol_cache_reset(self) -> None:
        order = self.order()
        self.registry.submit(order)

        cleared = self.registry.reset_books()

        self.assertEqual(cleared, (self.symbol,))
        self.assertEqual(self.registry.get(self.symbol).snapshot().bids, ())
