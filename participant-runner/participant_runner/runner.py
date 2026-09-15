from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from threading import Event, Lock, Semaphore
from time import monotonic, sleep
from typing import Protocol

from exchange.orderbook import BookSnapshot
from exchange.participants.types import OrderIntent, TradingParticipant

from participant_runner.client import BackendApiError, CancellationResult, SubmittedOrder
from participant_runner.config import HTTP_CONCURRENCY_DEFAULT
from participant_runner.coordinator import CoordinatorStatus, EventCoordinator


class BackendClient(Protocol):
    def fetch_book(self, symbol: str) -> BookSnapshot: ...

    def submit_order(self, intent: OrderIntent) -> SubmittedOrder: ...

    def cancel_order(self, order_id: str, symbol: str = "") -> CancellationResult: ...


@dataclass(frozen=True, slots=True)
class TrackedOrder:
    order_id: str
    symbol: str
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
    http_in_flight: int = 0
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
        self._slots = Semaphore(http_concurrency)
        self._pool = ThreadPoolExecutor(max_workers=http_concurrency)
        self._pending = 0
        self._cursor = 0
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
        self._enqueue_due_intents(snapshots)
        return self.status()

    def wait_for_idle(self, timeout_seconds: float = 5.0) -> None:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            with self._lock:
                if self._pending == 0:
                    return
            sleep(0.01)
        raise TimeoutError("runner HTTP is still in flight")

    def close(self) -> None:
        self._pool.shutdown(wait=True)

    def _notify_coordinator_before_tick(self) -> None:
        if self._coordinator is None:
            return
        try:
            with self._lock:
                self._coordinator.before_tick(self._tick)
        except Exception:
            logging.exception("event coordinator failed; continuing baseline traders")

    def _notify_coordinator_after_submit(
        self,
        intent: OrderIntent,
        submitted: bool,
        tick: int,
    ) -> None:
        if self._coordinator is None:
            return
        try:
            with self._lock:
                self._coordinator.after_submit(intent, submitted, tick)
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

    def _enqueue_due_intents(self, snapshots: dict[str, BookSnapshot]) -> None:
        count = len(self._participants)
        if count == 0:
            return
        considered = 0
        for offset in range(count):
            if not self._has_free_slot():
                break
            participant = self._participants[(self._cursor + offset) % count]
            considered += 1
            snapshot = snapshots.get(participant.symbol)
            if snapshot is None:
                continue
            if not self._slots.acquire(blocking=False):
                considered -= 1
                break
            intents = participant.next_intents(self._tick, snapshot)
            if not intents:
                self._slots.release()
                continue
            self._submit_to_pool(
                lambda intent=intents[0], tick=self._tick: self._submit_intent(intent, tick)
            )
            for intent in intents[1:]:
                if not self._start_http(
                    lambda intent=intent, tick=self._tick: self._submit_intent(intent, tick),
                    blocking=False,
                ):
                    break
        if considered:
            self._cursor = (self._cursor + considered) % count

    def _has_free_slot(self) -> bool:
        with self._lock:
            return self._pending < self._http_concurrency

    def _start_http(self, job: Callable[[], None], *, blocking: bool) -> bool:
        if not self._slots.acquire(blocking=blocking):
            return False
        self._submit_to_pool(job)
        return True

    def _submit_to_pool(self, job: Callable[[], None]) -> None:
        with self._lock:
            self._pending += 1
        try:
            self._pool.submit(self._run_job, job)
        except Exception:
            with self._lock:
                self._pending -= 1
            self._slots.release()
            raise

    def _run_job(self, job: Callable[[], None]) -> None:
        try:
            job()
        finally:
            with self._lock:
                self._pending -= 1
            self._slots.release()

    def _submit_intent(self, intent: OrderIntent, tick: int) -> None:
        submitted = self._submit(intent, tick)
        self._notify_coordinator_after_submit(intent, submitted, tick)

    def _submit(self, intent: OrderIntent, tick: int) -> bool:
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
                    symbol=intent.symbol,
                    submitted_tick=tick,
                    expires_after_ticks=intent.order_ttl_ticks or 1,
                )
        return True

    def cancel_all_open_orders(self) -> RunnerStatus:
        self.wait_for_idle()
        with self._lock:
            order_ids = tuple(self._outstanding_orders)
        for order_id in order_ids:
            self._start_http(lambda order_id=order_id: self._cancel(order_id), blocking=True)
        self.wait_for_idle()
        return self.status()

    def status(self) -> RunnerStatus:
        with self._lock:
            open_runner_orders = len(self._outstanding_orders)
            orders_submitted_total = self._orders_submitted
            orders_canceled_total = self._orders_canceled
            orders_already_closed_total = self._orders_already_closed
            request_failures_total = self._request_failures
            http_in_flight = self._pending
            event_status = self._coordinator_status_locked()
        return RunnerStatus(
            ticks_total=self._tick,
            orders_submitted_total=orders_submitted_total,
            orders_canceled_total=orders_canceled_total,
            orders_already_closed_total=orders_already_closed_total,
            request_failures_total=request_failures_total,
            open_runner_orders=open_runner_orders,
            http_in_flight=http_in_flight,
            events_received_total=event_status.events_received_total,
            events_deduplicated_total=event_status.events_deduplicated_total,
            dormant_traders_total=event_status.dormant_traders_total,
            activated_traders_total=event_status.activated_traders_total,
            reactions_planned_total=event_status.reactions_planned_total,
            reactions_submitted_total=event_status.reactions_submitted_total,
            reactions_dropped_total=event_status.reactions_dropped_total,
            scheduler_lag_max_ms=event_status.scheduler_lag_max_ms,
        )

    def _coordinator_status_locked(self) -> CoordinatorStatus:
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
        for order_id in expired_ids:
            if not self._start_http(
                lambda order_id=order_id: self._cancel(order_id),
                blocking=False,
            ):
                break

    def _cancel(self, order_id: str) -> None:
        with self._lock:
            tracked = self._outstanding_orders.get(order_id)
            symbol = tracked.symbol if tracked else ""
        try:
            result = self._client.cancel_order(order_id, symbol)
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
    try:
        while not stop_event.is_set():
            status = runner.tick_once()
            if status.ticks_total % status_log_interval_ticks == 0:
                logging.info(
                    "event=runner_status ticks=%s submitted=%s canceled=%s already_closed=%s "
                    "request_failures=%s open_orders=%s http_in_flight=%s events_received=%s "
                    "activated=%s planned=%s reactions_submitted=%s dropped=%s lag_max_ms=%s",
                    status.ticks_total,
                    status.orders_submitted_total,
                    status.orders_canceled_total,
                    status.orders_already_closed_total,
                    status.request_failures_total,
                    status.open_runner_orders,
                    status.http_in_flight,
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
    finally:
        runner.close()
