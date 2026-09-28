from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from exchange.models import MarketEventInbox


class MarketEventIngestApiTests(APITestCase):
    @staticmethod
    def payload(**overrides):
        payload = {
            "event_id": "opendart:20260928000123:005930",
            "symbol": "005930",
            "event_type": "supply_contract",
            "direction": "BUY",
            "confidence": 0.85,
            "impact": "high",
            "occurred_at": None,
            "detected_at": "2026-09-28T18:30:00+09:00",
            "source": "opendart",
            "source_item_id": "20260928000123",
            "headline": "삼성전자: 단일판매ㆍ공급계약체결",
        }
        payload.update(overrides)
        return payload

    def post_event(self, **overrides):
        return self.client.post(
            reverse("market-event-ingest"),
            self.payload(**overrides),
            format="json",
        )

    def test_new_event_is_persisted_as_pending(self):
        response = self.post_event()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data,
            {
                "event_id": "opendart:20260928000123:005930",
                "status": "accepted",
                "state": "pending",
            },
        )
        event = MarketEventInbox.objects.get()
        self.assertEqual(event.symbol, "005930")
        self.assertEqual(event.direction, "BUY")
        self.assertEqual(event.impact, "high")
        self.assertEqual(event.confidence, 0.85)
        self.assertIsNone(event.occurred_at)
        self.assertEqual(event.state, MarketEventInbox.State.PENDING)

    def test_identical_retry_is_idempotent(self):
        first = self.post_event()
        second = self.post_event()

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["status"], "duplicate")
        self.assertEqual(MarketEventInbox.objects.count(), 1)

    def test_same_event_id_with_different_payload_conflicts(self):
        self.post_event()

        response = self.post_event(direction="SELL")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(MarketEventInbox.objects.count(), 1)
        self.assertEqual(MarketEventInbox.objects.get().direction, "BUY")

    def test_detected_at_must_not_precede_known_occurrence_time(self):
        response = self.post_event(
            occurred_at="2026-09-28T18:31:00+09:00",
            detected_at="2026-09-28T18:30:00+09:00",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("detected_at", response.data)

    def test_contract_rejects_invalid_direction_impact_confidence_and_symbol(self):
        invalid_direction = self.post_event(direction="HOLD")
        invalid_impact = self.post_event(
            event_id="opendart:2:005930",
            impact="extreme",
        )
        invalid_confidence = self.post_event(
            event_id="opendart:3:005930",
            confidence=1.5,
        )
        invalid_symbol = self.post_event(
            event_id="opendart:4:5930",
            symbol="5930",
        )

        self.assertEqual(invalid_direction.status_code, 400)
        self.assertEqual(invalid_impact.status_code, 400)
        self.assertEqual(invalid_confidence.status_code, 400)
        self.assertEqual(invalid_symbol.status_code, 400)
        self.assertEqual(MarketEventInbox.objects.count(), 0)

    @override_settings(SIMULATION_MARKET_MODE="scheduled")
    def test_event_ingest_is_available_even_when_order_market_is_closed(self):
        response = self.post_event(
            occurred_at="2026-09-27T18:00:00+09:00",
            detected_at="2026-09-27T18:00:05+09:00",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["state"], "pending")
