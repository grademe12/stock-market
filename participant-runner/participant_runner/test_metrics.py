from unittest import TestCase
from urllib.request import urlopen

from exchange.orderbook import BookLevel, BookSnapshot
from exchange.participants.types import OrderIntent, OrderSide

from participant_runner.client import SubmittedOrder
from participant_runner.metrics import MetricsServer, render_metrics
from participant_runner.runner import ParticipantRunner


class FakeBackend:
    def fetch_book(self, symbol: str) -> BookSnapshot:
        return BookSnapshot(
            symbol=symbol,
            bids=(BookLevel(price=69_900, quantity=10),),
            asks=(BookLevel(price=70_100, quantity=10),),
        )

    def submit_order(self, intent: OrderIntent) -> SubmittedOrder:
        return SubmittedOrder(order_id="order-1", remaining_quantity=1)

    def cancel_order(self, order_id: str, symbol: str = "") -> object:
        raise AssertionError("cancel should not run")


class StaticParticipant:
    user_id = "metrics-trader"
    symbol = "005930"

    def next_intents(self, tick: int, snapshot: BookSnapshot) -> tuple[OrderIntent, ...]:
        return (
            OrderIntent(
                user_id=self.user_id,
                symbol=self.symbol,
                side=OrderSide.BUY,
                price=70_100,
                quantity=1,
            ),
        )


class RunnerMetricsTests(TestCase):
    def test_render_includes_runner_and_event_metrics(self) -> None:
        text = render_metrics(
            strategy="event_reactive",
            shard="0",
            http_in_flight=64,
            orders_submitted_total=12,
            events_received_total=3,
            events_deduplicated_total=1,
            event_trader_pool_size=200,
            activated_traders_total=125,
            reactions_planned_total=320,
            reactions_submitted_total=300,
            reactions_dropped_total=20,
            scheduler_lag_max_ms=1_250,
        )

        labels = 'strategy="event_reactive",shard="0"'
        expected = (
            ("runner_http_in_flight", "gauge", "64"),
            ("runner_orders_submitted_total", "counter", "12"),
            ("runner_events_received_total", "counter", "3"),
            ("runner_events_deduplicated_total", "counter", "1"),
            ("runner_event_trader_pool_size", "gauge", "200"),
            ("runner_activated_traders_total", "counter", "125"),
            ("runner_reactions_planned_total", "counter", "320"),
            ("runner_reactions_submitted_total", "counter", "300"),
            ("runner_reactions_dropped_total", "counter", "20"),
            ("runner_scheduler_lag_max_seconds", "gauge", "1.25"),
        )
        for metric, metric_type, value in expected:
            self.assertIn(f"# TYPE {metric} {metric_type}", text)
            self.assertIn(f"{metric}{{{labels}}} {value}", text)

    def test_metrics_http_reads_runner_status(self) -> None:
        runner = ParticipantRunner(FakeBackend(), (StaticParticipant(),), http_concurrency=1)

        def render() -> str:
            status = runner.status()
            return render_metrics(
                strategy="noise",
                shard="all",
                http_in_flight=status.http_in_flight,
                orders_submitted_total=status.orders_submitted_total,
                events_received_total=status.events_received_total,
                events_deduplicated_total=status.events_deduplicated_total,
                event_trader_pool_size=status.dormant_traders_total,
                activated_traders_total=status.activated_traders_total,
                reactions_planned_total=status.reactions_planned_total,
                reactions_submitted_total=status.reactions_submitted_total,
                reactions_dropped_total=status.reactions_dropped_total,
                scheduler_lag_max_ms=status.scheduler_lag_max_ms,
            )

        server = MetricsServer("127.0.0.1", 0, render)
        server.start()
        try:
            runner.tick_once()
            runner.wait_for_idle()
            with urlopen(f"http://127.0.0.1:{server.port}/metrics", timeout=1) as response:
                body = response.read().decode()
        finally:
            server.stop()
            runner.close()

        labels = 'strategy="noise",shard="all"'
        self.assertIn(f"runner_http_in_flight{{{labels}}} 0", body)
        self.assertIn(f"runner_orders_submitted_total{{{labels}}} 1", body)
        self.assertIn(f"runner_events_received_total{{{labels}}} 0", body)
        self.assertIn(f"runner_event_trader_pool_size{{{labels}}} 0", body)
        self.assertIn(f"runner_scheduler_lag_max_seconds{{{labels}}} 0.0", body)
