from unittest import TestCase

from exchange.sharding import (
    advertised_hostname,
    matcher_shard,
    matcher_shard_urls,
    matcher_topology_from_ready,
    owned_tickers,
    prometheus_sd_targets,
    resolve_matcher_shard_urls,
    shard_for_ticker,
)


class ShardingTests(TestCase):
    tickers = (
        "000660",
        "005930",
        "009150",
        "402340",
        "002990",
        "005935",
        "005380",
        "006400",
        "105560",
        "012330",
    )

    def test_two_shards_split_ten_tickers_evenly_by_rank(self) -> None:
        self.assertEqual(
            owned_tickers(self.tickers, 0, 2),
            ("000660", "009150", "002990", "005380", "105560"),
        )
        self.assertEqual(
            owned_tickers(self.tickers, 1, 2),
            ("005930", "402340", "005935", "006400", "012330"),
        )

    def test_single_shard_keeps_the_full_universe(self) -> None:
        self.assertEqual(owned_tickers(self.tickers, 0, 1), self.tickers)

    def test_shard_for_ticker_follows_universe_position(self) -> None:
        self.assertEqual(matcher_shard(0, 2), 0)
        self.assertEqual(matcher_shard(1, 2), 1)
        self.assertEqual(shard_for_ticker(self.tickers, "005930", 2), 1)
        self.assertIsNone(shard_for_ticker(self.tickers, "000270", 2))

    def test_four_shards_split_ten_tickers_by_rank(self) -> None:
        self.assertEqual(
            owned_tickers(self.tickers, 0, 4),
            ("000660", "002990", "105560"),
        )
        self.assertEqual(
            owned_tickers(self.tickers, 1, 4),
            ("005930", "005935", "012330"),
        )
        self.assertEqual(owned_tickers(self.tickers, 2, 4), ("009150", "005380"))
        self.assertEqual(owned_tickers(self.tickers, 3, 4), ("402340", "006400"))

    def test_matcher_shard_urls_expand_from_any_seed_port(self) -> None:
        self.assertEqual(
            matcher_shard_urls(
                "http://stock-market-gce:8001",
                shard_index=1,
                shard_count=4,
                listen_port=8001,
            ),
            (
                "http://stock-market-gce:8000",
                "http://stock-market-gce:8001",
                "http://stock-market-gce:8002",
                "http://stock-market-gce:8003",
            ),
        )

    def test_resolve_keeps_explicit_hostnames_when_count_matches(self) -> None:
        self.assertEqual(
            resolve_matcher_shard_urls(
                ("http://backend:8000", "http://backend-1:8000"),
                shard_index=0,
                shard_count=2,
                listen_port=8000,
            ),
            ("http://backend:8000", "http://backend-1:8000"),
        )

    def test_resolve_expands_same_host_when_count_grows(self) -> None:
        self.assertEqual(
            resolve_matcher_shard_urls(
                ("http://stock-market-gce:8000", "http://stock-market-gce:8001"),
                shard_index=0,
                shard_count=4,
                listen_port=8000,
            ),
            (
                "http://stock-market-gce:8000",
                "http://stock-market-gce:8001",
                "http://stock-market-gce:8002",
                "http://stock-market-gce:8003",
            ),
        )

    def test_matcher_topology_from_ready(self) -> None:
        self.assertEqual(
            matcher_topology_from_ready(
                {"shard_index": 1, "shard_count": 4, "listen_port": 8001}
            ),
            (1, 4, 8001),
        )

    def test_advertised_hostname_strips_port(self) -> None:
        self.assertEqual(advertised_hostname("stock-market-gce:8000"), "stock-market-gce")
        self.assertEqual(advertised_hostname("[::1]:8000"), "::1")

    def test_prometheus_sd_targets_cover_each_shard(self) -> None:
        self.assertEqual(
            prometheus_sd_targets("stock-market-gce", 2),
            [
                {"targets": ["stock-market-gce:8000"], "labels": {"matcher_shard": "0"}},
                {"targets": ["stock-market-gce:8001"], "labels": {"matcher_shard": "1"}},
            ],
        )
