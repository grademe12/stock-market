from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from random import Random
from types import MappingProxyType
from typing import Final

from exchange.orderbook import OrderSide


BASIS_POINTS: Final = 10_000
PRESET_VERSION: Final = "1"


def _require_int(name: str, value: int) -> None:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")


def _require_positive_int(name: str, value: int) -> None:
    _require_int(name, value)
    if value < 1:
        raise ValueError(f"{name} must be positive")


def _require_non_negative_int(name: str, value: int) -> None:
    _require_int(name, value)
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _require_bps(name: str, value: int) -> None:
    _require_int(name, value)
    if not 0 <= value <= BASIS_POINTS:
        raise ValueError(f"{name} must be between 0 and 10000")


def _require_range(
    name: str,
    minimum: int,
    maximum: int,
    *,
    lower: int,
    upper: int | None = None,
) -> None:
    _require_int(f"{name} minimum", minimum)
    _require_int(f"{name} maximum", maximum)
    if minimum < lower or maximum < minimum:
        raise ValueError(f"{name} range is invalid")
    if upper is not None and maximum > upper:
        raise ValueError(f"{name} range is invalid")


class EventPreset(StrEnum):
    MINOR_NEWS = "minor_news"
    BREAKING_NEWS = "breaking_news"
    MARKET_PANIC = "market_panic"
    MIXED_REACTION = "mixed_reaction"
    RUMOR = "rumor"


