from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from exchange.models import MarketDaily, ReferenceImportRun, Symbol
from exchange.reference_data.krx import KrxApiError, KrxDailyRecord, KrxOpenApiClient


@dataclass(frozen=True, slots=True)
class ImportResult:
    run_id: str
    trade_date: date
    selected_count: int
    top_records: tuple[KrxDailyRecord, ...]


def _select_top100(records: tuple[KrxDailyRecord, ...]) -> tuple[KrxDailyRecord, ...]:
    eligible = tuple(record for record in records if record.trading_value > 0)
    selected = tuple(
        sorted(
            eligible,
            key=lambda record: (-record.trading_value, -record.volume, record.ticker),
        )[:100]
    )
    if len(selected) != 100:
        raise KrxApiError(f"KRX KOSPI response must contain at least 100 traded symbols; got {len(selected)}")
    return selected


def _resolve_trade_date(
    client: KrxOpenApiClient,
    requested_trade_date: date | None,
    *,
    lookback_days: int,
) -> tuple[date, tuple[KrxDailyRecord, ...]]:
    if requested_trade_date is not None:
        records = client.fetch_daily(requested_trade_date)
        if not records:
            raise KrxApiError(f"KRX returned no rows for {requested_trade_date:%Y-%m-%d}")
        return requested_trade_date, records

    candidate = timezone.localdate() - timedelta(days=1)
    for _ in range(lookback_days):
        records = client.fetch_daily(candidate)
        if records:
            return candidate, records
        candidate -= timedelta(days=1)

    raise KrxApiError(f"KRX returned no completed trading day within {lookback_days} days")


def import_latest_kospi_top100(
    *,
    client: KrxOpenApiClient | None = None,
    requested_trade_date: date | None = None,
    lookback_days: int = 10,
) -> ImportResult:
    client = client or KrxOpenApiClient()
    run = ReferenceImportRun.objects.create(
        trade_date=requested_trade_date,
        status=ReferenceImportRun.Status.RUNNING,
    )

    try:
        trade_date, records = _resolve_trade_date(
            client,
            requested_trade_date,
            lookback_days=lookback_days,
        )
        selected = _select_top100(records)

        with transaction.atomic():
            selected_tickers = tuple(record.ticker for record in selected)
            MarketDaily.objects.filter(trade_date=trade_date).exclude(
                symbol_id__in=selected_tickers
            ).delete()

            for rank, record in enumerate(selected, start=1):
                symbol, _ = Symbol.objects.update_or_create(
                    ticker=record.ticker,
                    defaults={
                        "name": record.name,
                        "market": Symbol.Market.KOSPI,
                    },
                )
                MarketDaily.objects.update_or_create(
                    symbol=symbol,
                    trade_date=trade_date,
                    defaults={
                        "close_price": record.close_price,
                        "volume": record.volume,
                        "trading_value": record.trading_value,
                        "trading_value_rank": rank,
                        "source": "krx_open_api",
                        "source_payload": record.source_payload,
                    },
                )

            run.trade_date = trade_date
            run.status = ReferenceImportRun.Status.SUCCESS
            run.selected_count = len(selected)
            run.error_message = ""
            run.finished_at = timezone.now()
            run.save(
                update_fields=(
                    "trade_date",
                    "status",
                    "selected_count",
                    "error_message",
                    "finished_at",
                )
            )
    except Exception as exc:
        run.status = ReferenceImportRun.Status.FAILED
        run.error_message = str(exc)[:2_000]
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "error_message", "finished_at"))
        raise

    return ImportResult(
        run_id=str(run.id),
        trade_date=trade_date,
        selected_count=len(selected),
        top_records=selected[:10],
    )
