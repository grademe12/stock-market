"""Run the symbol gateway against localhost matcher processes."""

from __future__ import annotations

import argparse
import os

from gateway.proxy import serve


def _tickers_from_env() -> tuple[str, ...]:
    raw = os.getenv("GATEWAY_TICKERS", "").strip()
    return tuple(ticker.strip() for ticker in raw.split(",") if ticker.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Route orders to the matcher that owns the symbol")
    parser.add_argument("--bind", default=os.getenv("GATEWAY_BIND", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GATEWAY_PORT", "8000")))
    parser.add_argument(
        "--shard-count",
        type=int,
        default=int(os.getenv("SIMULATION_SHARD_COUNT", "1")),
    )
    parser.add_argument(
        "--first-matcher-port",
        type=int,
        default=int(os.getenv("GATEWAY_FIRST_MATCHER_PORT", "8001")),
    )
    parser.add_argument(
        "--matcher-host",
        default=os.getenv("GATEWAY_MATCHER_HOST", "127.0.0.1"),
    )
    arguments = parser.parse_args()
    tickers = _tickers_from_env()
    if not tickers:
        raise SystemExit("set GATEWAY_TICKERS to the ordered simulation universe")
    if arguments.shard_count < 1:
        raise SystemExit("SIMULATION_SHARD_COUNT must be at least 1")
    serve(
        arguments.bind,
        arguments.port,
        tickers=tickers,
        shard_count=arguments.shard_count,
        matcher_host=arguments.matcher_host,
        first_matcher_port=arguments.first_matcher_port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
