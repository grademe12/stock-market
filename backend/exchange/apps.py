import sys

from django.apps import AppConfig


class ExchangeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "exchange"

    def ready(self) -> None:
        if len(sys.argv) >= 2 and sys.argv[1] == "test":
            return
        from exchange.simulation import preload_simulated_tickers

        preload_simulated_tickers()
