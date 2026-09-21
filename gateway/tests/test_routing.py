from unittest import TestCase

from gateway.routing import (
    RoutingError,
    matcher_listen_port,
    route_request,
)


class GatewayRoutingTests(TestCase):
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

    def route(self, method: str, path: str, **kwargs: object):
        return route_request(
            method,
            path,
            tickers=self.tickers,
            shard_count=4,
            **kwargs,
        )

    def test_health_stays_on_shard_zero(self) -> None:
        self.assertEqual(self.route("GET", "/api/v1/health/").shard_index, 0)

    def test_book_follows_universe_position(self) -> None:
        self.assertEqual(self.route("GET", "api/v1/books/000660/").shard_index, 0)
        self.assertEqual(self.route("GET", "/api/v1/books/005930").shard_index, 1)
        self.assertEqual(self.route("GET", "/api/v1/books/009150/").shard_index, 2)
        self.assertEqual(self.route("GET", "/api/v1/books/402340/").shard_index, 3)

    def test_order_post_reads_body_symbol(self) -> None:
        route = self.route(
            "POST",
            "/api/v1/orders/",
            body=b'{"symbol":"005380","side":"BUY","price":1,"qty":1}',
        )
        self.assertEqual(route.shard_index, 2)
        self.assertEqual(route.symbol, "005380")

    def test_cancel_requires_symbol_query(self) -> None:
        with self.assertRaises(RoutingError) as raised:
            self.route("DELETE", "/api/v1/orders/11111111-1111-1111-1111-111111111111/")
        self.assertEqual(raised.exception.status, 400)

        route = self.route(
            "DELETE",
            "/api/v1/orders/11111111-1111-1111-1111-111111111111/",
            query="symbol=006400",
        )
        self.assertEqual(route.shard_index, 3)

    def test_trades_require_symbol(self) -> None:
        with self.assertRaises(RoutingError) as raised:
            self.route("GET", "/api/v1/trades/")
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(
            self.route("GET", "/api/v1/trades/", query="symbol=000660&limit=10").shard_index,
            0,
        )

    def test_unknown_symbol_is_rejected(self) -> None:
        with self.assertRaises(RoutingError) as raised:
            self.route("GET", "/api/v1/books/000270/")
        self.assertEqual(raised.exception.status, 400)

    def test_unknown_path_is_not_forwarded(self) -> None:
        with self.assertRaises(RoutingError) as raised:
            self.route("GET", "/admin/")
        self.assertEqual(raised.exception.status, 404)

    def test_matcher_ports_start_after_the_gateway(self) -> None:
        self.assertEqual(matcher_listen_port(0), 8001)
        self.assertEqual(matcher_listen_port(3), 8004)

    def test_metrics_path_selects_shard_and_rewrites_upstream(self) -> None:
        route = self.route("GET", "/metrics/2/")
        self.assertEqual(route.shard_index, 2)
        self.assertEqual(route.upstream_path, "/metrics/")

    def test_ready_path_selects_shard(self) -> None:
        route = self.route("GET", "/api/v1/ready/1")
        self.assertEqual(route.shard_index, 1)
        self.assertEqual(route.upstream_path, "/api/v1/ready/")

    def test_unknown_shard_metrics_are_rejected(self) -> None:
        with self.assertRaises(RoutingError) as raised:
            self.route("GET", "/metrics/4/")
        self.assertEqual(raised.exception.status, 404)
