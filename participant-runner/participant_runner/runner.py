from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import logging
from threading import Event, Lock
from typing import Protocol

from exchange.orderbook import BookSnapshot
from exchange.participants.types import OrderIntent, TradingParticipant

from participant_runner.client import BackendApiError, CancellationResult, SubmittedOrder
from participant_runner.config import HTTP_CONCURRENCY_DEFAULT
from participant_runner.coordinator import CoordinatorStatus, EventCoordinator


class BackendClient(Protocol):
    def fetch_book(self, symbol: str) -> BookSnapshot: ...

    def submit_order(self, intent: OrderIntent) -> SubmittedOrder: ...

    def cancel_order(self, order_id: str) -> CancellationResult: ...


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
    events_received_total: int = 0
    events_deduplicated_total: int = 0
    dormant_traders_total: int = 0
    activated_traders_total: int = 0
    reactions_planned_total: int = 0
    reactions_submitted_total: int = 0
    reactions_dropped_total: int = 0
    scheduler_lag_max_ms: int = 0


class ParticipantRunner:
    """Runs participant decisions outside the backend process through HTTP."""

    def __init__(
        self,
        client: BackendClient,
        participants: tuple[TradingParticipant, ...],
        coordinator: EventCoordinator | None = None,
        http_concurrency: int = HTTP_CONCURRENCY_DEFAULT,
    ) -> None:
        if http_concurrency < 1:
            raise ValueError("http_concurrency must be at least 1")
        self._client = client
        self._participants = participants
        self._coordinator = coordinator
        self._http_concurrency = http_concurrency
        self._lock = Lock()
        self._tick = 0
        self._outstanding_orders: dict[str, TrackedOrder] = {}
        self._orders_submitted = 0
        self._orders_canceled = 0
        self._orders_already_closed = 0
        self._request_failures = 0

    def tick_once(self) -> RunnerStatus:
        self._tick += 1
        self._notify_coordinator_before_tick()
        self._expire_orders()

        snapshots = self._fetch_snapshots()
        intents: list[OrderIntent] = []
        for participant in self._participants:
            snapshot = snapshots.get(participant.symbol)
            if snapshot is None:
                continue
            intents.extend(participant.next_intents(self._tick, snapshot))

        submitted_flags = self._run_http(
            [lambda intent=intent: self._submit(intent) for intent in intents]
        )
        for intent, submitted in zip(intents, submitted_flags, strict=True):
            self._notify_coordinator_after_submit(intent, bool(submitted))

        return self.status()

    def _notify_coordinator_before_tick(self) -> None:
        if self._coordinator is None:
            return
        try:
            self._coordinator.before_tick(self._tick)
        except Exception:
            logging.exception("event coordinator failed; continuing baseline traders")

    def _notify_coordinator_after_submit(self, intent: OrderIntent, submitted: bool) -> None:
        if self._coordinator is None:
            return
        try:
            self._coordinator.after_submit(intent, submitted, self._tick)
        except Exception:
            logging.exception("event coordinator submit hook failed")

    def _fetch_snapshots(self) -> dict[str, BookSnapshot]:
        snapshots: dict[str, BookSnapshot] = {}
        for symbol in dict.fromkeys(participant.symbol for participant in self._participants):
            try:
                snapshots[symbol] = self._client.fetch_book(symbol)
            except BackendApiError as exc:
                with self._lock:
                    self._request_failures += 1
                logging.warning("book request failed for %s: %s", symbol, exc)
        return snapshots

    def _run_http(self, jobs: Sequence[Callable[[], object]]) -> list[object]:
        if not jobs:
            return []
        workers = min(self._http_concurrency, len(jobs))
        if workers == 1:
            return [job() for job in jobs]
        results: list[object | None] = [None] * len(jobs)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(job): index for index, job in enumerate(jobs)}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return list(results)

    def _submit(self, intent: OrderIntent) -> bool:
        try:
            submitted_order = self._client.submit_order(intent)
        except BackendApiError as exc:
            with self._lock:
                self._request_failures += 1
            logging.warning("order submission failed: %s", exc)
            return False

        with self._lock:
            self._orders_submitted += 1
            if submitted_order.remaining_quantity:
                self._outstanding_orders[submitted_order.order_id] = TrackedOrder(
                    order_id=submitted_order.order_id,
                    submitted_tick=self._tick,
                    expires_after_ticks=intent.order_ttl_ticks or 1,
                )
        return True

    def cancel_all_open_orders(self) -> RunnerStatus:
        with self._lock:
            order_ids = tuple(self._outstanding_orders)
        self._run_http([lambda order_id=order_id: self._cancel(order_id) for order_id in order_ids])
        return self.status()

    def status(self) -> RunnerStatus:
        event_status = self._coordinator_status()
        with self._lock:
            open_runner_orders = len(self._outstanding_orders)
            orders_submitted_total = self._orders_submitted
            orders_canceled_total = self._orders_canceled
            orders_already_closed_total = self._orders_already_closed
            request_failures_total = self._request_failures
        return RunnerStatus(
            ticks_total=self._tick,
            orders_submitted_total=orders_submitted_total,
            orders_canceled_total=orders_canceled_total,
            orders_already_closed_total=orders_already_closed_total,
            request_failures_total=request_failures_total,
            open_runner_orders=open_runner_orders,
            events_received_total=event_status.events_received_total,
            events_deduplicated_total=event_status.events_deduplicated_total,
            dormant_traders_total=event_status.dormant_traders_total,
            activated_traders_total=event_status.activated_traders_total,
            reactions_planned_total=event_status.reactions_planned_total,
            reactions_submitted_total=event_status.reactions_submitted_total,
            reactions_dropped_total=event_status.reactions_dropped_total,
            scheduler_lag_max_ms=event_status.scheduler_lag_max_ms,
        )

    def _coordinator_status(self) -> CoordinatorStatus:
        if self._coordinator is None:
            return CoordinatorStatus(
                events_received_total=0,
                events_deduplicated_total=0,
                dormant_traders_total=0,
                activated_traders_total=0,
                reactions_planned_total=0,
                reactions_submitted_total=0,
                reactions_dropped_total=0,
                scheduler_lag_max_ms=0,
            )
        return self._coordinator.status()

    def _expire_orders(self) -> None:
        with self._lock:
            expired_ids = tuple(
                order_id
                for order_id, tracked_order in self._outstanding_orders.items()
                if self._tick - tracked_order.submitted_tick >= tracked_order.expires_after_ticks
            )
        self._run_http(
            [lambda order_id=order_id: self._cancel(order_id) for order_id in expired_ids]
        )

    def _cancel(self, order_id: str) -> None:
        try:
            result = self._client.cancel_order(order_id)
        except BackendApiError as exc:
            with self._lock:
                self._request_failures += 1
            logging.warning("order cancellation failed: %s", exc)
            return
        with self._lock:
            if result.status == "ALREADY_CLOSED":
                self._orders_already_closed += 1
            else:
                self._orders_canceled += 1
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
                "request_failures=%s open_orders=%s events_received=%s activated=%s "
                "planned=%s reactions_submitted=%s dropped=%s lag_max_ms=%s",
                status.ticks_total,
                status.orders_submitted_total,
                status.orders_canceled_total,
                status.orders_already_closed_total,
                status.request_failures_total,
                status.open_runner_orders,
                status.events_received_total,
                status.activated_traders_total,
                status.reactions_planned_total,
                status.reactions_submitted_total,
                status.reactions_dropped_total,
                status.scheduler_lag_max_ms,
            )
        if stop_event.wait(tick_interval_ms / 1_000):
            break
    return runner.cancel_all_open_orders()
