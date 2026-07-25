import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from exchange.participants.types import OrderIntent


class BackendApiError(RuntimeError):
    def __init__(self, status_code: int | None, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


class OrderAlreadyClosedError(BackendApiError):
    pass


@dataclass(frozen=True, slots=True)
class SubmittedOrder:
    order_id: str
    remaining_quantity: int


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

    def cancel_order(self, order_id: str) -> None:
        try:
            self._request("DELETE", f"/api/v1/orders/{order_id}/")
        except BackendApiError as exc:
            if exc.status_code == 404:
                raise OrderAlreadyClosedError(exc.status_code, str(exc)) from exc
            raise

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
