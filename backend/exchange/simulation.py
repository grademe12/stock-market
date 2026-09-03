from threading import Lock

from django.conf import settings
from django.db.models import Max
from django.db.utils import OperationalError, ProgrammingError

from exchange.models import MarketDaily

FALLBACK_SYMBOL = "005930"

_lock = Lock()
_cached_tickers: tuple[str, ...] | None = None
_cached_limit: int | None = None


def simulation_symbol_limit() -> int:
    return settings.SIMULATION_SYMBOL_LIMIT


def reset_simulated_tickers_cache() -> None:
    """Drop the in-process universe so the next read reloads from MarketDaily."""
    global _cached_tickers, _cached_limit
    with _lock:
        _cached_tickers = None
        _cached_limit = None


def _load_simulated_tickers() -> tuple[str, ...]:
    latest_trade_date = MarketDaily.objects.aggregate(latest=Max("trade_date"))["latest"]
    if latest_trade_date is None:
        return (FALLBACK_SYMBOL,)
    tickers = list(
        MarketDaily.objects.filter(trade_date=latest_trade_date)
        .order_by("trading_value_rank", "symbol_id")
        .values_list("symbol_id", flat=True)[: simulation_symbol_limit()]
    )
    return tuple(tickers)


def load_simulated_tickers() -> tuple[str, ...]:
    """Read the current universe from MarketDaily and store it in process memory."""
    global _cached_tickers, _cached_limit
    limit = simulation_symbol_limit()
    tickers = _load_simulated_tickers()
    with _lock:
        _cached_tickers = tickers
        _cached_limit = limit
        return _cached_tickers


def simulated_tickers() -> tuple[str, ...]:
    """Return tickers the in-process matcher will accept.

    The set is loaded once per process (or when SIMULATION_SYMBOL_LIMIT
    changes). When KRX daily data exists this is the latest trade date's
    top N by trading-value rank. Without reference data, only the
    development fallback symbol stays tradable so unit tests keep working.
    """
    limit = simulation_symbol_limit()
    with _lock:
        if _cached_tickers is not None and _cached_limit == limit:
            return _cached_tickers
    return load_simulated_tickers()


def is_simulated_symbol(ticker: str) -> bool:
    return ticker in simulated_tickers()


def preload_simulated_tickers() -> None:
    """Warm the cache at process start. Ignore missing tables during migrate."""
    try:
        load_simulated_tickers()
    except (OperationalError, ProgrammingError):
        reset_simulated_tickers_cache()
