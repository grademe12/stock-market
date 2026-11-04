import random

from django.test import SimpleTestCase

from exchange.orderbook import Order, OrderBook, OrderNotFoundError, OrderSide
from exchange.orderbook.book import _COMPACT_MIN_DEAD
from exchange.orderbook.reference_book import ReferenceOrderBook

SYMBOL = "005930"


def make_order(side: OrderSide, price: int, quantity: int, user_id: str = "u") -> Order:
    return Order(user_id=user_id, symbol=SYMBOL, side=side, price=price, quantity=quantity)


def trade_keys(result):
    # trade_id and executed_at are generated per call, so compare the economics.
    return tuple((t.price, t.quantity, t.buy_order_id, t.sell_order_id) for t in result.trades)


class DifferentialTests(SimpleTestCase):
    """Random orders and cancels must give the same results as the old list book."""

    def run_scenario(self, seed: int, steps: int) -> None:
        rng = random.Random(seed)
        reference = ReferenceOrderBook(symbol=SYMBOL)
        book = OrderBook(symbol=SYMBOL)
        known_ids = []

        for step in range(steps):
            if known_ids and rng.random() < 0.35:
                order_id = rng.choice(known_ids)
                try:
                    expected = reference.cancel(order_id)
                except OrderNotFoundError:
                    expected = None
                try:
                    actual = book.cancel(order_id)
                except OrderNotFoundError:
                    actual = None
                self.assertEqual(actual, expected, f"seed={seed} step={step} cancel")
            else:
                side = rng.choice((OrderSide.BUY, OrderSide.SELL))
                # Prices overlap around 70,000 so many orders cross.
                price = 70_000 + rng.randint(-6, 6) * 100
                order = make_order(side, price, rng.randint(1, 15), f"u{rng.randrange(50)}")
                expected = reference.submit(order)
                actual = book.submit(order)
                self.assertEqual(trade_keys(actual), trade_keys(expected), f"seed={seed} step={step}")
                self.assertEqual(actual.remaining_quantity, expected.remaining_quantity)
                known_ids.append(order.order_id)

            self.assertEqual(book.snapshot(), reference.snapshot(), f"seed={seed} step={step} snapshot")
            if step % 50 == 0:
                for side in OrderSide:
                    self.assertEqual(book.open_orders(side), reference.open_orders(side))
                probe = rng.choice(known_ids)
                self.assertEqual(book.get_open_order(probe), reference.get_open_order(probe))

        for side in OrderSide:
            self.assertEqual(book.open_orders(side), reference.open_orders(side))
            self.assertEqual(
                book.total_quantity(side),
                sum(o.remaining_quantity for o in reference.open_orders(side)),
            )

    def test_random_orders_and_cancels_match_reference(self) -> None:
        for seed in range(8):
            with self.subTest(seed=seed):
                self.run_scenario(seed, steps=1500)


