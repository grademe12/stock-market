from django.test import SimpleTestCase

from exchange.orderbook import OrderBook, OrderSide
from exchange.participants.adapters import InMemoryOrderBookAdapter
from exchange.participants.orchestrator import ParticipantOrchestrator
from exchange.participants.traders import NoiseTrader, build_noise_traders
from exchange.participants.types import OrderIntent, SimulationConfig, TraderSettings


class StaticParticipant:
    def __init__(self, intent: OrderIntent) -> None:
        self._intent = intent

    def next_intent(self, tick: int) -> OrderIntent:
        return self._intent


class ParticipantOrchestratorTests(SimpleTestCase):
    symbol = "005930"

    def config(self, **overrides) -> SimulationConfig:
        values = {
            "symbol": self.symbol,
            "participants": 2,
            "reference_price": 70_000,
            "price_step": 100,
            "max_offset_steps": 2,
            "quantity_min": 1,
            "quantity_max": 2,
            "order_ttl_ticks": 2,
            "seed": 42,
        }
        values.update(overrides)
        return SimulationConfig(**values)

    def test_noise_traders_generate_the_same_intents_for_the_same_seed(self) -> None:
        config = self.config()
        first_run = build_noise_traders(config)
        second_run = build_noise_traders(config)

        first_intents = [trader.next_intent(1) for trader in first_run]
        second_intents = [trader.next_intent(1) for trader in second_run]

        self.assertEqual(first_intents, second_intents)

    def test_noise_trader_obeys_its_individual_interval(self) -> None:
        trader = NoiseTrader(
            TraderSettings(
                user_id="noise-slow",
                symbol=self.symbol,
                strategy="noise",
                reference_price=70_000,
                price_step=100,
                max_offset_steps=1,
                quantity_min=1,
                quantity_max=1,
                order_ttl_ticks=2,
                interval_ticks=2,
                seed=42,
            )
        )

        self.assertIsNone(trader.next_intent(1))
        self.assertIsNotNone(trader.next_intent(2))

    def test_expired_open_order_is_canceled_before_the_next_tick(self) -> None:
        config = self.config(participants=1, order_ttl_ticks=1)
        book = OrderBook(symbol=self.symbol)
        intent = OrderIntent(
            user_id="noise-001",
            symbol=self.symbol,
            side=OrderSide.BUY,
            price=70_000,
            quantity=1,
        )
        orchestrator = ParticipantOrchestrator(
            config,
            InMemoryOrderBookAdapter(lambda: book),
            participants=(StaticParticipant(intent),),
        )

        orchestrator.tick()
        status = orchestrator.tick()

        self.assertEqual(status.orders_submitted_total, 2)
        self.assertEqual(status.orders_canceled_total, 1)
        self.assertEqual(status.open_bot_orders, 1)

    def test_opposing_participants_generate_a_trade(self) -> None:
        config = self.config()
        book = OrderBook(symbol=self.symbol)
        buy_intent = OrderIntent(
            user_id="noise-buy",
            symbol=self.symbol,
            side=OrderSide.BUY,
            price=70_100,
            quantity=1,
        )
        sell_intent = OrderIntent(
            user_id="noise-sell",
            symbol=self.symbol,
            side=OrderSide.SELL,
            price=70_000,
            quantity=1,
        )
        orchestrator = ParticipantOrchestrator(
            config,
            InMemoryOrderBookAdapter(lambda: book),
            participants=(StaticParticipant(buy_intent), StaticParticipant(sell_intent)),
        )

        status = orchestrator.tick()

        self.assertEqual(status.orders_submitted_total, 2)
        self.assertEqual(status.trades_generated_total, 1)
        self.assertEqual(status.open_bot_orders, 0)

    def test_cancel_all_open_orders_removes_bot_liquidity(self) -> None:
        config = self.config(participants=1)
        book = OrderBook(symbol=self.symbol)
        intent = OrderIntent(
            user_id="noise-001",
            symbol=self.symbol,
            side=OrderSide.BUY,
            price=70_000,
            quantity=1,
        )
        orchestrator = ParticipantOrchestrator(
            config,
            InMemoryOrderBookAdapter(lambda: book),
            participants=(StaticParticipant(intent),),
        )
        orchestrator.tick()

        orchestrator.cancel_all_open_orders()

        self.assertEqual(orchestrator.status().open_bot_orders, 0)
        self.assertEqual(book.open_orders(OrderSide.BUY), ())
