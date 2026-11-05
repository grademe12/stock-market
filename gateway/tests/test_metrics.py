from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from unittest import TestCase

from gateway.metrics import GatewayMetrics, Histogram, parse_listen_queue
from gateway.proxy import GatewayHTTPServer, make_handler
from gateway.routing import is_gateway_metrics_path

TICKERS = ("005930", "000660")

# Two listeners on :8000 (0x1F40), one with 3 connections waiting, one other port,
# and one established connection on :8000 that must be ignored.
PROC_NET_TCP = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:1F40 00000000:0000 0A 00000000:00000003 00:00000000 00000000     0        0 1 1
   1: 0100007F:1F41 00000000:0000 0A 00000000:00000007 00:00000000 00000000     0        0 2 1
   2: 0100007F:1F40 0100007F:9C40 01 00000000:00000010 00:00000000 00000000     0        0 3 1
"""


class HistogramTests(TestCase):
    def test_value_on_a_bound_goes_into_that_bucket(self) -> None:
        histogram = Histogram((0.1, 1.0))
        for value in (0.05, 0.1, 0.5, 2.0):
            histogram.observe(value)
        self.assertEqual(histogram.counts, [2, 1, 1])
        self.assertEqual(histogram.count, 4)


class RenderTests(TestCase):
    def test_render_is_cumulative_prometheus_text(self) -> None:
        metrics = GatewayMetrics()
        metrics.request_started()
        metrics.request_finished("POST", 201, 0.003)
        metrics.request_started()
        metrics.request_finished("POST", 201, 0.3)
        metrics.observe_upstream(1, 0.002)
        metrics.observe_upstream(1, 0.01, failed=True)
        metrics.observe_accept_wait(0.0001)

        text = metrics.render()

        self.assertIn('gateway_requests_total{method="POST",status="201"} 2', text)
        self.assertIn('gateway_request_duration_seconds_bucket{method="POST",le="0.005"} 1', text)
        self.assertIn('gateway_request_duration_seconds_bucket{method="POST",le="+Inf"} 2', text)
        self.assertIn('gateway_request_duration_seconds_count{method="POST"} 2', text)
        self.assertIn('gateway_upstream_duration_seconds_count{shard="1"} 2', text)
        self.assertIn('gateway_upstream_errors_total{shard="1"} 1', text)
        self.assertIn('gateway_accept_wait_seconds_bucket{le="0.0005"} 1', text)
        self.assertIn("gateway_accept_wait_seconds_count 1", text)
        self.assertIn("gateway_in_flight_requests 0", text)
        self.assertIn("process_cpu_seconds_total ", text)
        self.assertTrue(text.endswith("\n"))


class ListenQueueTests(TestCase):
    def test_reads_rx_queue_of_listening_socket_on_port(self) -> None:
        self.assertEqual(parse_listen_queue(PROC_NET_TCP, 8000), 3)
        self.assertEqual(parse_listen_queue(PROC_NET_TCP, 8001), 7)
        self.assertEqual(parse_listen_queue(PROC_NET_TCP, 9999), 0)


class FakeMatcher(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        payload = b'{"ok": true}'
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class GatewayMetricsEndToEndTests(TestCase):
    def setUp(self) -> None:
        self.matcher = ThreadingHTTPServer(("127.0.0.1", 0), FakeMatcher)
        matcher_port = self.matcher.server_address[1]
        self.metrics = GatewayMetrics()
        handler = make_handler(
            tickers=TICKERS,
            shard_count=1,
            matcher_host="127.0.0.1",
            first_matcher_port=matcher_port,
            metrics=self.metrics,
        )
        self.gateway = GatewayHTTPServer(("127.0.0.1", 0), handler, metrics=self.metrics)
        self.threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (self.matcher, self.gateway)
        ]
        for thread in self.threads:
            thread.start()

    def tearDown(self) -> None:
        for server in (self.gateway, self.matcher):
            server.shutdown()
            server.server_close()

    def request(self, method: str, path: str, body: dict | None = None):
        connection = HTTPConnection("127.0.0.1", self.gateway.server_address[1], timeout=5)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json"} if payload else {}
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, response.read().decode()
        finally:
            connection.close()

    def test_proxied_order_is_counted_and_timed(self) -> None:
        status, _ = self.request("POST", "/api/v1/orders/", {"symbol": "005930", "side": "BUY"})
        self.assertEqual(status, 201)

        status, text = self.request("GET", "/gateway/metrics")

        self.assertEqual(status, 200)
        self.assertIn('gateway_requests_total{method="POST",status="201"} 1', text)
        self.assertIn('gateway_upstream_duration_seconds_count{shard="0"} 1', text)
        # Both the order and the scrape went through accept().
        self.assertIn("gateway_accept_wait_seconds_count 2", text)
        # The scrape itself is not counted as a proxied request.
        self.assertNotIn('method="GET"', text)

    def test_routing_error_is_counted_with_its_status(self) -> None:
        status, _ = self.request("POST", "/api/v1/orders/", {"symbol": "999999"})
        self.assertGreaterEqual(status, 400)

        _, text = self.request("GET", "/gateway/metrics/")

        self.assertIn(f'gateway_requests_total{{method="POST",status="{status}"}} 1', text)
        self.assertNotIn("gateway_upstream_duration_seconds_count", text)

    def test_metrics_path_matches_with_and_without_slash(self) -> None:
        self.assertTrue(is_gateway_metrics_path("/gateway/metrics"))
        self.assertTrue(is_gateway_metrics_path("/gateway/metrics/"))
        self.assertFalse(is_gateway_metrics_path("/metrics/0/"))
