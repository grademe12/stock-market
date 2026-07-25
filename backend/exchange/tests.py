from rest_framework.test import APITestCase
from django.urls import reverse
from django.test import override_settings

from exchange import views
from exchange.models import TraderProfile
from exchange.orderbook import OrderBook


class HealthEndpointTests(APITestCase):
    def test_health_endpoint_returns_ok(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class OrderApiTests(APITestCase):
    def setUp(self) -> None:
        views.participant_runtime.stop()
        views.order_book = OrderBook(symbol=views.SIMULATION_SYMBOL)
        views.participant_runtime = views.build_participant_runtime()

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

    def test_invalid_order_is_rejected(self):
        response = self.submit_order(side="INVALID")

        self.assertEqual(response.status_code, 400)
        self.assertIn("side", response.data)


@override_settings(DEBUG=True)
class ParticipantSimulationApiTests(APITestCase):
    def setUp(self) -> None:
        views.participant_runtime.stop()
        views.order_book = OrderBook(symbol=views.SIMULATION_SYMBOL)
        views.participant_runtime = views.build_participant_runtime()

    def tearDown(self) -> None:
        views.participant_runtime.stop()

    @staticmethod
    def config():
        return {
            "strategy": "noise",
            "participants": 2,
            "reference_price": 70_000,
            "price_step": 100,
            "max_offset_steps": 2,
            "quantity_min": 1,
            "quantity_max": 2,
            "order_ttl_ticks": 2,
            "interval_ms": 1_000,
            "seed": 42,
        }

    def test_manual_tick_creates_reproducible_participant_orders(self):
        response = self.client.post(
            reverse("participant-simulation-tick"),
            self.config(),
            format="json",
        )
        status_response = self.client.get(reverse("participant-simulation"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["simulation"]["ticks_total"], 1)
        self.assertEqual(response.data["simulation"]["orders_submitted_total"], 2)
        self.assertEqual(status_response.data["state"], "STOPPED")
        self.assertEqual(status_response.data["ticks_total"], 1)

    def test_start_and_stop_control_the_in_process_runtime(self):
        start_response = self.client.post(
            reverse("participant-simulation-start"),
            self.config(),
            format="json",
        )
        stop_response = self.client.delete(reverse("participant-simulation"))

        self.assertEqual(start_response.status_code, 201)
        self.assertEqual(start_response.data["state"], "RUNNING")
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(stop_response.data["state"], "STOPPED")
        self.assertEqual(stop_response.data["open_bot_orders"], 0)


@override_settings(DEBUG=True)
class TraderProfileApiTests(APITestCase):
    def setUp(self) -> None:
        views.participant_runtime.stop()
        views.order_book = OrderBook(symbol=views.SIMULATION_SYMBOL)
        views.participant_runtime = views.build_participant_runtime()

    def tearDown(self) -> None:
        views.participant_runtime.stop()

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

    def test_enabled_profiles_replace_the_legacy_participant_count(self):
        enabled = self.client.post(
            reverse("trader-profile-list"),
            self.profile_payload(),
            format="json",
        )
        disabled = self.client.post(
            reverse("trader-profile-list"),
            self.profile_payload(
                name="Paused noise trader",
                user_id="noise-profile-002",
                enabled=False,
            ),
            format="json",
        )

        tick_response = self.client.post(
            reverse("participant-simulation-tick"),
            {"participants": 20, "interval_ms": 1_000},
            format="json",
        )
        book_response = self.client.get(reverse("book-detail", args=["005930"]))

        self.assertEqual(enabled.status_code, 201)
        self.assertEqual(disabled.status_code, 201)
        self.assertEqual(tick_response.status_code, 200)
        self.assertEqual(tick_response.data["simulation"]["orders_submitted_total"], 1)
        levels = book_response.data["bids"] + book_response.data["asks"]
        self.assertEqual(levels, [{"price": 71_200, "qty": 3}])

    def test_unsupported_profile_symbol_is_rejected(self):
        response = self.client.post(
            reverse("trader-profile-list"),
            self.profile_payload(symbol="000660"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("symbol", response.data)
