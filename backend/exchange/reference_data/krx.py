from dataclasses import dataclass
from datetime import date
import json
import os
import re
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class KrxConfigurationError(RuntimeError):
    pass


class KrxApiError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KrxDailyRecord:
    ticker: str
    name: str
    market: str
    trade_date: date
    close_price: int
    volume: int
    trading_value: int
    source_payload: dict[str, str]


def _integer(value: object, field_name: str) -> int:
    normalized = str(value).replace(",", "").strip()
    if normalized in {"", "-"}:
        return 0
    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise KrxApiError(f"KRX field {field_name} is not an integer") from exc
    if parsed < 0:
        raise KrxApiError(f"KRX field {field_name} must not be negative")
    return parsed


def _parse_record(payload: object) -> KrxDailyRecord:
    if not isinstance(payload, dict):
        raise KrxApiError("KRX daily record must be an object")

    try:
        ticker = str(payload["ISU_CD"]).strip()
        name = str(payload["ISU_NM"]).strip()
        market = str(payload["MKT_NM"]).strip()
        trade_date = date.fromisoformat(
            f"{str(payload['BAS_DD'])[0:4]}-{str(payload['BAS_DD'])[4:6]}-{str(payload['BAS_DD'])[6:8]}"
        )
    except (KeyError, ValueError) as exc:
        raise KrxApiError("KRX daily record is missing an identity field") from exc

    if not re.fullmatch(r"[0-9A-Z]{6}", ticker):
        raise KrxApiError("KRX ISU_CD must be a six-character KRX short code")
    if not name:
        raise KrxApiError("KRX ISU_NM must not be blank")
    if market != "KOSPI":
        raise KrxApiError("KRX record market must be KOSPI")

    return KrxDailyRecord(
        ticker=ticker,
        name=name,
        market=market,
        trade_date=trade_date,
        close_price=_integer(payload.get("TDD_CLSPRC"), "TDD_CLSPRC"),
        volume=_integer(payload.get("ACC_TRDVOL"), "ACC_TRDVOL"),
        trading_value=_integer(payload.get("ACC_TRDVAL"), "ACC_TRDVAL"),
        source_payload={str(key): str(value) for key, value in payload.items()},
    )


class KrxOpenApiClient:
    endpoint = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 10,
        max_attempts: int = 3,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("KRX_API_KEY", "")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._opener = opener

    def fetch_daily(self, trade_date: date) -> tuple[KrxDailyRecord, ...]:
        if not self._api_key.strip():
            raise KrxConfigurationError("KRX_API_KEY is required")

        query = urlencode({"basDd": trade_date.strftime("%Y%m%d")})
        request = Request(
            f"{self.endpoint}?{query}",
            headers={
                "AUTH_KEY": self._api_key,
                "Accept": "application/json",
                "User-Agent": "stock-market-reference-import/1.0",
            },
        )

        payload = self._request_json(request)
        response_code = str(payload.get("respCode", "")).strip()
        if response_code and response_code != "200":
            raise KrxApiError(f"KRX API rejected the request with code {response_code}")

        rows = payload.get("OutBlock_1")
        if not isinstance(rows, list):
            raise KrxApiError("KRX response does not contain OutBlock_1")

        records = tuple(_parse_record(row) for row in rows)
        if any(record.trade_date != trade_date for record in records):
            raise KrxApiError("KRX response trade date does not match the request")
        return records

    def _request_json(self, request: Request) -> dict[str, object]:
        for attempt in range(1, self._max_attempts + 1):
            try:
                with self._opener(request, timeout=self._timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise KrxApiError("KRX response must be a JSON object")
                return payload
            except HTTPError as exc:
                if exc.code < 500 or attempt == self._max_attempts:
                    raise KrxApiError(f"KRX API HTTP error {exc.code}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt == self._max_attempts:
                    raise KrxApiError("KRX API request failed") from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise KrxApiError("KRX API returned invalid JSON") from exc

            time.sleep(0.2 * attempt)

        raise AssertionError("unreachable")
