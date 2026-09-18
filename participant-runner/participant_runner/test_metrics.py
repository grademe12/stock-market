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
    def test_render_includes_in_flight_and_submitted(self) -> None:
        text = render_metrics(
            strategy="noise",
            shard="0",
            http_in_flight=64,
            orders_submitted_total=12,
        )

        self.assertIn('runner_http_in_flight{strategy="noise",shard="0"} 64', text)
        self.assertIn(
            'runner_orders_submitted_total{strategy="noise",shard="0"} 12',
            text,
        )

    def test_metrics_http_reads_runner_status(self) -> None:
        runner = ParticipantRunner(FakeBackend(), (StaticParticipant(),), http_concurrency=1)

        def render() -> str:
            status = runner.status()
            return render_metrics(
                strategy="noise",
                shard="all",
                http_in_flight=status.http_in_flight,
                orders_submitted_total=status.orders_submitted_total,
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

        self.assertIn('runner_http_in_flight{strategy="noise",shard="all"} 0', body)
        self.assertIn(
            'runner_orders_submitted_total{strategy="noise",shard="all"} 1',
            body,
        )
