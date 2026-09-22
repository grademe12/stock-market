from datetime import datetime, timedelta
from threading import Event, Lock
from time import sleep
from unittest import TestCase

from exchange.market_session import MarketSession
from exchange.orderbook import BookLevel, BookSnapshot, OrderSide
from exchange.participants import LiquidityProvider, OrderIntent, TraderSettings

from participant_runner.client import (
    BackendApiError,
    CancellationResult,
    ShardedBackendClient,
    SubmittedOrder,
)
from participant_runner.coordinator import FakeClock
from participant_runner.profiles import InvalidTraderProfileError, build_participants
from participant_runner.runner import ParticipantRunner, RunnerStatus, run_until_stopped


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

    def cancel_order(self, order_id: str, symbol: str = "") -> CancellationResult:
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


class FakeWallClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class AdvancingStopEvent:
    def __init__(self, clock: FakeWallClock, *, stop_after_waits: int) -> None:
        self.clock = clock
        self.stop_after_waits = stop_after_waits
        self.wait_timeouts: list[float] = []
        self._stopped = False

    def is_set(self) -> bool:
        return self._stopped

    def wait(self, timeout: float) -> bool:
        self.wait_timeouts.append(timeout)
        self.clock.advance(timeout)
        if len(self.wait_timeouts) >= self.stop_after_waits:
            self._stopped = True
            return True
        return False


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
        order_ttl_seconds=ttl,
    )


