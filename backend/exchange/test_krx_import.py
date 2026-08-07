from datetime import date, timedelta
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from exchange.models import MarketDaily, ReferenceImportRun, Symbol
from exchange.reference_data import (
    KrxApiError,
    KrxConfigurationError,
    KrxDailyRecord,
    KrxOpenApiClient,
    import_latest_kospi_top100,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body


class KrxOpenApiClientTests(SimpleTestCase):
    trade_date = date(2026, 7, 27)

    def test_api_key_is_required(self):
        client = KrxOpenApiClient(api_key="")

        with self.assertRaisesMessage(KrxConfigurationError, "KRX_API_KEY is required"):
            client.fetch_daily(self.trade_date)

    def test_daily_response_is_normalized(self):
        captured_request = None

        def opener(request, *, timeout):
            nonlocal captured_request
            captured_request = request
            self.assertEqual(timeout, 3)
            return FakeResponse(
                {
                    "OutBlock_1": [
                        {
                            "BAS_DD": "20260727",
                            "ISU_CD": "00104K",
                            "ISU_NM": "CJ4우(전환)",
                            "MKT_NM": "KOSPI",
                            "TDD_CLSPRC": "70,000",
                            "ACC_TRDVOL": "1,234",
                            "ACC_TRDVAL": "86,380,000",
                        },
                    ],
                }
            )

        client = KrxOpenApiClient(api_key="test-key", timeout_seconds=3, opener=opener)

        records = client.fetch_daily(self.trade_date)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].ticker, "00104K")
        self.assertEqual(records[0].close_price, 70_000)
        self.assertEqual(records[0].volume, 1_234)
        self.assertEqual(records[0].trading_value, 86_380_000)
        self.assertEqual(captured_request.get_header("Auth_key"), "test-key")
        self.assertNotIn("test-key", repr(records[0]))

    def test_rejected_response_does_not_include_the_key_in_error(self):
        def opener(request, *, timeout):
            return FakeResponse({"respCode": "401", "respMsg": "Unauthorized API Call"})

        client = KrxOpenApiClient(api_key="must-not-leak", opener=opener)

        with self.assertRaises(KrxApiError) as error:
            client.fetch_daily(self.trade_date)

        self.assertNotIn("must-not-leak", str(error.exception))


class StubKrxClient:
    def __init__(self, records_by_date: dict[date, tuple[KrxDailyRecord, ...]]) -> None:
        self.records_by_date = records_by_date
        self.requested_dates: list[date] = []

    def fetch_daily(self, trade_date: date) -> tuple[KrxDailyRecord, ...]:
        self.requested_dates.append(trade_date)
        return self.records_by_date.get(trade_date, ())


def daily_records(trade_date: date, *, count: int = 105) -> tuple[KrxDailyRecord, ...]:
    return tuple(
        KrxDailyRecord(
            ticker=f"{index:06d}",
            name=f"종목-{index:03d}",
            market="KOSPI",
            trade_date=trade_date,
            close_price=10_000 + index,
            volume=1_000 + index,
            trading_value=10_000_000 - (index * 1_000),
            source_payload={"ISU_CD": f"{index:06d}"},
        )
        for index in range(1, count + 1)
    )


class KrxImportServiceTests(TestCase):
    trade_date = date(2026, 7, 27)

    def test_top100_is_persisted_in_trading_value_order(self):
        records = daily_records(self.trade_date)
        client = StubKrxClient({self.trade_date: records})

        result = import_latest_kospi_top100(
            client=client,
            requested_trade_date=self.trade_date,
        )

        self.assertEqual(result.selected_count, 100)
        self.assertEqual(Symbol.objects.count(), 100)
        self.assertEqual(MarketDaily.objects.count(), 100)
        first = MarketDaily.objects.get(trade_date=self.trade_date, trading_value_rank=1)
        last = MarketDaily.objects.get(trade_date=self.trade_date, trading_value_rank=100)
        self.assertEqual(first.symbol_id, "000001")
        self.assertEqual(last.symbol_id, "000100")
        run = ReferenceImportRun.objects.get(id=result.run_id)
        self.assertEqual(run.status, ReferenceImportRun.Status.SUCCESS)
        self.assertEqual(run.selected_count, 100)

    def test_same_date_is_idempotent_and_removes_old_membership(self):
        first_records = daily_records(self.trade_date)
        import_latest_kospi_top100(
            client=StubKrxClient({self.trade_date: first_records}),
            requested_trade_date=self.trade_date,
        )
        replacement = KrxDailyRecord(
            ticker="999999",
            name="신규상위종목",
            market="KOSPI",
            trade_date=self.trade_date,
            close_price=50_000,
            volume=5_000,
            trading_value=99_000_000,
            source_payload={"ISU_CD": "999999"},
        )

        import_latest_kospi_top100(
            client=StubKrxClient({self.trade_date: (replacement, *first_records)}),
            requested_trade_date=self.trade_date,
        )

        self.assertEqual(MarketDaily.objects.filter(trade_date=self.trade_date).count(), 100)
        self.assertTrue(
            MarketDaily.objects.filter(
                trade_date=self.trade_date,
                symbol_id="999999",
                trading_value_rank=1,
            ).exists()
        )
        self.assertFalse(
            MarketDaily.objects.filter(
                trade_date=self.trade_date,
                symbol_id="000100",
            ).exists()
        )

    def test_latest_completed_date_searches_back_from_yesterday(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        completed_date = yesterday - timedelta(days=2)
        client = StubKrxClient({completed_date: daily_records(completed_date)})

        result = import_latest_kospi_top100(client=client)

        self.assertEqual(result.trade_date, completed_date)
        self.assertEqual(client.requested_dates, [yesterday, yesterday - timedelta(days=1), completed_date])

    def test_too_few_records_fails_without_partial_daily_data(self):
        client = StubKrxClient({self.trade_date: daily_records(self.trade_date, count=99)})

        with self.assertRaisesMessage(KrxApiError, "at least 100 traded symbols"):
            import_latest_kospi_top100(
                client=client,
                requested_trade_date=self.trade_date,
            )

        self.assertEqual(MarketDaily.objects.count(), 0)
        run = ReferenceImportRun.objects.get()
        self.assertEqual(run.status, ReferenceImportRun.Status.FAILED)
        self.assertEqual(run.selected_count, 0)

    def test_command_rejects_invalid_trade_date_before_network_access(self):
        with self.assertRaisesMessage(CommandError, "trade-date must use YYYYMMDD format"):
            call_command("import_krx_top100", trade_date="2026-07-27")
