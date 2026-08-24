from collections.abc import Iterable
from dataclasses import dataclass, field
import logging
from typing import Protocol

from exchange.participants import (
    EventReactiveTrader,
    NewsShockEvent,
    ReactionPlanner,
    ResolvedEventPlan,
)
from exchange.participants.types import OrderIntent, TradingParticipant


class Clock(Protocol):
    def monotonic_ms(self) -> int: ...


class SystemClock:
    def monotonic_ms(self) -> int:
        import time

        return time.monotonic_ns() // 1_000_000


class FakeClock:
    def __init__(self, now_ms: int = 0) -> None:
        self._now_ms = now_ms

    def monotonic_ms(self) -> int:
        return self._now_ms

    def advance(self, milliseconds: int) -> None:
        if milliseconds < 0:
            raise ValueError("clock cannot move backwards")
        self._now_ms += milliseconds


@dataclass
class EventRunState:
    event_id: str
    planned: int = 0
    submitted: int = 0
    dropped: int = 0
    activated: int = 0
    first_reaction_logged: bool = False
    completed: bool = False
    user_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class CoordinatorStatus:
    events_received_total: int
    events_deduplicated_total: int
    dormant_traders_total: int
    activated_traders_total: int
    reactions_planned_total: int
    reactions_submitted_total: int
    reactions_dropped_total: int
    scheduler_lag_max_ms: int


class SyntheticEventSource:
    def __init__(self, events: Iterable[NewsShockEvent]) -> None:
        self._events = tuple(
            sorted(events, key=lambda event: (event.starts_after_ms, event.event_id))
        )
        self._next_index = 0

    def due_events(self, elapsed_ms: int) -> tuple[NewsShockEvent, ...]:
        due: list[NewsShockEvent] = []
        while (
            self._next_index < len(self._events)
            and self._events[self._next_index].starts_after_ms <= elapsed_ms
        ):
            due.append(self._events[self._next_index])
            self._next_index += 1
        return tuple(due)


