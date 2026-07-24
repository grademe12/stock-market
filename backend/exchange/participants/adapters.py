from collections.abc import Callable
from uuid import UUID

from exchange.orderbook import MatchResult, OpenOrder, Order, OrderBook


class InMemoryOrderBookAdapter:
    """Adapter for the current single-process order book.

    ``book_provider`` keeps the simulator decoupled from Django module globals
    and can later be replaced by a remote execution adapter.
    """

    def __init__(self, book_provider: Callable[[], OrderBook]) -> None:
        self._book_provider = book_provider

    def submit(self, order: Order) -> MatchResult:
        return self._book_provider().submit(order)

    def cancel(self, order_id: UUID) -> OpenOrder:
        return self._book_provider().cancel(order_id)

    def get_open_order(self, order_id: UUID) -> OpenOrder | None:
        return self._book_provider().get_open_order(order_id)
