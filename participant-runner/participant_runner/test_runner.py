from threading import Lock
from time import sleep
from unittest import TestCase

from exchange.orderbook import BookLevel, BookSnapshot, OrderSide
from exchange.participants import LiquidityProvider, OrderIntent, TraderSettings

from participant_runner.client import BackendApiError, CancellationResult, SubmittedOrder
from participant_runner.profiles import build_participants
from participant_runner.runner import ParticipantRunner, run_until_stopped


class StaticParticipant:
    user_id = "external-static-1"
    symbol = "005930"

    def __init__(self, intents: tuple[OrderIntent, ...]) -> None:
        self.intents = intents

    def next_intents(
        self,
        tick: int,
        snapshot: BookSnapshot,
    ) -> tuple[OrderIntent, ...]:
        return self.intents


class FakeBackendClient:
    def __init__(self) -> None:
        self.submissions: list[OrderIntent] = []
        self.canceled_order_ids: list[str] = []
        self.closed_order_ids: set[str] = set()
        self.book_requests: list[str] = []
        self.book_error: BackendApiError | None = None
        self._lock = Lock()
        self._next_order = 0

    def fetch_book(self, symbol: str) -> BookSnapshot:
        with self._lock:
            self.book_requests.append(symbol)
        if self.book_error is not None:
            raise self.book_error
        return BookSnapshot(
            symbol=symbol,
            bids=(BookLevel(price=69_900, quantity=10),),
            asks=(BookLevel(price=70_100, quantity=10),),
        )

    def submit_order(self, intent: OrderIntent) -> SubmittedOrder:
        with self._lock:
            self.submissions.append(intent)
            self._next_order += 1
            order_id = f"order-{self._next_order}"
        return SubmittedOrder(order_id=order_id, remaining_quantity=1)

    def cancel_order(self, order_id: str) -> CancellationResult:
        if order_id in self.closed_order_ids:
            return CancellationResult(status="ALREADY_CLOSED")
        with self._lock:
            self.canceled_order_ids.append(order_id)
        return CancellationResult(status="CANCELED")


class ConcurrentBackendClient(FakeBackendClient):
    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0

    def submit_order(self, intent: OrderIntent) -> SubmittedOrder:
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            sleep(0.05)
            return super().submit_order(intent)
        finally:
            with self._lock:
                self.in_flight -= 1


class StopAfterFirstWait:
    def __init__(self) -> None:
        self._stopped = False

    def is_set(self) -> bool:
        return self._stopped

    def wait(self, timeout: float) -> bool:
        self._stopped = True
        return True


def buy_intent(ttl: int = 1) -> OrderIntent:
    return OrderIntent(
        user_id="external-static-1",
        symbol="005930",
        side=OrderSide.BUY,
        price=70_000,
        quantity=1,
        order_ttl_ticks=ttl,
    )


class ParticipantRunnerTests(TestCase):
    def test_runner_submits_and_expires_orders_over_http_client_port(self) -> None:
        client = FakeBackendClient()
        runner = ParticipantRunner(client, (StaticParticipant((buy_intent(),)),))

        runner.tick_once()
        status = runner.tick_once()

        self.assertEqual(len(client.submissions), 2)
        self.assertEqual(client.canceled_order_ids, ["order-1"])
        self.assertEqual(status.orders_canceled_total, 1)
        self.assertEqual(status.open_runner_orders, 1)

    def test_runner_fetches_one_snapshot_per_symbol_and_supports_two_quotes(self) -> None:
        client = FakeBackendClient()
        settings = TraderSettings(
            user_id="lp-1",
            symbol="005930",
            strategy="liquidity_provider",
            reference_price=70_000,
            price_step=100,
            max_offset_steps=5,
            quantity_min=1,
            quantity_max=1,
            order_ttl_ticks=2,
            interval_ticks=1,
            seed=42,
        )
        runner = ParticipantRunner(
            client,
            (LiquidityProvider(settings), LiquidityProvider(settings)),
        )

        status = runner.tick_once()

        self.assertEqual(client.book_requests, ["005930"])
        self.assertEqual(status.orders_submitted_total, 4)

    def test_book_failure_skips_orders_and_is_reported(self) -> None:
        client = FakeBackendClient()
        client.book_error = BackendApiError(503, "unavailable")
        runner = ParticipantRunner(client, (StaticParticipant((buy_intent(),)),))

        status = runner.tick_once()

        self.assertEqual(client.submissions, [])
        self.assertEqual(status.request_failures_total, 1)

    def test_closed_orders_are_not_reported_as_failures(self) -> None:
        client = FakeBackendClient()
        client.closed_order_ids.add("order-1")
        runner = ParticipantRunner(client, (StaticParticipant((buy_intent(),)),))

        runner.tick_once()
        status = runner.tick_once()

        self.assertEqual(status.orders_already_closed_total, 1)
        self.assertEqual(status.request_failures_total, 0)

    def test_profile_selection_builds_all_strategies(self) -> None:
        profiles = []
        for index, strategy in enumerate(
            (
                "noise",
                "momentum",
                "mean_reversion",
                "liquidity_provider",
                "event_reactive",
            ),
            start=1,
        ):
            profiles.append(
                {
                    "id": str(index),
                    "enabled": True,
                    "user_id": f"{strategy}-{index}",
                    "symbol": "005930",
                    "strategy": strategy,
                    "reference_price": 70_000,
                    "price_step": 100,
                    "max_offset_steps": 1,
                    "quantity_min": 1,
                    "quantity_max": 2,
                    "order_ttl_ticks": 2,
                    "interval_ticks": 1,
                    "seed": index,
                }
            )

        participants = build_participants(profiles)

        self.assertEqual(len(participants), 5)
        self.assertEqual([participant.user_id for participant in participants], [
            "noise-1",
            "momentum-2",
            "mean_reversion-3",
            "liquidity_provider-4",
            "event_reactive-5",
        ])

        filtered = build_participants(
            profiles,
            trader_strategies=("momentum", "liquidity_provider"),
        )

        self.assertEqual(
            [participant.user_id for participant in filtered],
            ["momentum-2", "liquidity_provider-4"],
        )

    def test_runner_emits_periodic_status_and_cleans_up_on_stop(self) -> None:
        client = FakeBackendClient()
        runner = ParticipantRunner(client, (StaticParticipant((buy_intent(ttl=2),)),))

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

    def test_http_concurrency_caps_in_flight_submits(self) -> None:
        client = ConcurrentBackendClient()
        intents = tuple(buy_intent() for _ in range(8))
        runner = ParticipantRunner(
            client,
            (StaticParticipant(intents),),
            http_concurrency=4,
        )

        status = runner.tick_once()

        self.assertEqual(status.orders_submitted_total, 8)
        self.assertEqual(len(client.submissions), 8)
        self.assertEqual(client.max_in_flight, 4)

    def test_serial_http_concurrency_keeps_one_in_flight(self) -> None:
        client = ConcurrentBackendClient()
        intents = tuple(buy_intent() for _ in range(3))
        runner = ParticipantRunner(
            client,
            (StaticParticipant(intents),),
            http_concurrency=1,
        )

        runner.tick_once()

        self.assertEqual(client.max_in_flight, 1)