class EventCoordinator:
    """Apply fixture news events to dormant traders without touching baseline flow."""

    def __init__(
        self,
        events: Iterable[NewsShockEvent],
        participants: Iterable[TradingParticipant],
        tick_interval_ms: int,
        clock: Clock | None = None,
    ) -> None:
        if tick_interval_ms < 1:
            raise ValueError("tick_interval_ms must be positive")

        self._tick_interval_ms = tick_interval_ms
        self._clock = clock or SystemClock()
        self._started_ms = self._clock.monotonic_ms()
        self._source = SyntheticEventSource(events)
        self._traders = {
            participant.user_id: participant
            for participant in participants
            if isinstance(participant, EventReactiveTrader)
        }
        self._planner = ReactionPlanner(tick_interval_ms)
        self._trader_event: dict[str, str] = {}
        self._event_max_lag: dict[str, int] = {}
        self._runs: dict[str, EventRunState] = {}
        self._events_received = 0
        self._events_deduplicated = 0
        self._activated_traders = 0
        self._reactions_planned = 0
        self._reactions_submitted = 0
        self._reactions_dropped = 0
        self._scheduler_lag_max_ms = 0

    def elapsed_ms(self) -> int:
        return self._clock.monotonic_ms() - self._started_ms

    def before_tick(self, tick: int) -> None:
        elapsed = self.elapsed_ms()
        for event in self._source.due_events(elapsed):
            self._apply_event(event)
        self._drop_late_orders(elapsed)
        for event_id in tuple(self._runs):
            self._maybe_complete(event_id)

    def after_submit(self, intent: OrderIntent, submitted: bool, tick: int) -> None:
        event_id = self._trader_event.get(intent.user_id)
        if event_id is None:
            return

        run = self._runs[event_id]
        if not submitted:
            self._record_drops(event_id, 1)
            self._maybe_complete(event_id)
            return

        self._reactions_submitted += 1
        run.submitted += 1
        scheduled_ms = tick * self._tick_interval_ms
        lag = max(0, self.elapsed_ms() - scheduled_ms)
        self._scheduler_lag_max_ms = max(self._scheduler_lag_max_ms, lag)
        if not run.first_reaction_logged:
            run.first_reaction_logged = True
            logging.info(
                "event=news_first_reaction event_id=%s user_id=%s tick=%s",
                event_id,
                intent.user_id,
                tick,
            )
        self._maybe_complete(event_id)

    def status(self) -> CoordinatorStatus:
        return CoordinatorStatus(
            events_received_total=self._events_received,
            events_deduplicated_total=self._events_deduplicated,
            dormant_traders_total=len(self._traders),
            activated_traders_total=self._activated_traders,
            reactions_planned_total=self._reactions_planned,
            reactions_submitted_total=self._reactions_submitted,
            reactions_dropped_total=self._reactions_dropped,
            scheduler_lag_max_ms=self._scheduler_lag_max_ms,
        )

    def _apply_event(self, event: NewsShockEvent) -> None:
        logging.info(
            "event=news_received event_id=%s symbol=%s preset=%s seed=%s starts_after_ms=%s",
            event.event_id,
            event.symbol,
            event.preset,
            event.seed,
            event.starts_after_ms,
        )
        candidates = tuple(
            trader.reaction_candidate()
            for trader in self._traders.values()
            if trader.remaining_reaction_orders == 0
        )
        plan = self._planner.plan_once(event, candidates)
        if plan is None:
            self._events_deduplicated += 1
            logging.info("event=news_deduplicated event_id=%s", event.event_id)
            return

        self._events_received += 1
        self._event_max_lag[event.event_id] = plan.max_scheduler_lag_ms
        run = self._runs.setdefault(event.event_id, EventRunState(event_id=event.event_id))
        self._assign_plans(plan, run)
        logging.info(
            "event=news_activated event_id=%s dormant=%s activated=%s planned_orders=%s "
            "preset_version=%s activation_ratio_bps=%s",
            event.event_id,
            plan.dormant_trader_count,
            plan.activated_trader_count,
            plan.planned_order_count,
            plan.preset_version,
            plan.activation_ratio_bps,
        )

    def _assign_plans(self, plan: ResolvedEventPlan, run: EventRunState) -> None:
        for reaction in plan.reactions:
            trader = self._traders.get(reaction.user_id)
            if trader is None:
                continue
            self._abandon_previous_event(trader, reaction.user_id)
            trader.apply_plan(reaction)
            if not reaction.activated:
                continue
            run.activated += 1
            run.planned += reaction.order_count
            run.user_ids.add(reaction.user_id)
            self._trader_event[reaction.user_id] = plan.event.event_id
            self._activated_traders += 1
            self._reactions_planned += reaction.order_count

    def _abandon_previous_event(self, trader: EventReactiveTrader, user_id: str) -> None:
        previous_event_id = self._trader_event.pop(user_id, None)
        leftover = trader.remaining_reaction_orders
        if previous_event_id is None or leftover == 0:
            return
        self._record_drops(previous_event_id, leftover)
        self._maybe_complete(previous_event_id)

    def _drop_late_orders(self, elapsed_ms: int) -> None:
        for user_id, trader in self._traders.items():
            event_id = self._trader_event.get(user_id)
            if event_id is None:
                continue
            dropped = trader.drop_late_orders(
                elapsed_ms,
                self._tick_interval_ms,
                self._event_max_lag[event_id],
            )
            if dropped:
                self._record_drops(event_id, dropped)

    def _record_drops(self, event_id: str, dropped: int) -> None:
        self._reactions_dropped += dropped
        self._runs[event_id].dropped += dropped

    def _maybe_complete(self, event_id: str) -> None:
        run = self._runs[event_id]
        if run.completed or run.planned == 0:
            return
        remaining = sum(
            trader.remaining_reaction_orders
            for user_id, trader in self._traders.items()
            if self._trader_event.get(user_id) == event_id
        )
        if remaining:
            return
        run.completed = True
        logging.info(
            "event=news_completed event_id=%s planned=%s submitted=%s dropped=%s",
            event_id,
            run.planned,
            run.submitted,
            run.dropped,
        )
