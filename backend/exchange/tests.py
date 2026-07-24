from rest_framework.test import APITestCase
from django.urls import reverse


class HealthEndpointTests(APITestCase):
    def test_health_endpoint_returns_ok(self):
        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
