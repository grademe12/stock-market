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


class OrderBookRegistryOrderIdMapTests(SimpleTestCase):
    """The order-ID map holds resting orders only (it used to keep every order forever)."""

    symbol = "005930"

    def setUp(self) -> None:
        self.registry = OrderBookRegistry()

    def order(self, side: OrderSide, quantity: int) -> Order:
        return Order(user_id="map-test", symbol=self.symbol, side=side, price=70_000, quantity=quantity)

    def test_filled_orders_leave_the_map(self) -> None:
        maker = self.order(OrderSide.SELL, 5)
        taker = self.order(OrderSide.BUY, 5)
        self.registry.submit(maker)
        self.assertEqual(self.registry.open_order_id_count(), 1)

        self.registry.submit(taker)

        self.assertEqual(self.registry.open_order_id_count(), 0)

    def test_partially_filled_maker_stays_cancelable(self) -> None:
        maker = self.order(OrderSide.SELL, 5)
        self.registry.submit(maker)
        self.registry.submit(self.order(OrderSide.BUY, 2))

        canceled = self.registry.cancel(maker.order_id)

        self.assertEqual(canceled.remaining_quantity, 3)
        self.assertEqual(self.registry.open_order_id_count(), 0)

    def test_expired_orders_leave_the_map(self) -> None:
        with self.settings(MATCHER_ORDER_MAX_AGE_SECONDS=120):
            registry = OrderBookRegistry()
            book = registry.get(self.symbol)
        now = [0.0]
        book._clock = lambda: now[0]
        order = self.order(OrderSide.BUY, 1)
        registry.submit(order)
        self.assertEqual(registry.open_order_id_count(), 1)

        now[0] = 121.0
        book.snapshot()

        self.assertEqual(registry.open_order_id_count(), 0)
        with self.assertRaises(OrderNotFoundError):
            registry.cancel(order.order_id)
