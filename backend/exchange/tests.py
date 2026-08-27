from unittest.mock import patch

from django.db import DatabaseError
from rest_framework.test import APITestCase
from django.urls import reverse
from django.test import override_settings
from django.core.management import call_command

from exchange import views
from exchange.models import TraderProfile
from exchange.orderbook import OrderBook


class HealthEndpointTests(APITestCase):
    def test_health_endpoint_returns_ok(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class ReadinessEndpointTests(APITestCase):
    def test_readiness_endpoint_checks_the_database(self):
        response = self.client.get(reverse("readiness"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready", "database": "ok"})

    def test_readiness_endpoint_rejects_an_unavailable_database(self):
        with patch("exchange.views.connection.cursor", side_effect=DatabaseError("offline")):
            response = self.client.get(reverse("readiness"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"status": "not_ready", "database": "unavailable"},
        )


class OrderApiTests(APITestCase):
    def setUp(self) -> None:
        views.order_book = OrderBook(symbol=views.SIMULATION_SYMBOL)

    def submit_order(self, **overrides):
        payload = {
            "user_id": "alice",
            "symbol": "005930",
            "side": "BUY",
            "price": 70_000,
            "qty": 3,
        }
        payload.update(overrides)
        return self.client.post(reverse("order-create"), payload, format="json")

    def test_orders_match_and_return_the_execution_result(self):
        resting_sell = self.submit_order(user_id="seller", side="SELL", price=70_000, qty=5)
        buy_response = self.submit_order(user_id="buyer", side="BUY", price=71_000, qty=3)

        self.assertEqual(resting_sell.status_code, 201)
        self.assertEqual(buy_response.status_code, 201)
        self.assertEqual(buy_response.data["remaining_qty"], 0)
        self.assertEqual(buy_response.data["trades"][0]["price"], 70_000)
        self.assertEqual(buy_response.data["trades"][0]["qty"], 3)

    @override_settings(TRADE_EXECUTION_LOG_ENABLED=True)
    def test_execution_log_is_emitted_only_for_a_matched_trade(self):
        self.submit_order(user_id="seller", side="SELL", price=70_000, qty=1)

        with self.assertLogs("exchange.execution", level="INFO") as logs:
            self.submit_order(user_id="buyer", side="BUY", price=70_000, qty=1)

        self.assertIn("event=trade_executed", logs.output[0])
        self.assertIn("symbol=005930", logs.output[0])

    def test_book_snapshot_and_cancel_endpoint(self):
        order_response = self.submit_order()
        order_id = order_response.data["order_id"]

        book_response = self.client.get(reverse("book-detail", args=["005930"]))
        cancel_response = self.client.delete(reverse("order-cancel", args=[order_id]))
        empty_book_response = self.client.get(reverse("book-detail", args=["005930"]))

        self.assertEqual(book_response.data["bids"], [{"price": 70_000, "qty": 3}])
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.data["canceled_qty"], 3)
        self.assertEqual(empty_book_response.data["bids"], [])

    def test_cancel_is_idempotent_when_an_order_is_already_closed(self):
        order_id = self.submit_order().data["order_id"]
        self.client.delete(reverse("order-cancel", args=[order_id]))

        response = self.client.delete(reverse("order-cancel", args=[order_id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ALREADY_CLOSED")
        self.assertEqual(response.data["canceled_qty"], 0)

    def test_invalid_order_is_rejected(self):
        response = self.submit_order(side="INVALID")

        self.assertEqual(response.status_code, 400)
        self.assertIn("side", response.data)


@override_settings(DEBUG=True)
class TraderProfileApiTests(APITestCase):
    def setUp(self) -> None:
        views.order_book = OrderBook(symbol=views.SIMULATION_SYMBOL)

    @staticmethod
    def profile_payload(**overrides):
        payload = {
            "name": "Conservative noise trader",
            "user_id": "noise-profile-001",
            "strategy": "noise",
            "enabled": True,
            "symbol": "005930",
            "reference_price": 71_200,
            "price_step": 100,
            "max_offset_steps": 0,
            "quantity_min": 3,
            "quantity_max": 3,
            "order_ttl_ticks": 4,
            "interval_ticks": 1,
            "seed": 42,
        }
        payload.update(overrides)
        return payload

    def test_profile_can_be_created_listed_updated_and_deleted(self):
        create_response = self.client.post(
            reverse("trader-profile-list"),
            self.profile_payload(),
            format="json",
        )
        profile_id = create_response.data["id"]

        list_response = self.client.get(reverse("trader-profile-list"))
        patch_response = self.client.patch(
            reverse("trader-profile-detail", args=[profile_id]),
            {"interval_ticks": 3, "enabled": False},
            format="json",
        )
        delete_response = self.client.delete(reverse("trader-profile-detail", args=[profile_id]))

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(list_response.data[0]["id"], profile_id)
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.data["interval_ticks"], 3)
        self.assertFalse(patch_response.data["enabled"])
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(TraderProfile.objects.filter(id=profile_id).exists())

    def test_all_external_runner_strategies_are_accepted(self):
        for index, strategy in enumerate(
            (
                "noise",
                "momentum",
                "mean_reversion",
                "liquidity_provider",
                "event_reactive",
            ),
            start=1,
        ):
            response = self.client.post(
                reverse("trader-profile-list"),
                self.profile_payload(
                    name=f"{strategy}-{index}",
                    user_id=f"{strategy}-{index}",
                    strategy=strategy,
                ),
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)

    def test_unsupported_profile_symbol_is_rejected(self):
        response = self.client.post(
            reverse("trader-profile-list"),
            self.profile_payload(symbol="000660"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("symbol", response.data)


class SeedTradersCommandTests(APITestCase):
    def test_seed_command_is_deterministic_and_idempotent(self):
        call_command("seed_traders", count=3, seed=42)
        fields = (
            "name",
            "user_id",
            "reference_price",
            "price_step",
            "max_offset_steps",
            "quantity_min",
            "quantity_max",
            "order_ttl_ticks",
            "interval_ticks",
            "seed",
        )
        first_run = list(TraderProfile.objects.order_by("user_id").values_list(*fields))

        call_command("seed_traders", count=3, seed=42)
        second_run = list(TraderProfile.objects.order_by("user_id").values_list(*fields))

        self.assertEqual(TraderProfile.objects.count(), 3)
        self.assertEqual(first_run, second_run)

    def test_seed_command_supports_each_external_strategy(self):
        strategies = (
            "noise",
            "momentum",
            "mean_reversion",
            "liquidity_provider",
            "event_reactive",
        )

        for strategy in strategies:
            call_command("seed_traders", count=1, seed=42, strategy=strategy)

        self.assertEqual(
            set(TraderProfile.objects.values_list("strategy", flat=True)),
            set(strategies),
        )
