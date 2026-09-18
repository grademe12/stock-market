"""Forward routed requests to localhost matcher processes."""

from __future__ import annotations

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlsplit

from gateway.routing import RoutingError, matcher_listen_port, route_request


class GatewayHandler(BaseHTTPRequestHandler):
    tickers: tuple[str, ...] = ()
    shard_count: int = 1
    matcher_host: str = "127.0.0.1"
    first_matcher_port: int = 8001
    timeout_seconds: float = 5.0

    def do_GET(self) -> None:
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def do_DELETE(self) -> None:
        self._proxy()

    def do_PATCH(self) -> None:
        self._proxy()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _proxy(self) -> None:
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        try:
            route = route_request(
                self.command,
                parsed.path,
                query=parsed.query,
                body=body,
                tickers=self.tickers,
                shard_count=self.shard_count,
            )
        except RoutingError as exc:
            self._write_error(exc.status, exc.detail)
            return

        port = matcher_listen_port(route.shard_index, first_port=self.first_matcher_port)
        connection = HTTPConnection(
            self.matcher_host,
            port,
            timeout=self.timeout_seconds,
        )
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length"}
        }
        try:
            connection.request(self.command, self.path, body=body or None, headers=headers)
            upstream = connection.getresponse()
            payload = upstream.read()
            self.send_response(upstream.status)
            for key, value in upstream.getheaders():
                if key.lower() in {"transfer-encoding", "connection"}:
                    continue
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            self._write_error(502, "matcher is unavailable")
        finally:
            connection.close()

    def _write_error(self, status: int, detail: str) -> None:
        payload = json.dumps({"detail": detail}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def make_handler(
    *,
    tickers: tuple[str, ...],
    shard_count: int,
    matcher_host: str = "127.0.0.1",
    first_matcher_port: int = 8001,
    timeout_seconds: float = 5.0,
) -> type[GatewayHandler]:
    class BoundHandler(GatewayHandler):
        pass

    BoundHandler.tickers = tickers
    BoundHandler.shard_count = shard_count
    BoundHandler.matcher_host = matcher_host
    BoundHandler.first_matcher_port = first_matcher_port
    BoundHandler.timeout_seconds = timeout_seconds
    return BoundHandler


def serve(
    bind: str,
    port: int,
    *,
    tickers: tuple[str, ...],
    shard_count: int,
    matcher_host: str = "127.0.0.1",
    first_matcher_port: int = 8001,
) -> None:
    handler = make_handler(
        tickers=tickers,
        shard_count=shard_count,
        matcher_host=matcher_host,
        first_matcher_port=first_matcher_port,
    )
    server = ThreadingHTTPServer((bind, port), handler)
    server.serve_forever()
