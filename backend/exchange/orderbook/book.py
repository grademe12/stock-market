from bisect import bisect_left, insort
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from uuid import UUID

from exchange.orderbook.types import (
    BookLevel,
    BookSnapshot,
    MatchResult,
    OpenOrder,
    Order,
    OrderNotFoundError,
    OrderSide,
    Trade,
)

# Rebuild a price level's queue once it holds more canceled entries than this
# and more canceled than live ones. Keeps lazy cancellation from leaking memory
# at levels that rarely reach the front of the book.
_COMPACT_MIN_DEAD = 64


@dataclass(slots=True)
class _Entry:
    order: Order
    remaining_quantity: int
    sequence: int
    rested_at: float
    alive: bool = True

    def as_open_order(self) -> OpenOrder:
        return OpenOrder(
            order=self.order,
            remaining_quantity=self.remaining_quantity,
            sequence=self.sequence,
        )


class _Level:
    __slots__ = ("queue", "quantity", "dead")

    def __init__(self) -> None:
        self.queue: deque[_Entry] = deque()
        self.quantity = 0
        self.dead = 0


class _Side:
    """One side of the book: sorted price keys plus a FIFO queue per price.

    Keys are stored ascending so ``keys[0]`` is always the best price:
    the price itself for asks and its negation for bids.
    """

    __slots__ = ("side", "keys", "levels", "total_quantity")

    def __init__(self, side: OrderSide) -> None:
        self.side = side
        self.keys: list[int] = []
        self.levels: dict[int, _Level] = {}
        self.total_quantity = 0

    def key(self, price: int) -> int:
        return -price if self.side is OrderSide.BUY else price

    def price(self, key: int) -> int:
        return -key if self.side is OrderSide.BUY else key

    def add(self, entry: _Entry) -> None:
        price = entry.order.price
        level = self.levels.get(price)
        if level is None:
            level = _Level()
            self.levels[price] = level
            insort(self.keys, self.key(price))
        level.queue.append(entry)
        level.quantity += entry.remaining_quantity
        self.total_quantity += entry.remaining_quantity

    def best(self) -> _Entry | None:
        """Return the oldest live order at the best price, dropping canceled ones."""
        while self.keys:
            price = self.price(self.keys[0])
            level = self.levels[price]
            queue = level.queue
            while queue and not queue[0].alive:
                queue.popleft()
                level.dead -= 1
            if queue:
                return queue[0]
            self._drop_level(price)
        return None

    def fill_best(self, entry: _Entry, quantity: int) -> bool:
        """Reduce the front order by ``quantity``. Return True when it is fully filled."""
        level = self.levels[entry.order.price]
        entry.remaining_quantity -= quantity
        level.quantity -= quantity
        self.total_quantity -= quantity
        if entry.remaining_quantity:
            return False
        entry.alive = False
        level.queue.popleft()
        if level.quantity == 0:
            self._drop_level(entry.order.price)
        return True

    def remove(self, entry: _Entry) -> None:
        """Remove a live order from anywhere in the book (cancel or expiry)."""
        price = entry.order.price
        level = self.levels[price]
        entry.alive = False
        level.quantity -= entry.remaining_quantity
        self.total_quantity -= entry.remaining_quantity
        if level.quantity == 0:
            # Every entry left in the queue is dead.
            self._drop_level(price)
            return
        level.dead += 1
        if level.dead > _COMPACT_MIN_DEAD and level.dead * 2 > len(level.queue):
            level.queue = deque(item for item in level.queue if item.alive)
            level.dead = 0

    def live_entries(self):
        for key in self.keys:
            for entry in self.levels[self.price(key)].queue:
                if entry.alive:
                    yield entry

    def book_levels(self) -> tuple[BookLevel, ...]:
        levels = self.levels
        return tuple(
            BookLevel(price=price, quantity=levels[price].quantity)
            for price in (self.price(key) for key in self.keys)
        )

    def _drop_level(self, price: int) -> None:
        del self.levels[price]
        key = self.key(price)
        index = bisect_left(self.keys, key)
        del self.keys[index]


