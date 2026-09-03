from django.conf import settings
from django.db.models import Max

from exchange.models import MarketDaily

FALLBACK_SYMBOL = "005930"


def simulation_symbol_limit() -> int:
    return settings.SIMULATION_SYMBOL_LIMIT


def simulated_tickers() -> tuple[str, ...]:
    """Return tickers the in-process matcher will accept.

    When KRX daily data exists this is the latest trade date's top N by
    trading-value rank. Without reference data, only the development
    fallback symbol stays tradable so unit tests keep working.
    """
    latest_trade_date = MarketDaily.objects.aggregate(latest=Max("trade_date"))["latest"]
    if latest_trade_date is None:
        return (FALLBACK_SYMBOL,)
    tickers = list(
        MarketDaily.objects.filter(trade_date=latest_trade_date)
        .order_by("trading_value_rank", "symbol_id")
        .values_list("symbol_id", flat=True)[: simulation_symbol_limit()]
    )
    return tuple(tickers)


def is_simulated_symbol(ticker: str) -> bool:
    return ticker in simulated_tickers()
