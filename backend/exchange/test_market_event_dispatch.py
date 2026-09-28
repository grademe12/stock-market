from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from exchange.models import MarketEventInbox


@override_settings(
    SIMULATION_MARKET_MODE="always_open",
    SIMULATION_EVENT_MAX_AGE_SECONDS=72 * 60 * 60,
)
class MarketEventDispatchApiTests(APITestCase):
    def create_event(self, **overrides) -> MarketEventInbox:
        now = timezone.now()
        values = {
            "event_id": "opendart:20260928000123:005930",
            "symbol": "005930",
            "event_type": "supply_contract",
            "direction": MarketEventInbox.Direction.BUY,
            "confidence": 0.85,
            "impact": MarketEventInbox.Impact.HIGH,
            "occurred_at": None,
            "detected_at": now,
            "source": "opendart",
            "source_item_id": "20260928000123",
            "headline": "삼성전자: 단일판매ㆍ공급계약체결",
        }
        values.update(overrides)
        return MarketEventInbox.objects.create(**values)

    def test_pending_events_are_filtered_by_runner_symbols(self):
        wanted = self.create_event()
        self.create_event(
            event_id="opendart:20260928000999:000660",
            symbol="000660",
            source_item_id="20260928000999",
        )

        response = self.client.get(
            reverse("market-event-pending"),
            {"symbols": "005930"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["market_open"])
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["event_id"], wanted.event_id)
        self.assertEqual(response.data["results"][0]["direction"], "BUY")
        self.assertEqual(response.data["results"][0]["impact"], "high")

    def test_pending_events_are_withheld_when_market_is_closed(self):
        self.create_event()

        with patch("exchange.views.MarketSession.is_open", return_value=False):
            response = self.client.get(
                reverse("market-event-pending"),
                {"symbols": "005930"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"market_open": False, "results": []})
        self.assertEqual(
            MarketEventInbox.objects.get().state,
            MarketEventInbox.State.PENDING,
        )

    def test_stale_event_uses_detected_at_when_occurrence_is_unknown(self):
        stale = self.create_event(
            detected_at=timezone.now() - timedelta(hours=73),
        )

        response = self.client.get(
            reverse("market-event-pending"),
            {"symbols": "005930"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])
        stale.refresh_from_db()
        self.assertEqual(stale.state, MarketEventInbox.State.STALE)

    def test_stale_event_prefers_known_occurrence_time(self):
        now = timezone.now()
        stale = self.create_event(
            occurred_at=now - timedelta(hours=80),
            detected_at=now - timedelta(hours=1),
        )

        self.client.get(
            reverse("market-event-pending"),
            {"symbols": "005930"},
        )

        stale.refresh_from_db()
        self.assertEqual(stale.state, MarketEventInbox.State.STALE)

    def test_ack_moves_pending_event_to_dispatched_idempotently(self):
        event = self.create_event()
        url = reverse("market-event-ack", args=[event.event_id])

        first = self.client.post(url, {}, format="json")
        second = self.client.post(url, {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["status"], "acknowledged")
        self.assertEqual(first.data["state"], "dispatched")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["status"], "duplicate")
        event.refresh_from_db()
        self.assertEqual(event.state, MarketEventInbox.State.DISPATCHED)

    def test_stale_event_cannot_be_acknowledged(self):
        event = self.create_event(state=MarketEventInbox.State.STALE)

        response = self.client.post(
            reverse("market-event-ack", args=[event.event_id]),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["state"], "stale")

    def test_pending_query_requires_valid_symbols(self):
        missing = self.client.get(reverse("market-event-pending"))
        malformed = self.client.get(
            reverse("market-event-pending"),
            {"symbols": "5930"},
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
