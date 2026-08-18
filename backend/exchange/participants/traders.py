from random import Random

from exchange.orderbook import BookSnapshot, OrderSide
from exchange.participants.events import ReactionCandidate, ResolvedReactionPlan
from exchange.participants.types import OrderIntent, TraderSettings, TradingParticipant


class BaseTrader:
    def __init__(self, settings: TraderSettings) -> None:
        self.user_id = settings.user_id
        self.symbol = settings.symbol
        self._settings = settings
        self._random = Random(settings.seed)
        self._phase = settings.seed % settings.interval_ticks

    def _is_due(self, tick: int) -> bool:
        return (tick + self._phase) % self._settings.interval_ticks == 0

    def _quantity(self) -> int:
        return self._random.randint(
            self._settings.quantity_min,
            self._settings.quantity_max,
        )

    def _intent(self, side: OrderSide, price: int) -> OrderIntent:
        return OrderIntent(
            user_id=self.user_id,
            symbol=self.symbol,
            side=side,
            price=max(self._settings.price_step, price),
            quantity=self._quantity(),
            order_ttl_ticks=self._settings.order_ttl_ticks,
        )

    def _midpoint(self, snapshot: BookSnapshot) -> int:
        best_bid = snapshot.bids[0].price if snapshot.bids else None
        best_ask = snapshot.asks[0].price if snapshot.asks else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) // 2
        if best_bid is not None:
            return best_bid
        if best_ask is not None:
            return best_ask
        return self._settings.reference_price


class NoiseTrader(BaseTrader):
    """A reproducible, non-predictive trading participant.

    It intentionally has no view of the order book. Its orders represent
    independent participants placing limits around a shared reference price.
    """

    def __init__(self, settings: TraderSettings) -> None:
        super().__init__(settings)

    def next_intents(self, tick: int, snapshot: BookSnapshot) -> tuple[OrderIntent, ...]:
        if not self._is_due(tick):
            return ()

        side = self._random.choice((OrderSide.BUY, OrderSide.SELL))
        offset_steps = self._random.randint(
            -self._settings.max_offset_steps,
            self._settings.max_offset_steps,
        )
        price = self._settings.reference_price + (offset_steps * self._settings.price_step)

        return (self._intent(side, price),)


class MomentumTrader(BaseTrader):
    """Follow the direction of the order-book midpoint between due ticks."""

    def __init__(self, settings: TraderSettings) -> None:
        super().__init__(settings)
        self._previous_midpoint: int | None = None

    def next_intents(self, tick: int, snapshot: BookSnapshot) -> tuple[OrderIntent, ...]:
        if not self._is_due(tick):
            return ()

        midpoint = self._midpoint(snapshot)
        previous_midpoint = self._previous_midpoint
        self._previous_midpoint = midpoint
        if previous_midpoint is None or midpoint == previous_midpoint:
            return ()

        if midpoint > previous_midpoint:
            price = snapshot.asks[0].price if snapshot.asks else midpoint + self._settings.price_step
            return (self._intent(OrderSide.BUY, price),)

        price = snapshot.bids[0].price if snapshot.bids else midpoint - self._settings.price_step
        return (self._intent(OrderSide.SELL, price),)


class MeanReversionTrader(BaseTrader):
    """Trade toward the configured reference price when midpoint deviates."""

    def next_intents(self, tick: int, snapshot: BookSnapshot) -> tuple[OrderIntent, ...]:
        if not self._is_due(tick):
            return ()

        midpoint = self._midpoint(snapshot)
        threshold = self._settings.price_step
        if midpoint <= self._settings.reference_price - threshold:
            price = snapshot.asks[0].price if snapshot.asks else midpoint + threshold
            return (self._intent(OrderSide.BUY, price),)
        if midpoint >= self._settings.reference_price + threshold:
            price = snapshot.bids[0].price if snapshot.bids else midpoint - threshold
            return (self._intent(OrderSide.SELL, price),)
        return ()


