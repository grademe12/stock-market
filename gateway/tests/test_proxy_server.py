from http.server import ThreadingHTTPServer
from unittest import TestCase

from gateway.proxy import GatewayHTTPServer


class GatewayHTTPServerTests(TestCase):
    def test_listen_queue_is_larger_than_socketserver_default(self) -> None:
        self.assertEqual(ThreadingHTTPServer.request_queue_size, 5)
        self.assertGreaterEqual(GatewayHTTPServer.request_queue_size, 1024)
