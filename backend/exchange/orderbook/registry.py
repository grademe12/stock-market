from datetime import date
from threading import RLock
from uuid import UUID

from django.conf import settings

from exchange.metrics import ORDERS_EXPIRED
from exchange.orderbook.book import OrderBook
from exchange.orderbook.types import MatchResult, OpenOrder, Order, OrderNotFoundError
from exchange.simulation import is_owned_symbol, reset_simulated_tickers_cache


class OrderBookRegistry:
    """In-process map of symbol to its single-writer order book.

    ``_order_symbols`` maps only resting orders to their symbol so a cancel
    can find its book. Books report when an order starts resting and when it
    leaves by a fill or expiry, so filled orders do not stay in the map.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._books: dict[str, OrderBook] = {}
        self._order_symbols: dict[UUID, str] = {}
        self._active_session_date: date | None = None

    def reset(self) -> None:
        """Reset test/development state including the simulated-symbol cache."""
        reset_simulated_tickers_cache()
        self.reset_books()

    def reset_books(self) -> tuple[str, ...]:
        """Clear in-memory matching state without invalidating the symbol universe."""
        with self._lock:
            cleared_symbols = tuple(self._books)
            self._books.clear()
            self._order_symbols.clear()
            self._active_session_date = None
            return cleared_symbols

    def rollover(self, session_date: date | None) -> tuple[str, ...]:
        """Start a newer trading session and return symbols whose books were cleared."""
        if session_date is None:
            return ()

        with self._lock:
            if self._active_session_date is None:
                self._active_session_date = session_date
                return ()
            if session_date <= self._active_session_date:
                return ()

            cleared_symbols = tuple(self._books)
            self._books.clear()
            self._order_symbols.clear()
            self._active_session_date = session_date
            return cleared_symbols

    def get(self, symbol: str) -> OrderBook | None:
        if not is_owned_symbol(symbol):
            return None
        with self._lock:
            book = self._books.get(symbol)
            if book is None:
                book = OrderBook(
                    symbol=symbol,
                    max_age_seconds=getattr(settings, "MATCHER_ORDER_MAX_AGE_SECONDS", 0),
                    on_rest=lambda order_id, symbol=symbol: self._order_rested(order_id, symbol),
                    on_close=lambda order_id, reason, symbol=symbol: self._order_closed(
                        order_id, reason, symbol
                    ),
                )
                self._books[symbol] = book
            return book

    def open_order_id_count(self) -> int:
        with self._lock:
            return len(self._order_symbols)

    def _order_rested(self, order_id: UUID, symbol: str) -> None:
        with self._lock:
            self._order_symbols[order_id] = symbol

    def _order_closed(self, order_id: UUID, reason: str, symbol: str) -> None:
        with self._lock:
            self._order_symbols.pop(order_id, None)
        if reason == "expired":
            ORDERS_EXPIRED.labels(symbol).inc()

    def submit(self, order: Order) -> MatchResult:
        book = self.get(order.symbol)
        if book is None:
            raise LookupError(f"symbol {order.symbol} is not simulated")
        return book.submit(order)

    def cancel(self, order_id: UUID) -> OpenOrder:
        with self._lock:
            symbol = self._order_symbols.get(order_id)
        if symbol is None:
            raise OrderNotFoundError(f"open order {order_id} was not found")
        book = self.get(symbol)
        if book is None:
            raise OrderNotFoundError(f"open order {order_id} was not found")
        try:
            canceled = book.cancel(order_id)
        except OrderNotFoundError:
            with self._lock:
                self._order_symbols.pop(order_id, None)
            raise
        with self._lock:
            self._order_symbols.pop(order_id, None)
        return canceled


books = OrderBookRegistry()
