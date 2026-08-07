from unittest import TestCase

from exchange.orderbook import OrderSide
from exchange.participants.types import OrderIntent

from participant_runner.client import CancellationResult, SubmittedOrder
from participant_runner.profiles import build_participants
from participant_runner.runner import ParticipantRunner, run_until_stopped


class StaticParticipant:
    def __init__(self, intent: OrderIntent) -> None:
        self.intent = intent

    def next_intent(self, tick: int) -> OrderIntent:
        return self.intent


class FakeBackendClient:
    def __init__(self) -> None:
        self.submissions: list[OrderIntent] = []
        self.canceled_order_ids: list[str] = []
        self.closed_order_ids: set[str] = set()

    def submit_order(self, intent: OrderIntent) -> SubmittedOrder:
        self.submissions.append(intent)
        return SubmittedOrder(order_id=f"order-{len(self.submissions)}", remaining_quantity=1)

    def cancel_order(self, order_id: str) -> CancellationResult:
        if order_id in self.closed_order_ids:
            return CancellationResult(status="ALREADY_CLOSED")
        self.canceled_order_ids.append(order_id)
        return CancellationResult(status="CANCELED")


class StopAfterFirstWait:
    def __init__(self) -> None:
        self._stopped = False

    def is_set(self) -> bool:
        return self._stopped

    def wait(self, timeout: float) -> bool:
        self._stopped = True
        return True


class ParticipantRunnerTests(TestCase):
    def test_runner_submits_and_expires_orders_over_http_client_port(self) -> None:
        client = FakeBackendClient()
        runner = ParticipantRunner(
            client,
            (
                StaticParticipant(
                    OrderIntent(
                        user_id="external-noise-1",
                        symbol="005930",
                        side=OrderSide.BUY,
                        price=70_000,
                        quantity=1,
                        order_ttl_ticks=1,
                    )
                ),
            ),
        )

        runner.tick_once()
        status = runner.tick_once()

        self.assertEqual(len(client.submissions), 2)
        self.assertEqual(client.canceled_order_ids, ["order-1"])
        self.assertEqual(status.orders_canceled_total, 1)
        self.assertEqual(status.open_runner_orders, 1)

    def test_closed_orders_are_not_reported_as_failures(self) -> None:
        client = FakeBackendClient()
        client.closed_order_ids.add("order-1")
        runner = ParticipantRunner(
            client,
            (
                StaticParticipant(
                    OrderIntent(
                        user_id="external-noise-1",
                        symbol="005930",
                        side=OrderSide.BUY,
                        price=70_000,
                        quantity=1,
                        order_ttl_ticks=1,
                    )
                ),
            ),
        )

        runner.tick_once()
        status = runner.tick_once()

        self.assertEqual(status.orders_already_closed_total, 1)
        self.assertEqual(status.request_failures_total, 0)

    def test_profile_selection_respects_enabled_ids_and_maximum(self) -> None:
        profiles = [
            {
                "id": "first",
                "enabled": True,
                "user_id": "noise-1",
                "symbol": "005930",
                "strategy": "noise",
                "reference_price": 70_000,
                "price_step": 100,
                "max_offset_steps": 1,
                "quantity_min": 1,
                "quantity_max": 2,
                "order_ttl_ticks": 2,
                "interval_ticks": 1,
                "seed": 1,
            },
            {
                "id": "second",
                "enabled": True,
                "user_id": "noise-2",
                "symbol": "005930",
                "strategy": "noise",
                "reference_price": 70_000,
                "price_step": 100,
                "max_offset_steps": 1,
                "quantity_min": 1,
                "quantity_max": 2,
                "order_ttl_ticks": 2,
                "interval_ticks": 1,
                "seed": 2,
            },
            {"id": "paused", "enabled": False},
        ]

        participants = build_participants(profiles, max_traders=1)

        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0].user_id, "noise-1")

    def test_runner_emits_periodic_status_and_cleans_up_on_stop(self) -> None:
        client = FakeBackendClient()
        runner = ParticipantRunner(
            client,
            (
                StaticParticipant(
                    OrderIntent(
                        user_id="external-noise-1",
                        symbol="005930",
                        side=OrderSide.BUY,
                        price=70_000,
                        quantity=1,
                        order_ttl_ticks=2,
                    )
                ),
            ),
        )

        with self.assertLogs(level="INFO") as logs:
            status = run_until_stopped(
                runner,
                tick_interval_ms=1_000,
                status_log_interval_ticks=1,
                stop_event=StopAfterFirstWait(),
            )

        self.assertIn("event=runner_status", logs.output[0])
        self.assertEqual(status.orders_canceled_total, 1)
        self.assertEqual(status.open_runner_orders, 0)