class StructureTests(SimpleTestCase):
    def setUp(self) -> None:
        self.book = OrderBook(symbol=SYMBOL)

    def test_canceled_order_is_skipped_when_matching(self) -> None:
        first = make_order(OrderSide.SELL, 70_000, 5)
        second = make_order(OrderSide.SELL, 70_000, 5)
        self.book.submit(first)
        self.book.submit(second)
        self.book.cancel(first.order_id)

        result = self.book.submit(make_order(OrderSide.BUY, 70_000, 3))

        self.assertEqual(result.trades[0].sell_order_id, second.order_id)
        self.assertEqual(self.book.total_quantity(OrderSide.SELL), 2)

    def test_empty_price_level_is_removed_from_snapshot(self) -> None:
        order = make_order(OrderSide.BUY, 69_900, 4)
        self.book.submit(order)
        self.book.submit(make_order(OrderSide.BUY, 69_800, 1))

        self.book.cancel(order.order_id)

        self.assertEqual([level.price for level in self.book.snapshot().bids], [69_800])
        self.assertEqual(self.book.best_price(OrderSide.BUY), 69_800)

    def test_snapshot_lists_best_price_first_on_both_sides(self) -> None:
        for price in (69_700, 69_900, 69_800):
            self.book.submit(make_order(OrderSide.BUY, price, 1))
        for price in (70_300, 70_100, 70_200):
            self.book.submit(make_order(OrderSide.SELL, price, 1))

        snapshot = self.book.snapshot()

        self.assertEqual([level.price for level in snapshot.bids], [69_900, 69_800, 69_700])
        self.assertEqual([level.price for level in snapshot.asks], [70_100, 70_200, 70_300])

    def test_running_totals_follow_fills_and_cancels(self) -> None:
        resting = make_order(OrderSide.SELL, 70_000, 10)
        self.book.submit(resting)
        self.book.submit(make_order(OrderSide.BUY, 70_000, 4))
        self.assertEqual(self.book.total_quantity(OrderSide.SELL), 6)
        self.assertEqual(self.book.open_order_count(), 1)

        self.book.cancel(resting.order_id)

        self.assertEqual(self.book.total_quantity(OrderSide.SELL), 0)
        self.assertEqual(self.book.open_order_count(), 0)

    def test_many_cancels_behind_a_live_order_compact_the_queue(self) -> None:
        keeper = make_order(OrderSide.BUY, 69_000, 1)
        self.book.submit(keeper)
        canceled = [make_order(OrderSide.BUY, 69_000, 1) for _ in range(_COMPACT_MIN_DEAD * 3)]
        for order in canceled:
            self.book.submit(order)
        for order in canceled:
            self.book.cancel(order.order_id)

        level = self.book._sides[OrderSide.BUY].levels[69_000]
        self.assertLessEqual(len(level.queue), _COMPACT_MIN_DEAD * 2 + 1)
        self.assertEqual(level.quantity, 1)
        self.assertEqual(self.book.open_orders(OrderSide.BUY)[0].order, keeper)

    def test_callbacks_report_rest_and_fill(self) -> None:
        events = []
        book = OrderBook(
            symbol=SYMBOL,
            on_rest=lambda order_id: events.append(("rest", order_id)),
            on_close=lambda order_id, reason: events.append((reason, order_id)),
        )
        maker = make_order(OrderSide.SELL, 70_000, 2)
        taker = make_order(OrderSide.BUY, 70_000, 2)
        book.submit(maker)
        book.submit(taker)

        self.assertEqual(events, [("rest", maker.order_id), ("filled", maker.order_id)])


class ExpiryTests(SimpleTestCase):
    def setUp(self) -> None:
        self.now = 1000.0
        self.closed = []
        self.book = OrderBook(
            symbol=SYMBOL,
            max_age_seconds=120,
            clock=lambda: self.now,
            on_close=lambda order_id, reason: self.closed.append((reason, order_id)),
        )

    def test_order_older_than_max_age_is_dropped_on_next_call(self) -> None:
        old = make_order(OrderSide.BUY, 69_900, 5)
        self.book.submit(old)
        self.now += 60
        young = make_order(OrderSide.BUY, 69_900, 3)
        self.book.submit(young)

        self.now += 61  # old is 121s, young is 61s

        self.assertIsNone(self.book.get_open_order(old.order_id))
        self.assertIsNotNone(self.book.get_open_order(young.order_id))
        self.assertEqual(self.book.total_quantity(OrderSide.BUY), 3)
        self.assertEqual(self.book.expired_total, 1)
        self.assertEqual(self.closed, [("expired", old.order_id)])

    def test_expired_order_is_not_matched(self) -> None:
        old = make_order(OrderSide.SELL, 70_000, 5)
        self.book.submit(old)
        self.now += 121

        result = self.book.submit(make_order(OrderSide.BUY, 70_000, 5))

        self.assertEqual(result.trades, ())
        self.assertEqual(result.remaining_quantity, 5)

    def test_cancel_after_expiry_reports_not_found(self) -> None:
        old = make_order(OrderSide.SELL, 70_000, 5)
        self.book.submit(old)
        self.now += 121

        with self.assertRaises(OrderNotFoundError):
            self.book.cancel(old.order_id)

    def test_filled_or_canceled_orders_are_not_expired_again(self) -> None:
        canceled = make_order(OrderSide.SELL, 70_100, 5)
        filled = make_order(OrderSide.SELL, 70_000, 5)
        self.book.submit(canceled)
        self.book.submit(filled)
        self.book.cancel(canceled.order_id)
        self.book.submit(make_order(OrderSide.BUY, 70_000, 5))
        self.closed.clear()

        self.now += 500
        self.book.snapshot()

        self.assertEqual(self.book.expired_total, 0)
        self.assertEqual(self.closed, [])

    def test_expiry_is_disabled_by_default(self) -> None:
        book = OrderBook(symbol=SYMBOL, clock=lambda: self.now)
        order = make_order(OrderSide.BUY, 69_900, 1)
        book.submit(order)
        self.now += 10_000

        self.assertIsNotNone(book.get_open_order(order.order_id))
