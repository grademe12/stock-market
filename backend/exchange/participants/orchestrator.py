from dataclasses import dataclass
from uuid import UUID

from exchange.orderbook import Order, OrderNotFoundError
from exchange.participants.ports import OrderExecutor, TradingParticipant
from exchange.participants.traders import build_noise_traders
from exchange.participants.types import SimulationConfig, SimulationStatus


@dataclass(frozen=True, slots=True)
class TrackedOrder:
    order_id: UUID
    submitted_tick: int
    expires_after_ticks: int


class ParticipantOrchestrator:
    """Runs participant decisions against one order-execution port per tick."""

    def __init__(
        self,
        config: SimulationConfig,
        order_executor: OrderExecutor,
        participants: tuple[TradingParticipant, ...] | None = None,
    ) -> None:
        self.config = config
        self._order_executor = order_executor
        self._participants = participants if participants is not None else build_noise_traders(config)
        self._tick = 0
        self._outstanding_orders: dict[UUID, TrackedOrder] = {}
        self._orders_submitted = 0
        self._orders_canceled = 0
        self._trades_generated = 0
        self._last_error: str | None = None

    def tick(self) -> SimulationStatus:
        self._tick += 1
        self._expire_orders()

        for participant in self._participants:
            intent = participant.next_intent(self._tick)
            if intent is None:
                continue
            result = self._order_executor.submit(
                Order(
                    user_id=intent.user_id,
                    symbol=intent.symbol,
                    side=intent.side,
                    price=intent.price,
                    quantity=intent.quantity,
                )
            )
            self._orders_submitted += 1
            self._trades_generated += len(result.trades)

            if result.remaining_quantity:
                self._outstanding_orders[result.order_id] = TrackedOrder(
                    order_id=result.order_id,
                    submitted_tick=self._tick,
                    expires_after_ticks=intent.order_ttl_ticks or self.config.order_ttl_ticks,
                )

        self._prune_filled_orders()
        return self.status(state="MANUAL")

    def status(self, state: str = "STOPPED") -> SimulationStatus:
        return SimulationStatus(
            state=state,
            ticks_total=self._tick,
            orders_submitted_total=self._orders_submitted,
            orders_canceled_total=self._orders_canceled,
            trades_generated_total=self._trades_generated,
            open_bot_orders=len(self._outstanding_orders),
            last_error=self._last_error,
        )

    def record_error(self, error: Exception) -> None:
        self._last_error = str(error)

    def cancel_all_open_orders(self) -> None:
        """Remove this simulation's remaining orders when a run is stopped."""
        for order_id in tuple(self._outstanding_orders):
            try:
                self._order_executor.cancel(order_id)
                self._orders_canceled += 1
            except OrderNotFoundError:
                pass
            finally:
                self._outstanding_orders.pop(order_id, None)

    def _expire_orders(self) -> None:
        for order_id, tracked_order in tuple(self._outstanding_orders.items()):
            if self._tick - tracked_order.submitted_tick < tracked_order.expires_after_ticks:
                continue

            try:
                self._order_executor.cancel(order_id)
                self._orders_canceled += 1
            except OrderNotFoundError:
                pass
            finally:
                self._outstanding_orders.pop(order_id, None)

    def _prune_filled_orders(self) -> None:
        for order_id in tuple(self._outstanding_orders):
            if self._order_executor.get_open_order(order_id) is None:
                self._outstanding_orders.pop(order_id)
