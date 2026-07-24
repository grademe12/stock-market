from dataclasses import dataclass

from exchange.orderbook import OrderSide


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
        if self.strategy != "noise":
            raise ValueError("only the noise strategy is supported")
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


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    symbol: str = "005930"
    participants: int = 20
    reference_price: int = 70_000
    price_step: int = 100
    max_offset_steps: int = 5
    quantity_min: int = 1
    quantity_max: int = 10
    order_ttl_ticks: int = 5
    interval_ms: int = 1_000
    seed: int = 42

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        if self.participants < 1:
            raise ValueError("participants must be at least 1")
        if self.reference_price < 1:
            raise ValueError("reference_price must be positive")
        if self.price_step < 1:
            raise ValueError("price_step must be positive")
        if self.max_offset_steps < 0:
            raise ValueError("max_offset_steps must not be negative")
        if self.quantity_min < 1 or self.quantity_max < self.quantity_min:
            raise ValueError("quantity range is invalid")
        if self.order_ttl_ticks < 1:
            raise ValueError("order_ttl_ticks must be at least 1")
        if self.interval_ms < 10:
            raise ValueError("interval_ms must be at least 10")


@dataclass(frozen=True, slots=True)
class SimulationStatus:
    state: str
    ticks_total: int
    orders_submitted_total: int
    orders_canceled_total: int
    trades_generated_total: int
    open_bot_orders: int
    last_error: str | None
