from rest_framework.test import APITestCase
from django.urls import reverse

from exchange import views
from exchange.orderbook import OrderBook


class HealthEndpointTests(APITestCase):
    def test_health_endpoint_returns_ok(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


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
