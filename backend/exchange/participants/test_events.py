from django.test import SimpleTestCase

from exchange.orderbook import OrderSide
from exchange.participants import (
    DirectionHint,
    EventPreset,
    NewsShockEvent,
    PRESET_DEFINITIONS,
    ReactionCandidate,
    ReactionPlanner,
)


class ReactionPlannerTests(SimpleTestCase):
    symbol = "005930"

    def event(self, **overrides) -> NewsShockEvent:
        values = {
            "event_id": "news-001",
            "symbol": self.symbol,
            "starts_after_ms": 3_000,
            "preset": EventPreset.BREAKING_NEWS,
            "direction_hint": DirectionHint.MIXED,
            "label": "breaking news fixture",
            "source": "fixture",
            "seed": 42,
        }
        values.update(overrides)
        return NewsShockEvent(**values)

    def candidates(self, count: int = 20) -> tuple[ReactionCandidate, ...]:
        return tuple(
            ReactionCandidate(
                user_id=f"event-reactive-{index:03d}",
                symbol=self.symbol,
                quantity_min=1,
                quantity_max=5,
                order_ttl_ticks=3,
                interval_ticks=1,
                seed=1_000 + index,
            )
            for index in range(1, count + 1)
        )

    def test_same_inputs_produce_the_same_process_independent_plan(self) -> None:
        event = self.event()
        candidates = self.candidates()

        first = ReactionPlanner(tick_interval_ms=100).plan_once(event, candidates)
        second = ReactionPlanner(tick_interval_ms=100).plan_once(
            event,
            tuple(reversed(candidates)),
        )

        self.assertEqual(first, second)

    def test_different_seed_changes_the_resolved_plan(self) -> None:
        candidates = self.candidates()

        first = ReactionPlanner(100).plan_once(self.event(seed=1), candidates)
        second = ReactionPlanner(100).plan_once(self.event(seed=2), candidates)

        self.assertNotEqual(first, second)

    def test_plan_activates_only_the_resolved_subset_and_builds_orders(self) -> None:
        event = self.event(direction_hint=DirectionHint.BUY)
        plan = ReactionPlanner(tick_interval_ms=100).plan_once(
            event,
            self.candidates(),
        )

        self.assertIsNotNone(plan)
        preset = PRESET_DEFINITIONS[event.preset]
        self.assertGreaterEqual(
            plan.activation_ratio_bps,
            preset.activation_ratio_bps_min,
        )
        self.assertLessEqual(
            plan.activation_ratio_bps,
            preset.activation_ratio_bps_max,
        )
        self.assertGreater(plan.activated_trader_count, 0)
        self.assertLess(plan.activated_trader_count, plan.dormant_trader_count)
        self.assertGreater(plan.planned_order_count, plan.activated_trader_count - 1)

        for reaction in plan.reactions:
            if not reaction.activated:
                self.assertEqual(reaction.order_count, 0)
                continue
            self.assertEqual(
                reaction.buy_probability_bps,
                preset.directional_buy_probability_bps,
            )
            self.assertEqual(reaction.order_count, len(reaction.order_tick_offsets))
            self.assertGreaterEqual(reaction.order_tick_offsets[0], 30)
            self.assertTrue(
                all(1 <= quantity <= 5 for quantity in reaction.quantities)
            )
            self.assertEqual(
                reaction.ttl_ticks,
                (3,) * reaction.order_count,
            )

        self.assertEqual(
            sum(count for _, count in plan.orders_by_tick()),
            plan.planned_order_count,
        )

    def test_mixed_direction_uses_equal_buy_probability(self) -> None:
        plan = ReactionPlanner(100).plan_once(
            self.event(direction_hint=DirectionHint.MIXED),
            self.candidates(),
        )

        self.assertTrue(
            all(
                reaction.buy_probability_bps == 5_000
                for reaction in plan.reactions
            )
        )
        sides = {
            side
            for reaction in plan.reactions
            for side in reaction.sides
        }
        self.assertEqual(sides, {OrderSide.BUY, OrderSide.SELL})

    def test_candidates_for_other_symbols_are_not_planned(self) -> None:
        candidates = self.candidates(2) + (
            ReactionCandidate(
                user_id="other-symbol",
                symbol="000660",
                quantity_min=1,
                quantity_max=1,
                order_ttl_ticks=1,
                interval_ticks=1,
                seed=7,
            ),
        )

        plan = ReactionPlanner(100).plan_once(self.event(), candidates)

        self.assertEqual(
            [reaction.user_id for reaction in plan.reactions],
            ["event-reactive-001", "event-reactive-002"],
        )

    def test_duplicate_event_is_idempotent_but_conflicting_payload_is_rejected(self) -> None:
        planner = ReactionPlanner(100)
        event = self.event()
        candidates = self.candidates()

        first = planner.plan_once(event, candidates)
        duplicate = planner.plan_once(event, candidates)

        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        with self.assertRaisesMessage(ValueError, "different payload"):
            planner.plan_once(self.event(seed=99), candidates)

    def test_duplicate_candidate_user_id_is_rejected(self) -> None:
        candidate = self.candidates(1)[0]

        with self.assertRaisesMessage(ValueError, "user_ids must be unique"):
            ReactionPlanner(100).plan_once(self.event(), (candidate, candidate))

    def test_event_and_candidate_validation_reject_invalid_values(self) -> None:
        with self.assertRaisesMessage(ValueError, "starts_after_ms"):
            self.event(starts_after_ms=-1)
        with self.assertRaisesMessage(ValueError, "preset"):
            self.event(preset="breaking_news")
        with self.assertRaisesMessage(ValueError, "quantity range"):
            ReactionCandidate(
                user_id="event-reactive-invalid",
                symbol=self.symbol,
                quantity_min=2,
                quantity_max=1,
                order_ttl_ticks=1,
                interval_ticks=1,
                seed=1,
            )

    def test_tick_interval_must_be_positive_integer(self) -> None:
        for value in (0, -1, True):
            with self.subTest(value=value):
                with self.assertRaisesMessage(ValueError, "tick_interval_ms"):
                    ReactionPlanner(value)
