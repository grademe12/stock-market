from unittest import TestCase

from gateway.discovery import advertised_scrape_target, prometheus_sd_targets


class GatewayDiscoveryTests(TestCase):
    def test_sd_stays_on_the_public_entry(self) -> None:
        self.assertEqual(
            prometheus_sd_targets("stock-market-gce:8000", 2),
            [
                {
                    "targets": ["stock-market-gce:8000"],
                    "labels": {
                        "matcher_shard": "0",
                        "__metrics_path__": "/metrics/0/",
                    },
                },
                {
                    "targets": ["stock-market-gce:8000"],
                    "labels": {
                        "matcher_shard": "1",
                        "__metrics_path__": "/metrics/1/",
                    },
                },
            ],
        )

    def test_scrape_target_keeps_host_port(self) -> None:
        self.assertEqual(
            advertised_scrape_target("stock-market-gce:8000", 8000),
            "stock-market-gce:8000",
        )
        self.assertEqual(advertised_scrape_target("stock-market-gce", 8000), "stock-market-gce:8000")
        self.assertEqual(advertised_scrape_target("[::1]:8000", 8000), "[::1]:8000")
