from dataclasses import dataclass
import logging
from threading import Event
from typing import Protocol

from exchange.participants.types import OrderIntent

from participant_runner.client import BackendApiError, CancellationResult, SubmittedOrder


class BackendClient(Protocol):
    def submit_order(self, intent: OrderIntent) -> SubmittedOrder: ...

    def cancel_order(self, order_id: str) -> CancellationResult: ...


class Participant(Protocol):
    def next_intent(self, tick: int) -> OrderIntent | None: ...


@dataclass(frozen=True, slots=True)
class TrackedOrder:
    order_id: str
    submitted_tick: int
    expires_after_ticks: int


@dataclass(frozen=True, slots=True)
class RunnerStatus:
    ticks_total: int
    orders_submitted_total: int
    orders_canceled_total: int
    orders_already_closed_total: int
    request_failures_total: int
    open_runner_orders: int


class ParticipantRunner:
    """Runs participant decisions outside the backend process through HTTP."""

    def __init__(self, client: BackendClient, participants: tuple[Participant, ...]) -> None:
        self._client = client
        self._participants = participants
        self._tick = 0
        self._outstanding_orders: dict[str, TrackedOrder] = {}
        self._orders_submitted = 0
        self._orders_canceled = 0
        self._orders_already_closed = 0
        self._request_failures = 0

    def tick_once(self) -> RunnerStatus:
        self._tick += 1
        self._expire_orders()

        for participant in self._participants:
            intent = participant.next_intent(self._tick)
            if intent is None:
                continue
            try:
                submitted_order = self._client.submit_order(intent)
            except BackendApiError as exc:
                self._request_failures += 1
                logging.warning("order submission failed: %s", exc)
                continue

            self._orders_submitted += 1
            if submitted_order.remaining_quantity:
                self._outstanding_orders[submitted_order.order_id] = TrackedOrder(
                    order_id=submitted_order.order_id,
                    submitted_tick=self._tick,
                    expires_after_ticks=intent.order_ttl_ticks or 1,
                )

        return self.status()

    def cancel_all_open_orders(self) -> RunnerStatus:
        for order_id in tuple(self._outstanding_orders):
            self._cancel(order_id)
        return self.status()

    def status(self) -> RunnerStatus:
        return RunnerStatus(
            ticks_total=self._tick,
            orders_submitted_total=self._orders_submitted,
            orders_canceled_total=self._orders_canceled,
            orders_already_closed_total=self._orders_already_closed,
            request_failures_total=self._request_failures,
            open_runner_orders=len(self._outstanding_orders),
        )

    def _expire_orders(self) -> None:
        for order_id, tracked_order in tuple(self._outstanding_orders.items()):
            if self._tick - tracked_order.submitted_tick >= tracked_order.expires_after_ticks:
                self._cancel(order_id)

    def _cancel(self, order_id: str) -> None:
        try:
            result = self._client.cancel_order(order_id)
            if result.status == "ALREADY_CLOSED":
                self._orders_already_closed += 1
            else:
                self._orders_canceled += 1
        except BackendApiError as exc:
            self._request_failures += 1
            logging.warning("order cancellation failed: %s", exc)
            return
        self._outstanding_orders.pop(order_id, None)


def run_until_stopped(
    runner: ParticipantRunner,
    tick_interval_ms: int,
    status_log_interval_ticks: int,
    stop_event: Event,
) -> RunnerStatus:
    while not stop_event.is_set():
        status = runner.tick_once()
        if status.ticks_total % status_log_interval_ticks == 0:
            logging.info(
                "event=runner_status ticks=%s submitted=%s canceled=%s already_closed=%s "
                "request_failures=%s open_orders=%s",
                status.ticks_total,
                status.orders_submitted_total,
                status.orders_canceled_total,
                status.orders_already_closed_total,
                status.request_failures_total,
                status.open_runner_orders,
            )
        if stop_event.wait(tick_interval_ms / 1_000):
            break
    return runner.cancel_all_open_orders()
