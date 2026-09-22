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
    events_received_total: int,
    events_deduplicated_total: int,
    event_trader_pool_size: int,
    activated_traders_total: int,
    reactions_planned_total: int,
    reactions_submitted_total: int,
    reactions_dropped_total: int,
    scheduler_lag_max_ms: int,
    market_session_open: bool,
    market_session_open_transitions_total: int,
    market_session_close_transitions_total: int,
) -> str:
    labels = f'strategy="{_label_value(strategy)}",shard="{_label_value(shard)}"'
    scheduler_lag_max_seconds = scheduler_lag_max_ms / 1_000
    return (
        "# HELP runner_http_in_flight In-flight order and cancel HTTP requests.\n"
        "# TYPE runner_http_in_flight gauge\n"
        f"runner_http_in_flight{{{labels}}} {http_in_flight}\n"
        "# HELP runner_orders_submitted_total Orders this runner successfully submitted.\n"
        "# TYPE runner_orders_submitted_total counter\n"
        f"runner_orders_submitted_total{{{labels}}} {orders_submitted_total}\n"
        "# HELP runner_events_received_total News shock events accepted by the coordinator.\n"
        "# TYPE runner_events_received_total counter\n"
        f"runner_events_received_total{{{labels}}} {events_received_total}\n"
        "# HELP runner_events_deduplicated_total Duplicate news shock events ignored by the coordinator.\n"
        "# TYPE runner_events_deduplicated_total counter\n"
        f"runner_events_deduplicated_total{{{labels}}} {events_deduplicated_total}\n"
        "# HELP runner_event_trader_pool_size Event-reactive traders registered with the coordinator.\n"
        "# TYPE runner_event_trader_pool_size gauge\n"
        f"runner_event_trader_pool_size{{{labels}}} {event_trader_pool_size}\n"
        "# HELP runner_activated_traders_total Event-reactive trader activations across accepted events.\n"
        "# TYPE runner_activated_traders_total counter\n"
        f"runner_activated_traders_total{{{labels}}} {activated_traders_total}\n"
        "# HELP runner_reactions_planned_total Reaction orders planned by accepted events.\n"
        "# TYPE runner_reactions_planned_total counter\n"
        f"runner_reactions_planned_total{{{labels}}} {reactions_planned_total}\n"
        "# HELP runner_reactions_submitted_total Planned reaction orders successfully submitted.\n"
        "# TYPE runner_reactions_submitted_total counter\n"
        f"runner_reactions_submitted_total{{{labels}}} {reactions_submitted_total}\n"
        "# HELP runner_reactions_dropped_total Planned reaction orders dropped or failed before submission.\n"
        "# TYPE runner_reactions_dropped_total counter\n"
        f"runner_reactions_dropped_total{{{labels}}} {reactions_dropped_total}\n"
        "# HELP runner_scheduler_lag_max_seconds Maximum observed event reaction scheduler lag.\n"
        "# TYPE runner_scheduler_lag_max_seconds gauge\n"
        f"runner_scheduler_lag_max_seconds{{{labels}}} {scheduler_lag_max_seconds}\n"
        "# HELP runner_market_session_open Whether this runner currently considers the market session open.\n"
        "# TYPE runner_market_session_open gauge\n"
        f"runner_market_session_open{{{labels}}} {1 if market_session_open else 0}\n"
        "# HELP runner_market_session_transitions_total Market session transitions observed by this runner.\n"
        "# TYPE runner_market_session_transitions_total counter\n"
        f"runner_market_session_transitions_total{{{labels},transition=\"open\"}} {market_session_open_transitions_total}\n"
        f"runner_market_session_transitions_total{{{labels},transition=\"close\"}} {market_session_close_transitions_total}\n"
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
