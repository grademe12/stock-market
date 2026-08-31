from collections import deque
from dataclasses import replace
from threading import RLock

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


class OrderBook:
    """A single-symbol, in-memory limit order book.

    Resting orders are sorted by price and then their insertion sequence. The
    matching price is always the resting (maker) order's price.
    """

    def __init__(self, symbol: str, *, recent_trade_capacity: int = 200) -> None:
        if not symbol.strip():
            raise ValueError("symbol must not be blank")
        if recent_trade_capacity < 1:
            raise ValueError("recent_trade_capacity must be at least 1")

        self.symbol = symbol
        self._bids: list[OpenOrder] = []
        self._asks: list[OpenOrder] = []
        self._recent_trades: deque[Trade] = deque(maxlen=recent_trade_capacity)
        self._sequence = 0
        self._lock = RLock()

    def submit(self, order: Order) -> MatchResult:
        if order.symbol != self.symbol:
            raise ValueError(f"order symbol must be {self.symbol}")

        with self._lock:
            remaining_quantity = order.quantity
            trades: list[Trade] = []
            opposing_orders = self._asks if order.side is OrderSide.BUY else self._bids

            while remaining_quantity and opposing_orders and self._crosses(order, opposing_orders[0]):
                resting_order = opposing_orders[0]
                matched_quantity = min(remaining_quantity, resting_order.remaining_quantity)
                buy_order, sell_order = self._trade_orders(order, resting_order.order)

                trades.append(
                    Trade(
                        symbol=self.symbol,
                        price=resting_order.order.price,
                        quantity=matched_quantity,
                        buy_order_id=buy_order.order_id,
                        sell_order_id=sell_order.order_id,
                    )
                )
                remaining_quantity -= matched_quantity

                if matched_quantity == resting_order.remaining_quantity:
                    opposing_orders.pop(0)
                else:
                    opposing_orders[0] = replace(
                        resting_order,
                        remaining_quantity=resting_order.remaining_quantity - matched_quantity,
                    )

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
        with self._lock:
            if side is OrderSide.BUY:
                return tuple(self._bids)
            if side is OrderSide.SELL:
                return tuple(self._asks)
        raise ValueError("side must be BUY or SELL")

    def cancel(self, order_id: UUID) -> OpenOrder:
        """Remove a resting order and return the quantity that was canceled."""
        with self._lock:
            for orders in (self._bids, self._asks):
                for index, open_order in enumerate(orders):
                    if open_order.order.order_id == order_id:
                        return orders.pop(index)

        raise OrderNotFoundError(f"open order {order_id} was not found")

    def get_open_order(self, order_id: UUID) -> OpenOrder | None:
        """Return an open order by ID, or ``None`` when it has been filled/canceled."""
        with self._lock:
            for orders in (self._bids, self._asks):
                for open_order in orders:
                    if open_order.order.order_id == order_id:
                        return open_order
        return None

    def snapshot(self) -> BookSnapshot:
        with self._lock:
            return BookSnapshot(
                symbol=self.symbol,
                bids=self._levels(self._bids),
                asks=self._levels(self._asks),
            )

    def _crosses(self, incoming_order: Order, resting_order: OpenOrder) -> bool:
        if incoming_order.side is OrderSide.BUY:
            return incoming_order.price >= resting_order.order.price
        return incoming_order.price <= resting_order.order.price

    def _trade_orders(self, incoming_order: Order, resting_order: Order) -> tuple[Order, Order]:
        if incoming_order.side is OrderSide.BUY:
            return incoming_order, resting_order
        return resting_order, incoming_order

    def _rest(self, order: Order, remaining_quantity: int) -> None:
        self._sequence += 1
        resting_order = OpenOrder(
            order=order,
            remaining_quantity=remaining_quantity,
            sequence=self._sequence,
        )

        if order.side is OrderSide.BUY:
            self._bids.append(resting_order)
            self._bids.sort(key=lambda item: (-item.order.price, item.sequence))
        else:
            self._asks.append(resting_order)
            self._asks.sort(key=lambda item: (item.order.price, item.sequence))

    @staticmethod
    def _levels(orders: list[OpenOrder]) -> tuple[BookLevel, ...]:
        quantities_by_price: dict[int, int] = {}
        for open_order in orders:
            price = open_order.order.price
            quantities_by_price[price] = quantities_by_price.get(price, 0) + open_order.remaining_quantity

        return tuple(
            BookLevel(price=price, quantity=quantity)
            for price, quantity in quantities_by_price.items()
        )
