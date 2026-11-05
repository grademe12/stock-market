"""Forward routed requests to localhost matcher processes."""

from __future__ import annotations

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import urlparse, urlsplit

from gateway.discovery import advertised_scrape_target, prometheus_sd_targets
from gateway.metrics import GatewayMetrics
from gateway.routing import (
    RoutingError,
    is_gateway_metrics_path,
    is_service_discovery_path,
    matcher_listen_port,
    route_request,
)


class GatewayHTTPServer(ThreadingHTTPServer):
    # socketserver listens with a backlog of 5 by default. Every runner request
    # opens a new connection, so a burst overflows that queue, the kernel drops
    # the handshake, and the client waits for a TCP retransmit (about 1s).
    # The matcher shards (gunicorn) already listen with 2048. The kernel caps
    # this value at net.core.somaxconn.
    request_queue_size = 2048

    def __init__(self, server_address, handler_class, *, metrics: GatewayMetrics | None = None) -> None:
        self.metrics = metrics
        self._accepted_at: dict[object, float] = {}
        self._accepted_lock = threading.Lock()
        super().__init__(server_address, handler_class)

    def process_request(self, request, client_address) -> None:
        # Runs on the accept loop. The handler thread reads this back so the
        # wait between accept() and the thread actually running is visible.
        if self.metrics is not None:
            with self._accepted_lock:
                self._accepted_at[request] = self.metrics.now()
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address) -> None:
        if self.metrics is not None:
            with self._accepted_lock:
                accepted_at = self._accepted_at.pop(request, None)
            if accepted_at is not None:
                self.metrics.observe_accept_wait(self.metrics.now() - accepted_at)
        super().process_request_thread(request, client_address)


class GatewayHandler(BaseHTTPRequestHandler):
    tickers: tuple[str, ...] = ()
    shard_count: int = 1
    matcher_host: str = "127.0.0.1"
    first_matcher_port: int = 8001
    shard_urls: tuple[str, ...] = ()
    public_port: int = 8000
    timeout_seconds: float = 5.0
    metrics: GatewayMetrics | None = None
    _status: int = 0

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

    def send_response(self, code: int, message: str | None = None) -> None:
        self._status = code
        super().send_response(code, message)

    def _proxy(self) -> None:
        metrics = self.metrics
        if metrics is None:
            self._handle()
            return
        if self.command == "GET" and is_gateway_metrics_path(urlsplit(self.path).path):
            self._write_metrics(metrics)
            return
        started = metrics.now()
        metrics.request_started()
        self._status = 0
        try:
            self._handle()
        finally:
            metrics.request_finished(self.command, self._status, metrics.now() - started)

    def _handle(self) -> None:
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        if self.command == "GET" and is_service_discovery_path(parsed.path):
            self._write_service_discovery()
            return
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

        host, port = self._upstream(route.shard_index)
        connection = HTTPConnection(host, port, timeout=self.timeout_seconds)
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"content-length"}
        }
        request_path = self._upstream_request_path(parsed, route.upstream_path)
        metrics = self.metrics
        upstream_started = metrics.now() if metrics is not None else 0.0
        try:
            try:
                connection.request(self.command, request_path, body=body or None, headers=headers)
                upstream = connection.getresponse()
                payload = upstream.read()
            except OSError:
                if metrics is not None:
                    metrics.observe_upstream(route.shard_index, metrics.now() - upstream_started, failed=True)
                raise
            if metrics is not None:
                metrics.observe_upstream(route.shard_index, metrics.now() - upstream_started)
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

    def _upstream(self, shard_index: int) -> tuple[str, int]:
        if self.shard_urls:
            parsed = urlparse(self.shard_urls[shard_index])
            if not parsed.hostname:
                raise RoutingError(500, "matcher URL is missing a host")
            return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        return self.matcher_host, matcher_listen_port(
            shard_index,
            first_port=self.first_matcher_port,
        )

    def _upstream_request_path(self, parsed, upstream_path: str | None) -> str:
        if not upstream_path:
            return self.path
        if parsed.query:
            return f"{upstream_path}?{parsed.query}"
        return upstream_path

    def _write_service_discovery(self) -> None:
        try:
            target = advertised_scrape_target(self.headers.get("Host", ""), self.public_port)
        except ValueError:
            self._write_error(400, "host header is required")
            return
        payload = json.dumps(prometheus_sd_targets(target, self.shard_count)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _write_metrics(self, metrics: GatewayMetrics) -> None:
        payload = metrics.render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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
    shard_urls: tuple[str, ...] = (),
    public_port: int = 8000,
    timeout_seconds: float = 5.0,
    metrics: GatewayMetrics | None = None,
) -> type[GatewayHandler]:
    class BoundHandler(GatewayHandler):
        pass

    BoundHandler.tickers = tickers
    BoundHandler.shard_count = shard_count
    BoundHandler.matcher_host = matcher_host
    BoundHandler.first_matcher_port = first_matcher_port
    BoundHandler.shard_urls = shard_urls
    BoundHandler.public_port = public_port
    BoundHandler.timeout_seconds = timeout_seconds
    BoundHandler.metrics = metrics
    return BoundHandler


def serve(
    bind: str,
    port: int,
    *,
    tickers: tuple[str, ...],
    shard_count: int,
    matcher_host: str = "127.0.0.1",
    first_matcher_port: int = 8001,
    shard_urls: tuple[str, ...] = (),
) -> None:
    metrics = GatewayMetrics(listen_port=port)
    handler = make_handler(
        tickers=tickers,
        shard_count=shard_count,
        matcher_host=matcher_host,
        first_matcher_port=first_matcher_port,
        shard_urls=shard_urls,
        public_port=port,
        metrics=metrics,
    )
    server = GatewayHTTPServer((bind, port), handler, metrics=metrics)
    server.serve_forever()
