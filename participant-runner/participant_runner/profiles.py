from collections.abc import Iterable
from typing import Any

from exchange.participants.traders import build_trader
from exchange.participants.types import TraderSettings, TradingParticipant


class InvalidTraderProfileError(ValueError):
    pass


def build_participants(
    profiles: Iterable[dict[str, Any]],
    trader_ids: tuple[str, ...] = (),
    max_traders: int | None = None,
) -> tuple[TradingParticipant, ...]:
    selected_ids = set(trader_ids)
    selected_profiles = [
        profile
        for profile in profiles
        if profile.get("enabled") and (not selected_ids or str(profile.get("id")) in selected_ids)
    ]

    if selected_ids:
        found_ids = {str(profile.get("id")) for profile in selected_profiles}
        if found_ids != selected_ids:
            raise InvalidTraderProfileError("each selected trader must exist and be enabled")

    if max_traders is not None:
        selected_profiles = selected_profiles[:max_traders]

    try:
        return tuple(
            build_trader(
                TraderSettings(
                    user_id=str(profile["user_id"]),
                    symbol=str(profile["symbol"]),
                    strategy=str(profile["strategy"]),
                    reference_price=int(profile["reference_price"]),
                    price_step=int(profile["price_step"]),
                    max_offset_steps=int(profile["max_offset_steps"]),
                    quantity_min=int(profile["quantity_min"]),
                    quantity_max=int(profile["quantity_max"]),
                    order_ttl_ticks=int(profile["order_ttl_ticks"]),
                    interval_ticks=int(profile["interval_ticks"]),
                    seed=int(profile["seed"]),
                )
            )
            for profile in selected_profiles
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTraderProfileError("trader profile has invalid settings") from exc
