from random import Random

from django.core.management.base import BaseCommand, CommandError

from exchange.models import TraderProfile
from exchange.participants import SUPPORTED_STRATEGIES


class Command(BaseCommand):
    help = "Create or update deterministic demo trader profiles."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--count", type=int, default=100)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--strategy", choices=SUPPORTED_STRATEGIES, default="noise")

    def handle(self, *args, **options) -> None:
        count = options["count"]
        strategy = options["strategy"]
        if not 1 <= count <= 1_000:
            raise CommandError("count must be between 1 and 1000")

        random = Random(options["seed"])
        created = 0
        updated = 0
        for index in range(1, count + 1):
            quantity_min = random.randint(1, 5)
            _, was_created = TraderProfile.objects.update_or_create(
                user_id=f"random-{strategy}-user-{index:03d}",
                defaults={
                    "name": f"random-{strategy}-{index:03d}",
                    "strategy": strategy,
                    "enabled": True,
                    "symbol": "005930",
                    "reference_price": random.randrange(65_000, 75_100, 100),
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
                f"strategy={strategy} created={created} updated={updated} "
                f"count={count} seed={options['seed']}"
            )
        )
