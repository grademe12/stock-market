from collections.abc import Iterable

from exchange.models import TraderProfile
from exchange.participants import NoiseTrader, TraderSettings


def profiles_to_participants(profiles: Iterable[TraderProfile]) -> tuple[NoiseTrader, ...]:
    """Django persistence adapter for the framework-independent bot package."""
    return tuple(
        NoiseTrader(
            TraderSettings(
                user_id=profile.user_id,
                symbol=profile.symbol,
                strategy=profile.strategy,
                reference_price=profile.reference_price,
                price_step=profile.price_step,
                max_offset_steps=profile.max_offset_steps,
                quantity_min=profile.quantity_min,
                quantity_max=profile.quantity_max,
                order_ttl_ticks=profile.order_ttl_ticks,
                interval_ticks=profile.interval_ticks,
                seed=profile.seed,
            )
        )
        for profile in profiles
    )
