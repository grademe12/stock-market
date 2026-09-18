from dataclasses import dataclass
from typing import Protocol

from exchange.orderbook import BookSnapshot, OrderSide


ORDER_TTL_SECONDS_DEFAULT = 16
TICK_INTERVAL_MS_DEFAULT = 1_000

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
    order_ttl_seconds: int | None = None


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
    order_ttl_seconds: int
    interval_seconds: int
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
        if self.order_ttl_seconds < 1 or self.interval_seconds < 1:
            raise ValueError("ttl and interval must be at least 1")


def ticks_for_interval(interval_seconds: int, tick_interval_ms: int) -> int:
    """Convert a wall-clock order interval into runner ticks."""

    if interval_seconds < 1:
        raise ValueError("interval_seconds must be at least 1")
    if tick_interval_ms < 1:
        raise ValueError("tick_interval_ms must be at least 1")
    return max(1, (interval_seconds * 1_000 + tick_interval_ms - 1) // tick_interval_ms)


class TradingParticipant(Protocol):
    user_id: str
    symbol: str

    def next_intents(
        self,
        tick: int,
        snapshot: BookSnapshot,
    ) -> tuple[OrderIntent, ...]: ...
