from datetime import date
from threading import RLock
from uuid import UUID

from exchange.orderbook.book import OrderBook
from exchange.orderbook.types import MatchResult, OpenOrder, Order, OrderNotFoundError
from exchange.simulation import is_owned_symbol, reset_simulated_tickers_cache


class OrderBookRegistry:
    """In-process map of symbol to its single-writer order book."""

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
                book = OrderBook(symbol=symbol)
                self._books[symbol] = book
            return book

    def submit(self, order: Order) -> MatchResult:
        book = self.get(order.symbol)
        if book is None:
            raise LookupError(f"symbol {order.symbol} is not simulated")
        result = book.submit(order)
        with self._lock:
            self._order_symbols[order.order_id] = order.symbol
        return result

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
