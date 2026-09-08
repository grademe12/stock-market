from unittest import TestCase

from exchange.sharding import matcher_shard, owned_tickers, shard_for_ticker


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
