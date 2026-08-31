from django.test import SimpleTestCase

from exchange.orderbook import Order, OrderBook, OrderNotFoundError, OrderSide


class OrderBookTests(SimpleTestCase):
    symbol = "005930"

    def setUp(self) -> None:
        self.book = OrderBook(symbol=self.symbol)

    def order(self, *, user_id: str, side: OrderSide, price: int, quantity: int) -> Order:
        return Order(
            user_id=user_id,
            symbol=self.symbol,
            side=side,
            price=price,
            quantity=quantity,
        )

    def test_non_crossing_order_rests_in_book(self) -> None:
        buy_order = self.order(user_id="alice", side=OrderSide.BUY, price=70_000, quantity=3)

        result = self.book.submit(buy_order)

        self.assertEqual(result.trades, ())
        self.assertEqual(result.remaining_quantity, 3)
        self.assertEqual(self.book.open_orders(OrderSide.BUY)[0].order, buy_order)

    def test_crossing_order_executes_at_resting_order_price(self) -> None:
        sell_order = self.order(user_id="alice", side=OrderSide.SELL, price=70_000, quantity=10)
        self.book.submit(sell_order)

        result = self.book.submit(
            self.order(user_id="bob", side=OrderSide.BUY, price=71_000, quantity=4)
        )

        self.assertEqual(result.remaining_quantity, 0)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].price, 70_000)
        self.assertEqual(result.trades[0].quantity, 4)
        self.assertIsNotNone(result.trades[0].executed_at.tzinfo)
        self.assertEqual(self.book.open_orders(OrderSide.SELL)[0].remaining_quantity, 6)

    def test_recent_trades_are_newest_first_and_bounded(self) -> None:
        book = OrderBook(symbol=self.symbol, recent_trade_capacity=2)

        for price in (70_000, 70_100, 70_200):
            book.submit(
                self.order(
                    user_id=f"seller-{price}",
                    side=OrderSide.SELL,
                    price=price,
                    quantity=1,
                )
            )
            book.submit(
                self.order(
                    user_id=f"buyer-{price}",
                    side=OrderSide.BUY,
                    price=price,
                    quantity=1,
                )
            )

        self.assertEqual([trade.price for trade in book.recent_trades(10)], [70_200, 70_100])

    def test_non_crossing_order_does_not_create_recent_trade(self) -> None:
        self.book.submit(
            self.order(user_id="alice", side=OrderSide.BUY, price=70_000, quantity=3)
        )

        self.assertEqual(self.book.recent_trades(50), ())

    def test_recent_trade_limit_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit must be at least 1"):
            self.book.recent_trades(0)

    def test_best_price_is_matched_before_an_older_worse_price(self) -> None:
        expensive_sell = self.order(user_id="alice", side=OrderSide.SELL, price=71_000, quantity=1)
        cheap_sell = self.order(user_id="bob", side=OrderSide.SELL, price=70_000, quantity=1)
        self.book.submit(expensive_sell)
        self.book.submit(cheap_sell)

        result = self.book.submit(
            self.order(user_id="carol", side=OrderSide.BUY, price=72_000, quantity=1)
        )

        self.assertEqual(result.trades[0].sell_order_id, cheap_sell.order_id)
        self.assertEqual(result.trades[0].price, 70_000)
        self.assertEqual(self.book.open_orders(OrderSide.SELL)[0].order, expensive_sell)

    def test_same_price_orders_are_matched_in_arrival_order(self) -> None:
        first_sell = self.order(user_id="alice", side=OrderSide.SELL, price=70_000, quantity=3)
        second_sell = self.order(user_id="bob", side=OrderSide.SELL, price=70_000, quantity=5)
        self.book.submit(first_sell)
        self.book.submit(second_sell)

        result = self.book.submit(
            self.order(user_id="carol", side=OrderSide.BUY, price=70_000, quantity=5)
        )

        self.assertEqual([trade.sell_order_id for trade in result.trades], [first_sell.order_id, second_sell.order_id])
        self.assertEqual([trade.quantity for trade in result.trades], [3, 2])
        self.assertEqual(self.book.open_orders(OrderSide.SELL)[0].remaining_quantity, 3)

    def test_partially_filled_incoming_order_rests_with_remaining_quantity(self) -> None:
        self.book.submit(
            self.order(user_id="alice", side=OrderSide.SELL, price=70_000, quantity=5)
        )

        result = self.book.submit(
            self.order(user_id="bob", side=OrderSide.BUY, price=70_000, quantity=8)
        )

        self.assertEqual(result.trades[0].quantity, 5)
        self.assertEqual(result.remaining_quantity, 3)
        self.assertEqual(self.book.open_orders(OrderSide.BUY)[0].remaining_quantity, 3)

    def test_order_for_another_symbol_is_rejected(self) -> None:
        another_symbol_order = Order(
            user_id="alice",
            symbol="035420",
            side=OrderSide.BUY,
            price=70_000,
            quantity=1,
        )

        with self.assertRaisesRegex(ValueError, "order symbol"):
            self.book.submit(another_symbol_order)

    def test_cancel_removes_resting_order(self) -> None:
        buy_order = self.order(user_id="alice", side=OrderSide.BUY, price=70_000, quantity=3)
        self.book.submit(buy_order)

        canceled_order = self.book.cancel(buy_order.order_id)

        self.assertEqual(canceled_order.order, buy_order)
        self.assertEqual(canceled_order.remaining_quantity, 3)
        self.assertEqual(self.book.open_orders(OrderSide.BUY), ())

    def test_cancel_rejects_order_that_is_not_resting(self) -> None:
        with self.assertRaises(OrderNotFoundError):
            self.book.cancel(self.order(user_id="alice", side=OrderSide.BUY, price=70_000, quantity=1).order_id)

    def test_get_open_order_returns_none_after_cancel(self) -> None:
        buy_order = self.order(user_id="alice", side=OrderSide.BUY, price=70_000, quantity=3)
        self.book.submit(buy_order)

        self.assertEqual(self.book.get_open_order(buy_order.order_id).order, buy_order)
        self.book.cancel(buy_order.order_id)

        self.assertIsNone(self.book.get_open_order(buy_order.order_id))

    def test_snapshot_aggregates_orders_at_same_price_level(self) -> None:
        self.book.submit(self.order(user_id="alice", side=OrderSide.BUY, price=70_000, quantity=3))
        self.book.submit(self.order(user_id="bob", side=OrderSide.BUY, price=70_000, quantity=5))
        self.book.submit(self.order(user_id="carol", side=OrderSide.BUY, price=69_000, quantity=2))

        snapshot = self.book.snapshot()

        self.assertEqual([(level.price, level.quantity) for level in snapshot.bids], [(70_000, 8), (69_000, 2)])
        self.assertEqual(snapshot.asks, ())

    def test_invalid_order_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            Order(user_id="alice", symbol=self.symbol, side=OrderSide.BUY, price=0, quantity=1)

        with self.assertRaisesRegex(ValueError, "positive integer"):
            Order(user_id="alice", symbol=self.symbol, side=OrderSide.BUY, price=70_000, quantity=0)
