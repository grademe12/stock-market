from typing import Protocol
from uuid import UUID

from exchange.orderbook import MatchResult, OpenOrder, Order
from exchange.participants.types import OrderIntent


class OrderExecutor(Protocol):
    """Port the simulator needs from the matching engine.

    The in-process adapter calls ``OrderBook`` directly. A future worker can
    implement the same port through an HTTP or message-bus client.
    """

    def submit(self, order: Order) -> MatchResult: ...

    def cancel(self, order_id: UUID) -> OpenOrder: ...

    def get_open_order(self, order_id: UUID) -> OpenOrder | None: ...


class TradingParticipant(Protocol):
    def next_intent(self, tick: int) -> OrderIntent | None: ...
