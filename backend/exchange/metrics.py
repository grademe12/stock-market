from time import perf_counter

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "http_requests",
    "Django HTTP responses by route, method, and status.",
    ("route", "method", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Django HTTP request duration by route and method.",
    ("route", "method"),
)
ORDERS_SUBMITTED = Counter(
    "orders_submitted",
    "Validated orders submitted to the in-memory matcher.",
    ("symbol", "side"),
)
ORDERS_REJECTED = Counter(
    "orders_rejected",
    "Orders rejected before reaching the matcher.",
    ("reason",),
)
TRADES_EXECUTED = Counter(
    "trades_executed",
    "Trades produced by the in-memory matcher.",
    ("symbol",),
)
TRADED_QUANTITY = Counter(
    "traded_quantity",
    "Total quantity executed by the in-memory matcher.",
    ("symbol",),
)
ORDERBOOK_DEPTH = Gauge(
    "orderbook_depth",
    "Total remaining order quantity by symbol and side.",
    ("symbol", "side"),
)


class PrometheusMetricsMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started_at = perf_counter()
        response = self.get_response(request)

        resolver_match = request.resolver_match
        if resolver_match is None or resolver_match.url_name != "metrics":
            route = (
                resolver_match.route or resolver_match.view_name
                if resolver_match is not None
                else "unmatched"
            )
            method = request.method
            HTTP_REQUESTS.labels(route, method, str(response.status_code)).inc()
            HTTP_REQUEST_DURATION.labels(route, method).observe(perf_counter() - started_at)

        return response


@require_GET
def metrics_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)
