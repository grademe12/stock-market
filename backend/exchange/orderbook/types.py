from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class Order:
    user_id: str
    symbol: str
    side: OrderSide
    price: int
    quantity: int
    order_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id must not be blank")
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        if not isinstance(self.side, OrderSide):
            raise ValueError("side must be BUY or SELL")
        if type(self.price) is not int or self.price <= 0:
            raise ValueError("price must be a positive integer")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    price: int
    quantity: int
    buy_order_id: UUID
    sell_order_id: UUID
    trade_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class MatchResult:
    order_id: UUID
    trades: tuple[Trade, ...]
    remaining_quantity: int


@dataclass(frozen=True, slots=True)
class OpenOrder:
    order: Order
    remaining_quantity: int
    sequence: int


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: int
    quantity: int


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    symbol: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]


class OrderNotFoundError(LookupError):
    pass
