from django.test import SimpleTestCase

from exchange.orderbook import BookLevel, BookSnapshot, OrderSide
from exchange.participants import (
    EventReactiveTrader,
    LiquidityProvider,
    MeanReversionTrader,
    MomentumTrader,
    NoiseTrader,
    ResolvedReactionPlan,
    TraderSettings,
    build_trader,
)


class TraderStrategyTests(SimpleTestCase):
    symbol = "005930"

    def settings(self, strategy: str, **overrides) -> TraderSettings:
        values = {
            "user_id": f"{strategy}-1",
            "symbol": self.symbol,
            "strategy": strategy,
            "reference_price": 70_000,
            "price_step": 100,
            "max_offset_steps": 5,
            "quantity_min": 1,
            "quantity_max": 1,
            "order_ttl_ticks": 3,
            "interval_ticks": 1,
            "seed": 42,
        }
        values.update(overrides)
        return TraderSettings(**values)

    def snapshot(
        self,
        bid: int | None = None,
        ask: int | None = None,
    ) -> BookSnapshot:
        return BookSnapshot(
            symbol=self.symbol,
            bids=(BookLevel(bid, 10),) if bid is not None else (),
            asks=(BookLevel(ask, 10),) if ask is not None else (),
        )

    def test_noise_trader_is_reproducible_and_obeys_interval(self) -> None:
        settings = self.settings("noise", interval_ticks=2)
        first = NoiseTrader(settings)
        second = NoiseTrader(settings)
        snapshot = self.snapshot()

        self.assertEqual(first.next_intents(1, snapshot), ())
        self.assertEqual(first.next_intents(2, snapshot), second.next_intents(2, snapshot))

    def test_momentum_trader_follows_midpoint_direction(self) -> None:
        trader = MomentumTrader(self.settings("momentum"))

        self.assertEqual(trader.next_intents(1, self.snapshot(69_900, 70_100)), ())
        rising = trader.next_intents(2, self.snapshot(70_100, 70_300))
        falling = trader.next_intents(3, self.snapshot(69_700, 69_900))

        self.assertEqual((rising[0].side, rising[0].price), (OrderSide.BUY, 70_300))
        self.assertEqual((falling[0].side, falling[0].price), (OrderSide.SELL, 69_700))

    def test_mean_reversion_trader_trades_toward_reference_price(self) -> None:
        trader = MeanReversionTrader(self.settings("mean_reversion"))

        below = trader.next_intents(1, self.snapshot(69_700, 69_900))
        above = trader.next_intents(2, self.snapshot(70_100, 70_300))
        neutral = trader.next_intents(3, self.snapshot(69_950, 70_050))

        self.assertEqual((below[0].side, below[0].price), (OrderSide.BUY, 69_900))
        self.assertEqual((above[0].side, above[0].price), (OrderSide.SELL, 70_100))
        self.assertEqual(neutral, ())

    def test_liquidity_provider_quotes_both_sides(self) -> None:
        trader = LiquidityProvider(self.settings("liquidity_provider"))

        intents = trader.next_intents(1, self.snapshot(69_900, 70_100))

        self.assertEqual(
            [(intent.side, intent.price) for intent in intents],
            [(OrderSide.BUY, 69_900), (OrderSide.SELL, 70_100)],
        )

    def test_liquidity_provider_center_is_limited_around_reference(self) -> None:
        trader = LiquidityProvider(
            self.settings("liquidity_provider", max_offset_steps=0)
        )

        intents = trader.next_intents(1, self.snapshot(71_900, 72_100))

        self.assertEqual([intent.price for intent in intents], [69_900, 70_100])

    def test_factory_builds_every_supported_strategy(self) -> None:
        expected_types = {
            "noise": NoiseTrader,
            "momentum": MomentumTrader,
            "mean_reversion": MeanReversionTrader,
            "liquidity_provider": LiquidityProvider,
            "event_reactive": EventReactiveTrader,
        }

        for strategy, expected_type in expected_types.items():
            self.assertIsInstance(build_trader(self.settings(strategy)), expected_type)


