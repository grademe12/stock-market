from dataclasses import asdict
from threading import Event, RLock, Thread, current_thread

from exchange.participants.orchestrator import ParticipantOrchestrator
from exchange.participants.ports import OrderExecutor, TradingParticipant
from exchange.participants.types import SimulationConfig, SimulationStatus


class SimulationAlreadyRunningError(RuntimeError):
    pass


class ParticipantSimulationRuntime:
    """Owns the optional in-process tick thread and its current simulation."""

    def __init__(self, order_executor: OrderExecutor) -> None:
        self._order_executor = order_executor
        self._lock = RLock()
        self._orchestrator: ParticipantOrchestrator | None = None
        self._stop_event: Event | None = None
        self._thread: Thread | None = None

    def start(
        self,
        config: SimulationConfig,
        participants: tuple[TradingParticipant, ...] | None = None,
    ) -> SimulationStatus:
        with self._lock:
            if self.is_running:
                raise SimulationAlreadyRunningError("participant simulation is already running")

            self._orchestrator = ParticipantOrchestrator(config, self._order_executor, participants)
            self._stop_event = Event()
            self._thread = Thread(target=self._run, name="participant-simulation", daemon=True)
            self._thread.start()
            return self.status()

    def tick_once(
        self,
        config: SimulationConfig,
        participants: tuple[TradingParticipant, ...] | None = None,
    ) -> SimulationStatus:
        with self._lock:
            if self.is_running:
                raise SimulationAlreadyRunningError("stop the running simulation before a manual tick")
            if self._orchestrator is None or self._orchestrator.config != config:
                self._orchestrator = ParticipantOrchestrator(config, self._order_executor, participants)
            return self._orchestrator.tick()

    def stop(self) -> SimulationStatus:
        with self._lock:
            stop_event = self._stop_event
            thread = self._thread
            if stop_event is None or thread is None:
                return self.status()
            stop_event.set()

        thread.join(timeout=1)
        with self._lock:
            if self._orchestrator is not None:
                self._orchestrator.cancel_all_open_orders()
        return self.status()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> SimulationStatus:
        with self._lock:
            if self._orchestrator is None:
                return SimulationStatus(
                    state="STOPPED",
                    ticks_total=0,
                    orders_submitted_total=0,
                    orders_canceled_total=0,
                    trades_generated_total=0,
                    open_bot_orders=0,
                    last_error=None,
                )
            return self._orchestrator.status(state="RUNNING" if self.is_running else "STOPPED")

    def status_payload(self) -> dict[str, object]:
        return asdict(self.status())

    def _run(self) -> None:
        while True:
            with self._lock:
                stop_event = self._stop_event
                orchestrator = self._orchestrator
            if stop_event is None or orchestrator is None or stop_event.is_set():
                break

            try:
                orchestrator.tick()
            except Exception as exc:  # Preserve the runner for observability in development.
                orchestrator.record_error(exc)

            if stop_event.wait(orchestrator.config.interval_ms / 1_000):
                break

        with self._lock:
            if self._thread is current_thread():
                self._thread = None
                self._stop_event = None