class ParticipantRunnerTests(TestCase):
    def start_runner(self, *args, **kwargs) -> ParticipantRunner:
        runner = ParticipantRunner(*args, **kwargs)
        self.addCleanup(runner.close)
        return runner

    def finish_tick(self, runner: ParticipantRunner) -> RunnerStatus:
        runner.tick_once()
        runner.wait_for_idle()
        return runner.status()

    def test_runner_submits_and_expires_orders_over_http_client_port(self) -> None:
        client = FakeBackendClient()
        clock = FakeClock(0)
        runner = self.start_runner(client, (StaticParticipant((buy_intent(),)),), clock=clock)

        self.finish_tick(runner)
        clock.advance(1_000)
        status = self.finish_tick(runner)

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
            order_ttl_seconds=2,
            interval_seconds=1,
            seed=42,
        )
        runner = self.start_runner(
            client,
            (LiquidityProvider(settings), LiquidityProvider(settings)),
        )

        status = self.finish_tick(runner)

        self.assertEqual(client.book_requests, ["005930"])
        self.assertEqual(status.orders_submitted_total, 4)

    def test_book_failure_skips_orders_and_is_reported(self) -> None:
        client = FakeBackendClient()
        client.book_error = BackendApiError(503, "unavailable")
        runner = self.start_runner(client, (StaticParticipant((buy_intent(),)),))

        status = self.finish_tick(runner)

        self.assertEqual(client.submissions, [])
        self.assertEqual(status.request_failures_total, 1)

    def test_closed_orders_are_not_reported_as_failures(self) -> None:
        client = FakeBackendClient()
        client.closed_order_ids.add("order-1")
        clock = FakeClock(0)
        runner = self.start_runner(client, (StaticParticipant((buy_intent(),)),), clock=clock)

        self.finish_tick(runner)
        clock.advance(1_000)
        status = self.finish_tick(runner)

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
                    "order_ttl_seconds": 2,
                    "interval_seconds": 1,
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

    def test_profile_selection_keeps_one_matcher_shard_before_max_traders(self) -> None:
        profiles = [
            {
                "id": "1",
                "enabled": True,
                "user_id": "noise-hynix",
                "symbol": "000660",
                "strategy": "noise",
                "reference_price": 250_000,
                "price_step": 100,
                "max_offset_steps": 1,
                "quantity_min": 1,
                "quantity_max": 2,
                "order_ttl_seconds": 2,
                "interval_seconds": 1,
                "seed": 1,
            },
            {
                "id": "2",
                "enabled": True,
                "user_id": "noise-samsung",
                "symbol": "005930",
                "strategy": "noise",
                "reference_price": 70_000,
                "price_step": 100,
                "max_offset_steps": 1,
                "quantity_min": 1,
                "quantity_max": 2,
                "order_ttl_seconds": 2,
                "interval_seconds": 1,
                "seed": 2,
            },
            {
                "id": "3",
                "enabled": True,
                "user_id": "noise-sk",
                "symbol": "000660",
                "strategy": "noise",
                "reference_price": 250_000,
                "price_step": 100,
                "max_offset_steps": 1,
                "quantity_min": 1,
                "quantity_max": 2,
                "order_ttl_seconds": 2,
                "interval_seconds": 1,
                "seed": 3,
            },
        ]

        shard_zero = build_participants(
            profiles,
            runner_shard_index=0,
            symbol_shards={"000660": 0, "005930": 1},
            max_traders=1,
        )
        shard_one = build_participants(
            profiles,
            runner_shard_index=1,
            symbol_shards={"000660": 0, "005930": 1},
        )

        self.assertEqual([participant.user_id for participant in shard_zero], ["noise-hynix"])
        self.assertEqual([participant.user_id for participant in shard_one], ["noise-samsung"])

    def test_profile_selection_requires_shard_map_when_index_is_set(self) -> None:
        with self.assertRaisesRegex(InvalidTraderProfileError, "RUNNER_SHARD_INDEX"):
            build_participants(
                (
                    {
                        "id": "1",
                        "enabled": True,
                        "user_id": "noise-1",
                        "symbol": "005930",
                        "strategy": "noise",
                        "reference_price": 70_000,
                        "price_step": 100,
                        "max_offset_steps": 1,
                        "quantity_min": 1,
                        "quantity_max": 2,
                        "order_ttl_seconds": 2,
                        "interval_seconds": 1,
                        "seed": 1,
                    },
                ),
                runner_shard_index=0,
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
                market_session=MarketSession("always_open"),
            )

        self.assertTrue(
            any("event=runner_status" in line for line in logs.output)
        )
        self.assertEqual(status.orders_canceled_total, 1)
        self.assertEqual(status.open_runner_orders, 0)

    def test_scheduled_runner_waits_until_open_before_first_tick(self) -> None:
        client = FakeBackendClient()
        runner = ParticipantRunner(client, (StaticParticipant((buy_intent(),)),))
        wall_clock = FakeWallClock(
            datetime.fromisoformat("2026-09-22T08:59:59+09:00")
        )
        stop_event = AdvancingStopEvent(wall_clock, stop_after_waits=2)

        status = run_until_stopped(
            runner,
            tick_interval_ms=1_000,
            status_log_interval_ticks=60,
            stop_event=stop_event,
            market_session=MarketSession("scheduled"),
            wall_clock=wall_clock,
        )

        self.assertEqual(status.ticks_total, 1)
        self.assertEqual(len(client.submissions), 1)
        self.assertEqual(stop_event.wait_timeouts[0], 1.0)

    def test_market_close_cleans_orders_once_and_stops_new_ticks(self) -> None:
        client = FakeBackendClient()
        runner = ParticipantRunner(
            client,
            (StaticParticipant((buy_intent(ttl=30),)),),
        )
        wall_clock = FakeWallClock(
            datetime.fromisoformat("2026-09-22T15:29:59+09:00")
        )
        stop_event = AdvancingStopEvent(wall_clock, stop_after_waits=2)

        with self.assertLogs(level="INFO") as logs:
            status = run_until_stopped(
                runner,
                tick_interval_ms=1_000,
                status_log_interval_ticks=60,
                stop_event=stop_event,
                market_session=MarketSession("scheduled"),
                wall_clock=wall_clock,
            )

        self.assertEqual(status.ticks_total, 1)
        self.assertEqual(len(client.submissions), 1)
        self.assertEqual(client.canceled_order_ids, ["order-1"])
        self.assertEqual(status.open_runner_orders, 0)
        self.assertEqual(
            sum("event=runner_market_close" in line for line in logs.output),
            1,
        )

    def test_closed_runner_can_stop_without_generating_a_tick(self) -> None:
        client = FakeBackendClient()
        runner = ParticipantRunner(client, (StaticParticipant((buy_intent(),)),))
        wall_clock = FakeWallClock(
            datetime.fromisoformat("2026-09-22T08:00:00+09:00")
        )
        stop_event = AdvancingStopEvent(wall_clock, stop_after_waits=1)

        status = run_until_stopped(
            runner,
            tick_interval_ms=1_000,
            status_log_interval_ticks=60,
            stop_event=stop_event,
            market_session=MarketSession("scheduled"),
            wall_clock=wall_clock,
        )

        self.assertEqual(status.ticks_total, 0)
        self.assertEqual(client.submissions, [])
        self.assertEqual(stop_event.wait_timeouts, [3600.0])

    def test_http_concurrency_caps_in_flight_submits(self) -> None:
        client = ConcurrentBackendClient()
        intents = tuple(buy_intent() for _ in range(8))
        runner = self.start_runner(
            client,
            (StaticParticipant(intents),),
            http_concurrency=4,
        )

        status = self.finish_tick(runner)

        self.assertEqual(status.orders_submitted_total, 4)
        self.assertEqual(len(client.submissions), 4)
        self.assertEqual(client.max_in_flight, 4)

    def test_serial_http_concurrency_keeps_one_in_flight(self) -> None:
        client = ConcurrentBackendClient()
        intents = tuple(buy_intent() for _ in range(3))
        runner = self.start_runner(
            client,
            (StaticParticipant(intents),),
            http_concurrency=1,
        )

        self.finish_tick(runner)

        self.assertEqual(client.max_in_flight, 1)
        self.assertEqual(len(client.submissions), 1)

    def test_tick_returns_before_http_finishes(self) -> None:
        started = Event()
        release = Event()

        class GateClient(FakeBackendClient):
            def submit_order(self, intent):
                started.set()
                if not release.wait(timeout=2):
                    raise TimeoutError("release was not signaled")
                return super().submit_order(intent)

        client = GateClient()
        runner = self.start_runner(client, (StaticParticipant((buy_intent(),)),))

        status = runner.tick_once()

        self.assertTrue(started.wait(timeout=1))
        self.assertEqual(status.orders_submitted_total, 0)
        self.assertEqual(status.http_in_flight, 1)
        release.set()
        runner.wait_for_idle()
        self.assertEqual(runner.status().orders_submitted_total, 1)

    def test_sharded_client_sends_orders_to_the_owning_matcher(self) -> None:
        shard_zero = FakeBackendClient()
        shard_one = FakeBackendClient()
        client = ShardedBackendClient(
            (shard_zero, shard_one),
            {"000660": 0, "005930": 1},
        )
        hynix = StaticParticipant(
            (
                OrderIntent(
                    user_id="hynix",
                    symbol="000660",
                    side=OrderSide.BUY,
                    price=250_000,
                    quantity=1,
                    order_ttl_seconds=1,
                ),
            )
        )
        hynix.symbol = "000660"
        samsung = StaticParticipant((buy_intent(),))

        runner = self.start_runner(client, (hynix, samsung), http_concurrency=2)
        self.finish_tick(runner)

        self.assertEqual([intent.symbol for intent in shard_zero.submissions], ["000660"])
        self.assertEqual([intent.symbol for intent in shard_one.submissions], ["005930"])
