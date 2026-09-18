"""Decide which matcher shard should receive an inbound HTTP request."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Mapping
from urllib.parse import parse_qs

from exchange.sharding import shard_for_ticker

BOOK_PATH = re.compile(r"^/api/v1/books/(\d{6})/?$")
ORDER_CREATE_PATH = re.compile(r"^/api/v1/orders/?$")
ORDER_CANCEL_PATH = re.compile(r"^/api/v1/orders/[0-9a-fA-F-]+/?$")
TRADES_PATH = re.compile(r"^/api/v1/trades/?$")
DEFAULT_SHARD_PATHS = (
    re.compile(r"^/api/v1/health/?$"),
    re.compile(r"^/api/v1/ready/?$"),
    re.compile(r"^/api/v1/symbols/?$"),
    re.compile(r"^/api/v1/traders(?:/[0-9a-fA-F-]+)?/?$"),
    re.compile(r"^/api/v1/prometheus-sd/?$"),
    re.compile(r"^/metrics/?$"),
)


class RoutingError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Route:
    shard_index: int
    symbol: str | None


def matcher_listen_port(shard_index: int, *, first_port: int = 8001) -> int:
    if shard_index < 0:
        raise ValueError("shard_index must be at least 0")
    if first_port < 1:
        raise ValueError("first_port must be at least 1")
    return first_port + shard_index


def route_request(
    method: str,
    path: str,
    *,
    query: str = "",
    body: bytes | str | None = None,
    tickers: tuple[str, ...],
    shard_count: int,
) -> Route:
    """Return the matcher shard for this request, or raise RoutingError."""
    if shard_count < 1:
        raise RoutingError(500, "shard_count must be at least 1")
    normalized_method = method.upper()
    normalized_path = path if path.startswith("/") else f"/{path}"

    if any(pattern.match(normalized_path) for pattern in DEFAULT_SHARD_PATHS):
        return Route(shard_index=0, symbol=None)

    symbol = _symbol_from_request(
        normalized_method,
        normalized_path,
        query=query,
        body=body,
    )
    shard = shard_for_ticker(tickers, symbol, shard_count)
    if shard is None:
        raise RoutingError(400, "symbol is not in the current simulation set")
    return Route(shard_index=shard, symbol=symbol)


def _symbol_from_request(
    method: str,
    path: str,
    *,
    query: str,
    body: bytes | str | None,
) -> str:
    book_match = BOOK_PATH.match(path)
    if method == "GET" and book_match:
        return book_match.group(1)

    if method == "GET" and TRADES_PATH.match(path):
        return _required_query_symbol(query)

    if method == "POST" and ORDER_CREATE_PATH.match(path):
        return _symbol_from_order_body(body)

    if method == "DELETE" and ORDER_CANCEL_PATH.match(path):
        return _required_query_symbol(query)

    raise RoutingError(404, "gateway route is not allowed")


def _required_query_symbol(query: str) -> str:
    values = parse_qs(query, keep_blank_values=True).get("symbol", [])
    symbol = values[0].strip() if values else ""
    if not symbol:
        raise RoutingError(400, "symbol is required")
    return symbol


def _symbol_from_order_body(body: bytes | str | None) -> str:
    if body is None or body == b"" or body == "":
        raise RoutingError(400, "order body is required")
    raw = body.decode("utf-8") if isinstance(body, bytes) else body
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RoutingError(400, "order body must be JSON") from exc
    if not isinstance(payload, Mapping):
        raise RoutingError(400, "order body must be an object")
    symbol = str(payload.get("symbol") or "").strip()
    if not symbol:
        raise RoutingError(400, "symbol is required")
    return symbol
