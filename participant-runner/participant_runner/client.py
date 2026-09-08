import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from exchange.orderbook import BookLevel, BookSnapshot
from exchange.participants.types import OrderIntent


class BackendApiError(RuntimeError):
    def __init__(self, status_code: int | None, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class SubmittedOrder:
    order_id: str
    remaining_quantity: int


@dataclass(frozen=True, slots=True)
class CancellationResult:
    status: str


class BackendApiClient:
    """Small standard-library client for the public backend API contract."""

    def __init__(self, base_url: str, timeout_ms: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_ms / 1_000

    def fetch_trader_profiles(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/v1/traders/")
        if not isinstance(payload, list):
            raise BackendApiError(None, "trader profile response must be a list")
        return payload

    def fetch_book(self, symbol: str) -> BookSnapshot:
        payload = self._request("GET", f"/api/v1/books/{symbol}/")
        try:
            payload_symbol = str(payload["symbol"])
            bids = self._book_levels(payload["bids"])
            asks = self._book_levels(payload["asks"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BackendApiError(None, "book response has an invalid shape") from exc
        if payload_symbol != symbol:
            raise BackendApiError(None, "book response symbol does not match request")
        return BookSnapshot(symbol=payload_symbol, bids=bids, asks=asks)

    def submit_order(self, intent: OrderIntent) -> SubmittedOrder:
        payload = self._request(
            "POST",
            "/api/v1/orders/",
            {
                "user_id": intent.user_id,
                "symbol": intent.symbol,
                "side": intent.side.value,
                "price": intent.price,
                "qty": intent.quantity,
            },
        )
        try:
            return SubmittedOrder(
                order_id=str(payload["order_id"]),
                remaining_quantity=int(payload["remaining_qty"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BackendApiError(None, "order response has an invalid shape") from exc

    def fetch_matcher_shards(self) -> dict[str, int]:
        payload = self._request("GET", "/api/v1/symbols/?limit=100")
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise BackendApiError(None, "symbol response must include results")
        shards: dict[str, int] = {}
        for item in payload["results"]:
            if not isinstance(item, dict) or not item.get("simulation_enabled"):
                continue
            ticker = str(item["ticker"])
            raw_shard = item.get("matcher_shard")
            if raw_shard is None:
                continue
            shards[ticker] = int(raw_shard)
        return shards

    def cancel_order(self, order_id: str, symbol: str = "") -> CancellationResult:
        path = f"/api/v1/orders/{order_id}/"
        if symbol:
            path = f"{path}?symbol={symbol}"
        payload = self._request("DELETE", path)
        try:
            result = CancellationResult(status=str(payload["status"]))
        except (KeyError, TypeError) as exc:
            raise BackendApiError(None, "cancel response has an invalid shape") from exc
        if result.status not in {"CANCELED", "ALREADY_CLOSED"}:
            raise BackendApiError(None, f"unexpected cancel status: {result.status}")
        return result

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BackendApiError(exc.code, detail) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BackendApiError(None, str(exc)) from exc

    @staticmethod
    def _book_levels(payload: Any) -> tuple[BookLevel, ...]:
        if not isinstance(payload, list):
            raise ValueError("book levels must be a list")
        levels = []
        for level in payload:
            price = int(level["price"])
            quantity = int(level["qty"])
            if price < 1 or quantity < 1:
                raise ValueError("book level values must be positive")
            levels.append(BookLevel(price=price, quantity=quantity))
        return tuple(levels)


class ShardedBackendClient:
    """Send book, order, and cancel calls to the matcher that owns the symbol."""

    def __init__(
        self,
        clients: tuple[BackendApiClient, ...],
        shards: dict[str, int],
    ) -> None:
        if not clients:
            raise BackendApiError(None, "at least one backend shard URL is required")
        self._clients = clients
        self._shards = shards

    def fetch_trader_profiles(self) -> list[dict[str, Any]]:
        return self._clients[0].fetch_trader_profiles()

    def fetch_book(self, symbol: str) -> BookSnapshot:
        return self._client_for(symbol).fetch_book(symbol)

    def submit_order(self, intent: OrderIntent) -> SubmittedOrder:
        return self._client_for(intent.symbol).submit_order(intent)

    def cancel_order(self, order_id: str, symbol: str = "") -> CancellationResult:
        if not symbol:
            raise BackendApiError(None, "cancel requires a symbol when shards are enabled")
        return self._client_for(symbol).cancel_order(order_id, symbol)

    def _client_for(self, symbol: str) -> BackendApiClient:
        shard = self._shards.get(symbol)
        if shard is None:
            raise BackendApiError(None, f"no matcher shard for {symbol}")
        if shard < 0 or shard >= len(self._clients):
            raise BackendApiError(None, f"matcher shard {shard} is not configured")
        return self._clients[shard]