class DirectionHint(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    MIXED = "MIXED"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class NewsShockEvent:
    event_id: str
    symbol: str
    starts_after_ms: int
    preset: EventPreset
    direction_hint: DirectionHint = DirectionHint.NONE
    label: str = ""
    source: str = "fixture"
    seed: int = 42

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.symbol.strip():
            raise ValueError("event_id and symbol must not be blank")
        if not self.source.strip():
            raise ValueError("source must not be blank")
        _require_non_negative_int("starts_after_ms", self.starts_after_ms)
        _require_int("seed", self.seed)
        if not isinstance(self.preset, EventPreset):
            raise ValueError("preset must be an EventPreset")
        if not isinstance(self.direction_hint, DirectionHint):
            raise ValueError("direction_hint must be a DirectionHint")


@dataclass(frozen=True, slots=True)
class ReactionCandidate:
    user_id: str
    symbol: str
    quantity_min: int
    quantity_max: int
    order_ttl_ticks: int
    interval_ticks: int
    seed: int

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.symbol.strip():
            raise ValueError("user_id and symbol must not be blank")
        _require_positive_int("quantity_min", self.quantity_min)
        _require_positive_int("quantity_max", self.quantity_max)
        if self.quantity_max < self.quantity_min:
            raise ValueError("quantity range is invalid")
        _require_positive_int("order_ttl_ticks", self.order_ttl_ticks)
        _require_positive_int("interval_ticks", self.interval_ticks)
        _require_int("seed", self.seed)


@dataclass(frozen=True, slots=True)
class ReactionPreset:
    activation_ratio_bps_min: int
    activation_ratio_bps_max: int
    reaction_delay_ms_min: int
    reaction_delay_ms_max: int
    order_count_min: int
    order_count_max: int
    order_interval_ticks_min: int
    order_interval_ticks_max: int
    default_buy_probability_bps: int
    directional_buy_probability_bps: int
    max_scheduler_lag_ms: int

    def __post_init__(self) -> None:
        _require_range(
            "activation ratio",
            self.activation_ratio_bps_min,
            self.activation_ratio_bps_max,
            lower=0,
            upper=BASIS_POINTS,
        )
        _require_range(
            "reaction delay",
            self.reaction_delay_ms_min,
            self.reaction_delay_ms_max,
            lower=0,
        )
        _require_range(
            "order count",
            self.order_count_min,
            self.order_count_max,
            lower=1,
        )
        _require_range(
            "order interval",
            self.order_interval_ticks_min,
            self.order_interval_ticks_max,
            lower=1,
        )
        _require_bps("default_buy_probability_bps", self.default_buy_probability_bps)
        _require_bps(
            "directional_buy_probability_bps",
            self.directional_buy_probability_bps,
        )
        if self.directional_buy_probability_bps < BASIS_POINTS // 2:
            raise ValueError("directional buy probability must be at least 5000")
        _require_positive_int("max_scheduler_lag_ms", self.max_scheduler_lag_ms)


PRESET_DEFINITIONS: Final[Mapping[EventPreset, ReactionPreset]] = MappingProxyType(
    {
        EventPreset.MINOR_NEWS: ReactionPreset(
            activation_ratio_bps_min=1_000,
            activation_ratio_bps_max=3_000,
            reaction_delay_ms_min=10_000,
            reaction_delay_ms_max=60_000,
            order_count_min=1,
            order_count_max=2,
            order_interval_ticks_min=2,
            order_interval_ticks_max=5,
            default_buy_probability_bps=5_000,
            directional_buy_probability_bps=7_000,
            max_scheduler_lag_ms=5_000,
        ),
        EventPreset.BREAKING_NEWS: ReactionPreset(
            activation_ratio_bps_min=4_000,
            activation_ratio_bps_max=8_000,
            reaction_delay_ms_min=0,
            reaction_delay_ms_max=20_000,
            order_count_min=1,
            order_count_max=4,
            order_interval_ticks_min=1,
            order_interval_ticks_max=3,
            default_buy_probability_bps=5_000,
            directional_buy_probability_bps=8_000,
            max_scheduler_lag_ms=2_000,
        ),
        EventPreset.MARKET_PANIC: ReactionPreset(
            activation_ratio_bps_min=7_000,
            activation_ratio_bps_max=10_000,
            reaction_delay_ms_min=0,
            reaction_delay_ms_max=3_000,
            order_count_min=2,
            order_count_max=6,
            order_interval_ticks_min=1,
            order_interval_ticks_max=2,
            default_buy_probability_bps=5_000,
            directional_buy_probability_bps=9_000,
            max_scheduler_lag_ms=1_000,
        ),
        EventPreset.MIXED_REACTION: ReactionPreset(
            activation_ratio_bps_min=4_000,
            activation_ratio_bps_max=8_000,
            reaction_delay_ms_min=0,
            reaction_delay_ms_max=20_000,
            order_count_min=1,
            order_count_max=4,
            order_interval_ticks_min=1,
            order_interval_ticks_max=3,
            default_buy_probability_bps=5_000,
            directional_buy_probability_bps=5_000,
            max_scheduler_lag_ms=2_000,
        ),
        EventPreset.RUMOR: ReactionPreset(
            activation_ratio_bps_min=1_500,
            activation_ratio_bps_max=5_000,
            reaction_delay_ms_min=10_000,
            reaction_delay_ms_max=120_000,
            order_count_min=1,
            order_count_max=3,
            order_interval_ticks_min=2,
            order_interval_ticks_max=6,
            default_buy_probability_bps=5_000,
            directional_buy_probability_bps=6_500,
            max_scheduler_lag_ms=5_000,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class ResolvedReactionPlan:
    user_id: str
    symbol: str
    activated: bool
    reaction_after_ms: int | None
    order_interval_ticks: int
    buy_probability_bps: int
    sides: tuple[OrderSide, ...]
    quantities: tuple[int, ...]
    ttl_ticks: tuple[int, ...]
    order_tick_offsets: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.symbol.strip():
            raise ValueError("user_id and symbol must not be blank")
        _require_positive_int("order_interval_ticks", self.order_interval_ticks)
        _require_bps("buy_probability_bps", self.buy_probability_bps)
        lengths = {
            len(self.sides),
            len(self.quantities),
            len(self.ttl_ticks),
            len(self.order_tick_offsets),
        }
        if len(lengths) != 1:
            raise ValueError("reaction order sequences must have equal lengths")
        if self.activated != bool(self.sides):
            raise ValueError("activated plans must contain at least one order")
        if self.activated != (self.reaction_after_ms is not None):
            raise ValueError("reaction time must exist only for activated plans")
        if self.reaction_after_ms is not None:
            _require_non_negative_int("reaction_after_ms", self.reaction_after_ms)
        if any(not isinstance(side, OrderSide) for side in self.sides):
            raise ValueError("reaction sides must be BUY or SELL")
        if any(type(quantity) is not int or quantity < 1 for quantity in self.quantities):
            raise ValueError("reaction quantities must be positive integers")
        if any(type(ttl) is not int or ttl < 1 for ttl in self.ttl_ticks):
            raise ValueError("reaction TTLs must be positive integers")
        if any(type(tick) is not int or tick < 0 for tick in self.order_tick_offsets):
            raise ValueError("reaction tick offsets must be non-negative integers")
        if tuple(sorted(self.order_tick_offsets)) != self.order_tick_offsets:
            raise ValueError("reaction tick offsets must be ordered")

    @property
    def order_count(self) -> int:
        return len(self.sides)


@dataclass(frozen=True, slots=True)
class ResolvedEventPlan:
    event: NewsShockEvent
    preset_version: str
    tick_interval_ms: int
    activation_ratio_bps: int
    max_scheduler_lag_ms: int
    reactions: tuple[ResolvedReactionPlan, ...]

    def __post_init__(self) -> None:
        if not self.preset_version.strip():
            raise ValueError("preset_version must not be blank")
        _require_positive_int("tick_interval_ms", self.tick_interval_ms)
        _require_bps("activation_ratio_bps", self.activation_ratio_bps)
        _require_positive_int("max_scheduler_lag_ms", self.max_scheduler_lag_ms)
        user_ids = [reaction.user_id for reaction in self.reactions]
        if len(user_ids) != len(set(user_ids)):
            raise ValueError("reaction plan user_ids must be unique")
        if any(reaction.symbol != self.event.symbol for reaction in self.reactions):
            raise ValueError("reaction plan symbol must match event symbol")

    @property
    def dormant_trader_count(self) -> int:
        return len(self.reactions)

    @property
    def activated_trader_count(self) -> int:
        return sum(reaction.activated for reaction in self.reactions)

    @property
    def planned_order_count(self) -> int:
        return sum(reaction.order_count for reaction in self.reactions)

    def orders_by_tick(self) -> tuple[tuple[int, int], ...]:
        counts = Counter(
            tick
            for reaction in self.reactions
            for tick in reaction.order_tick_offsets
        )
        return tuple(sorted(counts.items()))


class ReactionPlanner:
    """Resolve news reactions once using stable, process-independent randomness."""

    def __init__(self, tick_interval_ms: int) -> None:
        _require_positive_int("tick_interval_ms", tick_interval_ms)
        self._tick_interval_ms = tick_interval_ms
        self._processed_events: dict[str, NewsShockEvent] = {}

    def plan_once(
        self,
        event: NewsShockEvent,
        candidates: Iterable[ReactionCandidate],
    ) -> ResolvedEventPlan | None:
        previous_event = self._processed_events.get(event.event_id)
        if previous_event is not None:
            if previous_event != event:
                raise ValueError("event_id was already used with a different payload")
            return None

        plan = self._resolve(event, tuple(candidates))
        self._processed_events[event.event_id] = event
        return plan

    def _resolve(
        self,
        event: NewsShockEvent,
        candidates: tuple[ReactionCandidate, ...],
    ) -> ResolvedEventPlan:
        _require_unique_user_ids(candidates)
        eligible = tuple(
            sorted(
                (candidate for candidate in candidates if candidate.symbol == event.symbol),
                key=lambda candidate: candidate.user_id,
            )
        )
        preset = PRESET_DEFINITIONS[event.preset]
        event_random = Random(_stable_seed(event.seed, event.event_id, "event"))
        activation_ratio_bps = event_random.randint(
            preset.activation_ratio_bps_min,
            preset.activation_ratio_bps_max,
        )
        activated_count = _activation_count(len(eligible), activation_ratio_bps)
        activated_ids = {
            candidate.user_id
            for candidate in sorted(
                eligible,
                key=lambda candidate: _stable_seed(
                    event.seed,
                    event.event_id,
                    "activation",
                    candidate.user_id,
                    candidate.seed,
                ),
            )[:activated_count]
        }
        buy_probability_bps = _buy_probability(event, preset, event_random)
        event_start_tick = _ceil_div(event.starts_after_ms, self._tick_interval_ms)

        reactions = tuple(
            self._resolve_candidate(
                event=event,
                preset=preset,
                candidate=candidate,
                activated=candidate.user_id in activated_ids,
                buy_probability_bps=buy_probability_bps,
                event_start_tick=event_start_tick,
            )
            for candidate in eligible
        )
        return ResolvedEventPlan(
            event=event,
            preset_version=PRESET_VERSION,
            tick_interval_ms=self._tick_interval_ms,
            activation_ratio_bps=activation_ratio_bps,
            max_scheduler_lag_ms=preset.max_scheduler_lag_ms,
            reactions=reactions,
        )

    def _resolve_candidate(
        self,
        *,
        event: NewsShockEvent,
        preset: ReactionPreset,
        candidate: ReactionCandidate,
        activated: bool,
        buy_probability_bps: int,
        event_start_tick: int,
    ) -> ResolvedReactionPlan:
        if not activated:
            return ResolvedReactionPlan(
                user_id=candidate.user_id,
                symbol=candidate.symbol,
                activated=False,
                reaction_after_ms=None,
                order_interval_ticks=candidate.interval_ticks,
                buy_probability_bps=buy_probability_bps,
                sides=(),
                quantities=(),
                ttl_ticks=(),
                order_tick_offsets=(),
            )

        random = Random(
            _stable_seed(
                event.seed,
                event.event_id,
                "reaction",
                candidate.user_id,
                candidate.seed,
            )
        )
        reaction_after_ms = random.randint(
            preset.reaction_delay_ms_min,
            preset.reaction_delay_ms_max,
        )
        order_count = random.randint(preset.order_count_min, preset.order_count_max)
        order_interval_ticks = max(
            candidate.interval_ticks,
            random.randint(
                preset.order_interval_ticks_min,
                preset.order_interval_ticks_max,
            ),
        )
        first_order_tick = event_start_tick + _ceil_div(
            reaction_after_ms,
            self._tick_interval_ms,
        )
        sides = tuple(
            OrderSide.BUY
            if random.randrange(BASIS_POINTS) < buy_probability_bps
            else OrderSide.SELL
            for _ in range(order_count)
        )
        quantities = tuple(
            random.randint(candidate.quantity_min, candidate.quantity_max)
            for _ in range(order_count)
        )
        return ResolvedReactionPlan(
            user_id=candidate.user_id,
            symbol=candidate.symbol,
            activated=True,
            reaction_after_ms=reaction_after_ms,
            order_interval_ticks=order_interval_ticks,
            buy_probability_bps=buy_probability_bps,
            sides=sides,
            quantities=quantities,
            ttl_ticks=(candidate.order_ttl_ticks,) * order_count,
            order_tick_offsets=tuple(
                first_order_tick + (index * order_interval_ticks)
                for index in range(order_count)
            ),
        )


def _buy_probability(
    event: NewsShockEvent,
    preset: ReactionPreset,
    random: Random,
) -> int:
    if event.direction_hint is DirectionHint.BUY:
        return preset.directional_buy_probability_bps
    if event.direction_hint is DirectionHint.SELL:
        return BASIS_POINTS - preset.directional_buy_probability_bps
    if event.direction_hint is DirectionHint.MIXED:
        return BASIS_POINTS // 2
    if event.preset is EventPreset.MARKET_PANIC:
        return random.choice(
            (
                preset.directional_buy_probability_bps,
                BASIS_POINTS - preset.directional_buy_probability_bps,
            )
        )
    return preset.default_buy_probability_bps


def _activation_count(candidate_count: int, activation_ratio_bps: int) -> int:
    if not candidate_count or not activation_ratio_bps:
        return 0
    rounded_count = (
        (candidate_count * activation_ratio_bps) + (BASIS_POINTS // 2)
    ) // BASIS_POINTS
    return min(candidate_count, max(1, rounded_count))


def _stable_seed(*parts: object) -> int:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(sha256(payload).digest()[:16], "big")


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def _require_unique_user_ids(candidates: tuple[ReactionCandidate, ...]) -> None:
    user_ids = [candidate.user_id for candidate in candidates]
    if len(user_ids) != len(set(user_ids)):
        raise ValueError("reaction candidate user_ids must be unique")
