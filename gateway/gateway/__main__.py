"""Run the symbol gateway against matcher processes."""

from __future__ import annotations

import argparse
import os

from gateway.proxy import serve
from gateway.universe import wait_for_tickers


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


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
    shard_urls = _csv_env("GATEWAY_SHARD_URLS")
    tickers = _csv_env("GATEWAY_TICKERS")
    if arguments.shard_count < 1:
        raise SystemExit("SIMULATION_SHARD_COUNT must be at least 1")
    if shard_urls and len(shard_urls) != arguments.shard_count:
        raise SystemExit("GATEWAY_SHARD_URLS must match SIMULATION_SHARD_COUNT")
    if not tickers:
        universe_url = os.getenv("GATEWAY_UNIVERSE_URL", "").strip()
        if not universe_url:
            if shard_urls:
                universe_url = shard_urls[0]
            else:
                universe_url = f"http://{arguments.matcher_host}:{arguments.first_matcher_port}"
        tickers = wait_for_tickers(universe_url)
    serve(
        arguments.bind,
        arguments.port,
        tickers=tickers,
        shard_count=arguments.shard_count,
        matcher_host=arguments.matcher_host,
        first_matcher_port=arguments.first_matcher_port,
        shard_urls=shard_urls,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
