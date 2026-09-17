from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


def _label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_metrics(
    *,
    strategy: str,
    shard: str,
    http_in_flight: int,
    orders_submitted_total: int,
) -> str:
    labels = f'strategy="{_label_value(strategy)}",shard="{_label_value(shard)}"'
    return (
        "# HELP runner_http_in_flight In-flight order and cancel HTTP requests.\n"
        "# TYPE runner_http_in_flight gauge\n"
        f"runner_http_in_flight{{{labels}}} {http_in_flight}\n"
        "# HELP runner_orders_submitted_total Orders this runner successfully submitted.\n"
        "# TYPE runner_orders_submitted_total counter\n"
        f"runner_orders_submitted_total{{{labels}}} {orders_submitted_total}\n"
    )


class MetricsServer:
    """Serves Prometheus text on GET /metrics from a background thread."""

    def __init__(
        self,
        host: str,
        port: int,
        render: Callable[[], str],
    ) -> None:
        handler = _handler_for(render)
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._thread = Thread(target=self._httpd.serve_forever, name="runner-metrics", daemon=True)

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)


def _handler_for(render: Callable[[], str]) -> type[BaseHTTPRequestHandler]:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] != "/metrics":
                self.send_error(404)
                return
            body = render().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return MetricsHandler
