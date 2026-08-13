from django.test import SimpleTestCase

from exchange.orderbook import BookLevel, BookSnapshot, OrderSide
from exchange.participants import (
    LiquidityProvider,
    MeanReversionTrader,
    MomentumTrader,
    NoiseTrader,
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
        }

        for strategy, expected_type in expected_types.items():
            self.assertIsInstance(build_trader(self.settings(strategy)), expected_type)
