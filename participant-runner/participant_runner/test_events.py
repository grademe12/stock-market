from unittest import TestCase

from exchange.participants import EventPreset, EventReactiveTrader, NewsShockEvent, TraderSettings

from participant_runner.coordinator import EventCoordinator, FakeClock
from participant_runner.runner import ParticipantRunner
from participant_runner.test_runner import FakeBackendClient, StaticParticipant, buy_intent


def event_settings(user_id: str = "event_reactive-1") -> TraderSettings:
    return TraderSettings(
        user_id=user_id,
        symbol="005930",
        strategy="event_reactive",
        reference_price=70_000,
        price_step=100,
        max_offset_steps=5,
        quantity_min=1,
        quantity_max=1,
        order_ttl_ticks=3,
        interval_ticks=1,
        seed=42,
    )


def shock_event(**overrides) -> NewsShockEvent:
    values = {
        "event_id": "shock-001",
        "symbol": "005930",
        "starts_after_ms": 200,
        "preset": EventPreset.BREAKING_NEWS,
        "seed": 42,
    }
    values.update(overrides)
    return NewsShockEvent(**values)


class EventCoordinatorRunnerTests(TestCase):
    def test_baseline_continues_while_event_traders_wait_then_spike(self) -> None:
        client = FakeBackendClient()
        clock = FakeClock()
        event_trader = EventReactiveTrader(event_settings())
        baseline = StaticParticipant((buy_intent(),))
        coordinator = EventCoordinator(
            (shock_event(),),
            (baseline, event_trader),
            tick_interval_ms=100,
            clock=clock,
        )
        runner = ParticipantRunner(
            client,
            (baseline, event_trader),
            coordinator=coordinator,
        )

        clock.advance(100)
        first = runner.tick_once()
        event_orders_before = [
            intent for intent in client.submissions if intent.user_id == event_trader.user_id
        ]

        clock.advance(100)
        with self.assertLogs(level="INFO") as logs:
            second = runner.tick_once()
        event_orders_after = [
            intent for intent in client.submissions if intent.user_id == event_trader.user_id
        ]

        remaining_ticks = 0
        while event_trader.remaining_reaction_orders and remaining_ticks < 400:
            clock.advance(100)
            runner.tick_once()
            remaining_ticks += 1
        after_complete = [
            intent for intent in client.submissions if intent.user_id == event_trader.user_id
        ]
        clock.advance(100)
        runner.tick_once()
        after_baseline = [
            intent for intent in client.submissions if intent.user_id == event_trader.user_id
        ]

        self.assertEqual(event_orders_before, [])
        self.assertEqual(first.orders_submitted_total, 1)
        self.assertEqual(first.events_received_total, 0)
        self.assertEqual(second.events_received_total, 1)
        self.assertGreater(len(after_complete), 0)
        self.assertEqual(after_baseline, after_complete)
        self.assertIn("event=news_received", "\n".join(logs.output))
        self.assertIn("event=news_activated", "\n".join(logs.output))
        self.assertTrue(
            any(intent.user_id == baseline.user_id for intent in client.submissions)
        )
        self.assertGreater(runner.status().reactions_planned_total, 0)
        self.assertEqual(
            runner.status().reactions_submitted_total + runner.status().reactions_dropped_total,
            runner.status().reactions_planned_total,
        )

    def test_late_reaction_orders_are_dropped_and_baseline_still_submits(self) -> None:
        client = FakeBackendClient()
        clock = FakeClock()
        event_trader = EventReactiveTrader(event_settings())
        baseline = StaticParticipant((buy_intent(),))
        coordinator = EventCoordinator(
            (shock_event(),),
            (event_trader, baseline),
            tick_interval_ms=100,
            clock=clock,
        )
        runner = ParticipantRunner(
            client,
            (baseline, event_trader),
            coordinator=coordinator,
        )

        clock.advance(30_000)
        with self.assertLogs(level="INFO") as logs:
            status = runner.tick_once()

        event_orders = [
            intent for intent in client.submissions if intent.user_id == event_trader.user_id
        ]
        self.assertEqual(event_orders, [])
        self.assertGreater(status.reactions_dropped_total, 0)
        self.assertEqual(status.orders_submitted_total, 1)
        self.assertIn("event=news_completed", "\n".join(logs.output))

    def test_event_failure_does_not_stop_baseline_traders(self) -> None:
        client = FakeBackendClient()
        coordinator = EventCoordinator(
            (shock_event(),),
            (),
            tick_interval_ms=100,
            clock=FakeClock(),
        )
        coordinator.before_tick = lambda tick: (_ for _ in ()).throw(RuntimeError("boom"))
        runner = ParticipantRunner(
            client,
            (StaticParticipant((buy_intent(),)),),
            coordinator=coordinator,
        )

        with self.assertLogs(level="ERROR") as logs:
            status = runner.tick_once()

        self.assertEqual(status.orders_submitted_total, 1)
        self.assertIn("event coordinator failed", "\n".join(logs.output))
