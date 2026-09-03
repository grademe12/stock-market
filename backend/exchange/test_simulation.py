from datetime import date

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from exchange.models import MarketDaily, Symbol
from exchange.simulation import (
    FALLBACK_SYMBOL,
    is_simulated_symbol,
    reset_simulated_tickers_cache,
    simulated_tickers,
)


class SimulatedTickerTests(TestCase):
    def setUp(self) -> None:
        reset_simulated_tickers_cache()

    def test_fallback_symbol_is_used_without_reference_data(self):
        self.assertEqual(simulated_tickers(), (FALLBACK_SYMBOL,))
        self.assertTrue(is_simulated_symbol(FALLBACK_SYMBOL))
        self.assertFalse(is_simulated_symbol("000660"))

    @override_settings(SIMULATION_SYMBOL_LIMIT=2)
    def test_latest_trade_date_selects_top_ranked_symbols(self):
        self._create_daily("005930", "삼성전자", date(2026, 8, 27), rank=1)
        self._create_daily("000660", "SK하이닉스", date(2026, 8, 28), rank=2)
        self._create_daily("035420", "NAVER", date(2026, 8, 28), rank=1)
        self._create_daily("005930", "삼성전자", date(2026, 8, 28), rank=3)

        self.assertEqual(simulated_tickers(), ("035420", "000660"))
        self.assertTrue(is_simulated_symbol("000660"))
        self.assertFalse(is_simulated_symbol("005930"))

    @override_settings(SIMULATION_SYMBOL_LIMIT=2)
    def test_universe_is_read_from_the_database_once(self):
        self._create_daily("035420", "NAVER", date(2026, 8, 28), rank=1)
        self._create_daily("000660", "SK하이닉스", date(2026, 8, 28), rank=2)

        with CaptureQueriesContext(connection) as first_read:
            self.assertEqual(simulated_tickers(), ("035420", "000660"))
        with CaptureQueriesContext(connection) as cached_read:
            self.assertEqual(simulated_tickers(), ("035420", "000660"))
            self.assertTrue(is_simulated_symbol("000660"))

        self.assertGreater(len(first_read), 0)
        self.assertEqual(len(cached_read), 0)

    @staticmethod
    def _create_daily(ticker: str, name: str, trade_date: date, *, rank: int) -> None:
        symbol, _ = Symbol.objects.update_or_create(
            ticker=ticker,
            defaults={"name": name, "market": Symbol.Market.KOSPI},
        )
        MarketDaily.objects.create(
            symbol=symbol,
            trade_date=trade_date,
            close_price=70_000,
            volume=1_000,
            trading_value=1_000_000 - rank,
            trading_value_rank=rank,
            source_payload={},
        )
