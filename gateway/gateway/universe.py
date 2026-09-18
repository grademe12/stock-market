"""Load the ordered simulation ticker universe from a matcher symbols API."""

from __future__ import annotations

import json
from time import sleep
from urllib.error import URLError
from urllib.request import urlopen


def tickers_from_symbols_payload(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("symbol response must include results")
    tickers: list[str] = []
    for item in payload["results"]:
        if not isinstance(item, dict) or not item.get("simulation_enabled"):
            continue
        ticker = str(item.get("ticker") or "").strip()
        if ticker:
            tickers.append(ticker)
    if not tickers:
        raise ValueError("symbol response has no simulated tickers")
    return tuple(tickers)


def fetch_tickers(base_url: str, *, timeout_seconds: float = 5.0) -> tuple[str, ...]:
    url = f"{base_url.rstrip('/')}/api/v1/symbols/?limit=100"
    with urlopen(url, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return tickers_from_symbols_payload(payload)


def wait_for_tickers(base_url: str, *, attempts: int = 20, delay_seconds: float = 2.0) -> tuple[str, ...]:
    last_error = "matcher universe is unavailable"
    for _ in range(attempts):
        try:
            return fetch_tickers(base_url)
        except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            sleep(delay_seconds)
    raise RuntimeError(last_error)