class EventReactiveTraderTests(SimpleTestCase):
    symbol = "005930"

    def settings(self, **overrides) -> TraderSettings:
        values = {
            "user_id": "event_reactive-1",
            "symbol": self.symbol,
            "strategy": "event_reactive",
            "reference_price": 70_000,
            "price_step": 100,
            "max_offset_steps": 5,
            "quantity_min": 1,
            "quantity_max": 10,
            "order_ttl_ticks": 3,
            "interval_ticks": 1,
            "seed": 42,
        }
        values.update(overrides)
        return TraderSettings(**values)

    def snapshot(
        self,
        bid: int | None = None,
        ask: int | None = None,
    ) -> BookSnapshot:
        return BookSnapshot(
            symbol=self.symbol,
            bids=(BookLevel(bid, 10),) if bid is not None else (),
            asks=(BookLevel(ask, 10),) if ask is not None else (),
        )

    def plan(self, **overrides) -> ResolvedReactionPlan:
        values = {
            "user_id": "event_reactive-1",
            "symbol": self.symbol,
            "activated": True,
            "reaction_after_ms": 500,
            "order_interval_ticks": 2,
            "buy_probability_bps": 5_000,
            "sides": (OrderSide.BUY, OrderSide.SELL),
            "quantities": (3, 4),
            "ttl_ticks": (5, 6),
            "order_tick_offsets": (5, 7),
        }
        values.update(overrides)
        return ResolvedReactionPlan(**values)

    def test_trader_stays_dormant_until_an_activated_plan_is_due(self) -> None:
        trader = EventReactiveTrader(self.settings())
        snapshot = self.snapshot(69_900, 70_100)

        self.assertEqual(trader.next_intents(5, snapshot), ())

        trader.apply_plan(
            self.plan(
                activated=False,
                reaction_after_ms=None,
                sides=(),
                quantities=(),
                ttl_ticks=(),
                order_tick_offsets=(),
            )
        )
        self.assertEqual(trader.next_intents(5, snapshot), ())

        trader.apply_plan(self.plan())
        before = trader.next_intents(4, snapshot)
        first = trader.next_intents(5, snapshot)
        between = trader.next_intents(6, snapshot)
        second = trader.next_intents(7, snapshot)
        after = trader.next_intents(8, snapshot)

        self.assertEqual(before, ())
        self.assertEqual(
            (first[0].side, first[0].price, first[0].quantity, first[0].order_ttl_ticks),
            (OrderSide.BUY, 70_100, 3, 5),
        )
        self.assertEqual(between, ())
        self.assertEqual(
            (second[0].side, second[0].price, second[0].quantity, second[0].order_ttl_ticks),
            (OrderSide.SELL, 69_900, 4, 6),
        )
        self.assertEqual(after, ())

    def test_empty_and_one_sided_books_use_reference_price_fallback(self) -> None:
        trader = EventReactiveTrader(self.settings())
        trader.apply_plan(self.plan(sides=(OrderSide.BUY,), quantities=(1,), ttl_ticks=(3,), order_tick_offsets=(1,)))
        empty_buy = trader.next_intents(1, self.snapshot())
        bid_only_buy = trader.next_intents(1, self.snapshot(bid=69_900))

        trader.apply_plan(self.plan(sides=(OrderSide.SELL,), quantities=(1,), ttl_ticks=(3,), order_tick_offsets=(1,)))
        empty_sell = trader.next_intents(1, self.snapshot())
        ask_only_sell = trader.next_intents(1, self.snapshot(ask=70_100))

        self.assertEqual(empty_buy[0].price, 70_100)
        self.assertEqual(bid_only_buy[0].price, 70_100)
        self.assertEqual(empty_sell[0].price, 69_900)
        self.assertEqual(ask_only_sell[0].price, 69_900)

    def test_fallback_sell_price_is_clamped_to_the_price_step(self) -> None:
        trader = EventReactiveTrader(self.settings(reference_price=100, price_step=100))
        trader.apply_plan(self.plan(sides=(OrderSide.SELL,), quantities=(1,), ttl_ticks=(3,), order_tick_offsets=(1,)))

        sell = trader.next_intents(1, self.snapshot())

        self.assertEqual(sell[0].price, 100)

    def test_apply_plan_rejects_a_plan_for_another_trader(self) -> None:
        trader = EventReactiveTrader(self.settings())

        with self.assertRaisesMessage(ValueError, "user_id"):
            trader.apply_plan(self.plan(user_id="other-trader"))
        with self.assertRaisesMessage(ValueError, "symbol"):
            trader.apply_plan(self.plan(symbol="000660"))