class EventReactiveTrader(BaseTrader):
    """Stay dormant until a resolved news-reaction plan is applied."""

    def __init__(self, settings: TraderSettings) -> None:
        super().__init__(settings)
        self._plan: ResolvedReactionPlan | None = None
        self._consumed_indexes: set[int] = set()

    def reaction_candidate(self) -> ReactionCandidate:
        settings = self._settings
        return ReactionCandidate(
            user_id=self.user_id,
            symbol=self.symbol,
            quantity_min=settings.quantity_min,
            quantity_max=settings.quantity_max,
            order_ttl_ticks=settings.order_ttl_ticks,
            interval_ticks=settings.interval_ticks,
            seed=settings.seed,
        )

    def apply_plan(self, plan: ResolvedReactionPlan) -> None:
        if plan.user_id != self.user_id:
            raise ValueError("reaction plan user_id must match the trader")
        if plan.symbol != self.symbol:
            raise ValueError("reaction plan symbol must match the trader")
        self._plan = plan
        self._consumed_indexes = set()

    @property
    def remaining_reaction_orders(self) -> int:
        plan = self._plan
        if plan is None or not plan.activated:
            return 0
        return plan.order_count - len(self._consumed_indexes)

    def drop_late_orders(
        self,
        elapsed_ms: int,
        tick_interval_ms: int,
        max_scheduler_lag_ms: int,
    ) -> int:
        plan = self._plan
        if plan is None or not plan.activated:
            return 0

        dropped = 0
        for index, offset in enumerate(plan.order_tick_offsets):
            if index in self._consumed_indexes:
                continue
            scheduled_ms = offset * tick_interval_ms
            if elapsed_ms - scheduled_ms > max_scheduler_lag_ms:
                self._consumed_indexes.add(index)
                dropped += 1
        return dropped

    def next_intents(self, tick: int, snapshot: BookSnapshot) -> tuple[OrderIntent, ...]:
        plan = self._plan
        if plan is None or not plan.activated:
            return ()

        intents: list[OrderIntent] = []
        for index, offset in enumerate(plan.order_tick_offsets):
            if index in self._consumed_indexes:
                continue
            if max(offset, 1) != tick:
                continue
            self._consumed_indexes.add(index)
            intents.append(self._reaction_intent(plan, index, snapshot))
        return tuple(intents)

    def _reaction_intent(
        self,
        plan: ResolvedReactionPlan,
        index: int,
        snapshot: BookSnapshot,
    ) -> OrderIntent:
        side = plan.sides[index]
        return OrderIntent(
            user_id=self.user_id,
            symbol=self.symbol,
            side=side,
            price=self._reaction_price(side, snapshot),
            quantity=plan.quantities[index],
            order_ttl_ticks=plan.ttl_ticks[index],
        )

    def _reaction_price(self, side: OrderSide, snapshot: BookSnapshot) -> int:
        if side is OrderSide.BUY:
            if snapshot.asks:
                return snapshot.asks[0].price
            fallback = self._settings.reference_price + self._settings.price_step
        elif snapshot.bids:
            return snapshot.bids[0].price
        else:
            fallback = self._settings.reference_price - self._settings.price_step
        return max(self._settings.price_step, fallback)


class LiquidityProvider(BaseTrader):
    """Place one passive bid and ask around the current midpoint each due tick."""

    def next_intents(self, tick: int, snapshot: BookSnapshot) -> tuple[OrderIntent, ...]:
        if not self._is_due(tick):
            return ()

        center = self._midpoint(snapshot)
        max_distance = self._settings.max_offset_steps * self._settings.price_step
        center = min(
            self._settings.reference_price + max_distance,
            max(self._settings.reference_price - max_distance, center),
        )

        return (
            self._intent(OrderSide.BUY, center - self._settings.price_step),
            self._intent(OrderSide.SELL, center + self._settings.price_step),
        )


def build_trader(settings: TraderSettings) -> TradingParticipant:
    traders: dict[str, type[BaseTrader]] = {
        "noise": NoiseTrader,
        "momentum": MomentumTrader,
        "mean_reversion": MeanReversionTrader,
        "liquidity_provider": LiquidityProvider,
        "event_reactive": EventReactiveTrader,
    }
    try:
        trader_class = traders[settings.strategy]
    except KeyError as exc:
        raise ValueError(f"unsupported strategy: {settings.strategy}") from exc
    return trader_class(settings)