class OrderBook:
    """A single-symbol, in-memory limit order book.

    Price-time priority: better price first, then arrival order within a
    price. The matching price is always the resting (maker) order's price.

    Each side keeps sorted price levels with a FIFO queue per level, an
    order-ID index, and running quantity totals, so the cost of one operation
    does not grow with the number of resting orders.

    ``max_age_seconds`` > 0 makes the book drop orders that have rested that
    long. Expiry is lazy: it runs at the start of the next call on this book.
    ``on_rest(order_id)`` and ``on_close(order_id, reason)`` are called under
    the book lock when an order starts resting and when it leaves the book by
    a fill (``"filled"``) or by expiry (``"expired"``). Cancels are not
    reported; the caller already knows about them.
    """

    def __init__(
        self,
        symbol: str,
        *,
        recent_trade_capacity: int = 200,
        max_age_seconds: float = 0,
        clock: Callable[[], float] = monotonic,
        on_rest: Callable[[UUID], None] | None = None,
        on_close: Callable[[UUID, str], None] | None = None,
    ) -> None:
        if not symbol.strip():
            raise ValueError("symbol must not be blank")
        if recent_trade_capacity < 1:
            raise ValueError("recent_trade_capacity must be at least 1")
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must not be negative")

        self.symbol = symbol
        self._sides = {OrderSide.BUY: _Side(OrderSide.BUY), OrderSide.SELL: _Side(OrderSide.SELL)}
        self._index: dict[UUID, _Entry] = {}
        self._recent_trades: deque[Trade] = deque(maxlen=recent_trade_capacity)
        self._sequence = 0
        self._lock = RLock()
        self._max_age_seconds = max_age_seconds
        self._clock = clock
        # Arrival order of resting entries, kept only when expiry is enabled.
        self._arrivals: deque[_Entry] = deque()
        self._on_rest = on_rest
        self._on_close = on_close
        self.expired_total = 0

    def submit(self, order: Order) -> MatchResult:
        if order.symbol != self.symbol:
            raise ValueError(f"order symbol must be {self.symbol}")

        with self._lock:
            self._expire()
            remaining_quantity = order.quantity
            trades: list[Trade] = []
            opposing = self._sides[OrderSide.SELL if order.side is OrderSide.BUY else OrderSide.BUY]

            while remaining_quantity:
                resting = opposing.best()
                if resting is None or not self._crosses(order, resting.order):
                    break
                matched_quantity = min(remaining_quantity, resting.remaining_quantity)
                buy_order, sell_order = self._trade_orders(order, resting.order)
                trades.append(
                    Trade(
                        symbol=self.symbol,
                        price=resting.order.price,
                        quantity=matched_quantity,
                        buy_order_id=buy_order.order_id,
                        sell_order_id=sell_order.order_id,
                    )
                )
                remaining_quantity -= matched_quantity
                if opposing.fill_best(resting, matched_quantity):
                    self._close(resting, "filled")

            if remaining_quantity:
                self._rest(order, remaining_quantity)

            self._recent_trades.extend(trades)

            return MatchResult(
                order_id=order.order_id,
                trades=tuple(trades),
                remaining_quantity=remaining_quantity,
            )

    def recent_trades(self, limit: int) -> tuple[Trade, ...]:
        """Return the newest executions first from the bounded in-memory tape."""
        if limit < 1:
            raise ValueError("limit must be at least 1")

        with self._lock:
            return tuple(reversed(tuple(self._recent_trades)[-limit:]))

    def open_orders(self, side: OrderSide) -> tuple[OpenOrder, ...]:
        """All resting orders on one side in priority order. O(n); for tests and tools."""
        if side not in self._sides:
            raise ValueError("side must be BUY or SELL")
        with self._lock:
            self._expire()
            return tuple(entry.as_open_order() for entry in self._sides[side].live_entries())

    def cancel(self, order_id: UUID) -> OpenOrder:
        """Remove a resting order and return the quantity that was canceled."""
        with self._lock:
            self._expire()
            entry = self._index.pop(order_id, None)
            if entry is None:
                raise OrderNotFoundError(f"open order {order_id} was not found")
            canceled = entry.as_open_order()
            self._sides[entry.order.side].remove(entry)
            return canceled

    def get_open_order(self, order_id: UUID) -> OpenOrder | None:
        """Return an open order by ID, or ``None`` when it has been filled/canceled."""
        with self._lock:
            self._expire()
            entry = self._index.get(order_id)
            return entry.as_open_order() if entry is not None else None

    def snapshot(self) -> BookSnapshot:
        with self._lock:
            self._expire()
            return BookSnapshot(
                symbol=self.symbol,
                bids=self._sides[OrderSide.BUY].book_levels(),
                asks=self._sides[OrderSide.SELL].book_levels(),
            )

    def total_quantity(self, side: OrderSide) -> int:
        """Remaining quantity on one side. O(1); used for the depth gauge."""
        with self._lock:
            self._expire()
            return self._sides[side].total_quantity

    def best_price(self, side: OrderSide) -> int | None:
        with self._lock:
            self._expire()
            entry = self._sides[side].best()
            return entry.order.price if entry is not None else None

    def open_order_count(self) -> int:
        with self._lock:
            return len(self._index)

    @staticmethod
    def _crosses(incoming_order: Order, resting_order: Order) -> bool:
        if incoming_order.side is OrderSide.BUY:
            return incoming_order.price >= resting_order.price
        return incoming_order.price <= resting_order.price

    @staticmethod
    def _trade_orders(incoming_order: Order, resting_order: Order) -> tuple[Order, Order]:
        if incoming_order.side is OrderSide.BUY:
            return incoming_order, resting_order
        return resting_order, incoming_order

    def _rest(self, order: Order, remaining_quantity: int) -> None:
        self._sequence += 1
        entry = _Entry(
            order=order,
            remaining_quantity=remaining_quantity,
            sequence=self._sequence,
            rested_at=self._clock() if self._max_age_seconds else 0.0,
        )
        self._sides[order.side].add(entry)
        self._index[order.order_id] = entry
        if self._max_age_seconds:
            self._arrivals.append(entry)
        if self._on_rest is not None:
            self._on_rest(order.order_id)

    def _close(self, entry: _Entry, reason: str) -> None:
        self._index.pop(entry.order.order_id, None)
        if self._on_close is not None:
            self._on_close(entry.order.order_id, reason)

    def _expire(self) -> None:
        if not self._max_age_seconds:
            return
        deadline = self._clock() - self._max_age_seconds
        arrivals = self._arrivals
        while arrivals:
            entry = arrivals[0]
            if entry.alive and entry.rested_at > deadline:
                return
            arrivals.popleft()
            if not entry.alive:
                continue
            self._sides[entry.order.side].remove(entry)
            self.expired_total += 1
            self._close(entry, "expired")
