from random import Random

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from exchange.models import MarketDaily, TraderProfile
from exchange.participants import SUPPORTED_STRATEGIES
from exchange.simulation import FALLBACK_SYMBOL, is_simulated_symbol


class Command(BaseCommand):
    help = "Create or update deterministic demo trader profiles."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--count", type=int, default=100)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--strategy", choices=SUPPORTED_STRATEGIES, default="noise")
        parser.add_argument("--symbol", default=FALLBACK_SYMBOL)

    def handle(self, *args, **options) -> None:
        count = options["count"]
        strategy = options["strategy"]
        symbol = str(options["symbol"]).strip()
        if not 1 <= count <= 1_000:
            raise CommandError("count must be between 1 and 1000")
        if not is_simulated_symbol(symbol):
            raise CommandError(f"symbol {symbol} is not in the current simulation set")

        random = Random(options["seed"])
        reference_price_center = self._reference_price_center(symbol)
        created = 0
        updated = 0
        for index in range(1, count + 1):
            quantity_min = random.randint(1, 5)
            user_key = (
                f"random-{strategy}-user-{index:03d}"
                if symbol == FALLBACK_SYMBOL
                else f"random-{strategy}-{symbol}-user-{index:03d}"
            )
            name = (
                f"random-{strategy}-{index:03d}"
                if symbol == FALLBACK_SYMBOL
                else f"random-{strategy}-{symbol}-{index:03d}"
            )
            _, was_created = TraderProfile.objects.update_or_create(
                user_id=user_key,
                defaults={
                    "name": name,
                    "strategy": strategy,
                    "enabled": True,
                    "symbol": symbol,
                    "reference_price": self._reference_price(random, reference_price_center),
                    "price_step": random.choice((50, 100, 500)),
                    "max_offset_steps": random.randint(0, 10),
                    "quantity_min": quantity_min,
                    "quantity_max": random.randint(quantity_min, 15),
                    "order_ttl_ticks": random.randint(1, 10),
                    "interval_ticks": random.randint(1, 5),
                    "seed": random.randint(1, 2_147_483_647),
                },
            )
            created += was_created
            updated += not was_created

        self.stdout.write(
            self.style.SUCCESS(
                "seeded demo traders: "
                f"strategy={strategy} symbol={symbol} created={created} updated={updated} "
                f"count={count} seed={options['seed']}"
            )
        )

    def _reference_price_center(self, symbol: str) -> int:
        latest_trade_date = MarketDaily.objects.filter(symbol_id=symbol).aggregate(
            latest=Max("trade_date")
        )["latest"]
        if latest_trade_date is None:
            return 70_000
        close_price = (
            MarketDaily.objects.filter(symbol_id=symbol, trade_date=latest_trade_date)
            .values_list("close_price", flat=True)
            .first()
        )
        return close_price or 70_000

    @staticmethod
    def _reference_price(random: Random, center: int) -> int:
        if center == 70_000:
            return random.randrange(65_000, 75_100, 100)
        step = 100
        low = max(step, center - (5 * step))
        high = center + (5 * step)
        return random.randrange(low, high + step, step)
