from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from exchange.reference_data import (
    KrxApiError,
    KrxConfigurationError,
    import_latest_kospi_top100,
)


class Command(BaseCommand):
    help = "Import the latest confirmed KOSPI top 100 symbols by trading value."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--trade-date", help="Explicit KRX trade date in YYYYMMDD format")

    def handle(self, *args, **options) -> None:
        trade_date = None
        if options["trade_date"]:
            try:
                trade_date = datetime.strptime(options["trade_date"], "%Y%m%d").date()
            except ValueError as exc:
                raise CommandError("trade-date must use YYYYMMDD format") from exc

        try:
            result = import_latest_kospi_top100(requested_trade_date=trade_date)
        except (KrxConfigurationError, KrxApiError) as exc:
            raise CommandError(str(exc)) from exc

        top_summary = ", ".join(
            f"{index}:{record.ticker} {record.name}"
            for index, record in enumerate(result.top_records, start=1)
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"imported KOSPI top100: trade_date={result.trade_date:%Y-%m-%d} "
                f"count={result.selected_count} run_id={result.run_id}"
            )
        )
        self.stdout.write(f"top10: {top_summary}")
