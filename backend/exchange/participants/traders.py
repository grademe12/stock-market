from random import Random

from exchange.orderbook import OrderSide
from exchange.participants.types import OrderIntent, SimulationConfig, TraderSettings


class NoiseTrader:
    """A reproducible, non-predictive trading participant.

    It intentionally has no view of the order book. Its orders represent
    independent participants placing limits around a shared reference price.
    """

    def __init__(self, settings: TraderSettings) -> None:
        self.user_id = settings.user_id
        self._settings = settings
        self._random = Random(settings.seed)
        self._phase = settings.seed % settings.interval_ticks

    def next_intent(self, tick: int) -> OrderIntent | None:
        if (tick + self._phase) % self._settings.interval_ticks:
            return None

        side = self._random.choice((OrderSide.BUY, OrderSide.SELL))
        offset_steps = self._random.randint(
            -self._settings.max_offset_steps,
            self._settings.max_offset_steps,
        )
        price = self._settings.reference_price + (offset_steps * self._settings.price_step)

        return OrderIntent(
            user_id=self.user_id,
            symbol=self._settings.symbol,
            side=side,
            price=max(self._settings.price_step, price),
            quantity=self._random.randint(self._settings.quantity_min, self._settings.quantity_max),
            order_ttl_ticks=self._settings.order_ttl_ticks,
        )


def build_noise_traders(config: SimulationConfig) -> tuple[NoiseTrader, ...]:
    return tuple(
        NoiseTrader(
            TraderSettings(
                user_id=f"noise-{index:03d}",
                symbol=config.symbol,
                strategy="noise",
                reference_price=config.reference_price,
                price_step=config.price_step,
                max_offset_steps=config.max_offset_steps,
                quantity_min=config.quantity_min,
                quantity_max=config.quantity_max,
                order_ttl_ticks=config.order_ttl_ticks,
                interval_ticks=1,
                seed=config.seed + index,
            )
        )
        for index in range(1, config.participants + 1)
    )
