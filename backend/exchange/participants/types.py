from dataclasses import dataclass
from typing import Protocol

from exchange.orderbook import BookSnapshot, OrderSide


SUPPORTED_STRATEGIES = (
    "noise",
    "momentum",
    "mean_reversion",
    "liquidity_provider",
    "event_reactive",
)


@dataclass(frozen=True, slots=True)
class OrderIntent:
    user_id: str
    symbol: str
    side: OrderSide
    price: int
    quantity: int
    order_ttl_ticks: int | None = None


@dataclass(frozen=True, slots=True)
class TraderSettings:
    """Strategy settings independent of Django persistence or API transport."""

    user_id: str
    symbol: str
    strategy: str
    reference_price: int
    price_step: int
    max_offset_steps: int
    quantity_min: int
    quantity_max: int
    order_ttl_ticks: int
    interval_ticks: int
    seed: int

    def __post_init__(self) -> None:
        if self.strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(f"unsupported strategy: {self.strategy}")
        if not self.user_id.strip() or not self.symbol.strip():
            raise ValueError("user_id and symbol must not be blank")
        if self.reference_price < 1 or self.price_step < 1:
            raise ValueError("reference_price and price_step must be positive")
        if self.max_offset_steps < 0:
            raise ValueError("max_offset_steps must not be negative")
        if self.quantity_min < 1 or self.quantity_max < self.quantity_min:
            raise ValueError("quantity range is invalid")
        if self.order_ttl_ticks < 1 or self.interval_ticks < 1:
            raise ValueError("tick intervals must be at least 1")


class TradingParticipant(Protocol):
    user_id: str
    symbol: str

    def next_intents(
        self,
        tick: int,
        snapshot: BookSnapshot,
    ) -> tuple[OrderIntent, ...]: ...
