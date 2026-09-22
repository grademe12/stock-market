from dataclasses import dataclass
import os
from pathlib import Path

from exchange.market_session import SCHEDULED, SUPPORTED_MARKET_MODES
from exchange.participants.types import SUPPORTED_STRATEGIES


class ConfigurationError(ValueError):
    pass


HTTP_CONCURRENCY_DEFAULT = 16
HTTP_CONCURRENCY_MAXIMUM = 128


def _choice(name: str, default: str, choices: set[str] | frozenset[str]) -> str:
    value = os.getenv(name, default).strip() or default
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ConfigurationError(f"{name} must be one of: {allowed}")
    return value


def _parse_int(name: str, raw_value: str) -> int:
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _positive_int(
    name: str,
    default: int | None = None,
    *,
    maximum: int | None = None,
) -> int | None:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    value = _parse_int(name, raw_value)
    if value < 1:
        raise ConfigurationError(f"{name} must be at least 1")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be between 1 and {maximum}")
    return value


def _non_negative_int(name: str) -> int | None:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return None
    value = _parse_int(name, raw_value)
    if value < 0:
        raise ConfigurationError(f"{name} must be at least 0")
    return value


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Container/runtime settings, separate from individual trader profiles."""

    backend_base_url: str
    backend_shard_urls: tuple[str, ...]
    simulation_market_mode: str
    tick_interval_ms: int
    request_timeout_ms: int
    status_log_interval_ticks: int
    max_traders: int | None
    http_concurrency: int
    trader_ids: tuple[str, ...]
    trader_strategies: tuple[str, ...]
    runner_shard_index: int | None
    scenario_path: Path | None
    metrics_bind: str
    metrics_port: int | None

    @classmethod
    def from_environment(cls) -> "RunnerConfig":
        backend_base_url = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        if not backend_base_url.startswith(("http://", "https://")):
            raise ConfigurationError("BACKEND_BASE_URL must start with http:// or https://")
        raw_shard_urls = os.getenv("BACKEND_SHARD_URLS", "").strip()
        if raw_shard_urls:
            backend_shard_urls = tuple(
                url.strip().rstrip("/")
                for url in raw_shard_urls.split(",")
                if url.strip()
            )
        else:
            backend_shard_urls = (backend_base_url,)
        if not backend_shard_urls:
            raise ConfigurationError("BACKEND_SHARD_URLS must contain at least one URL")
        if len(set(backend_shard_urls)) != len(backend_shard_urls):
            raise ConfigurationError("BACKEND_SHARD_URLS must not contain duplicates")
        for url in backend_shard_urls:
            if not url.startswith(("http://", "https://")):
                raise ConfigurationError(
                    "BACKEND_SHARD_URLS must start with http:// or https://"
                )

        trader_ids = tuple(
            trader_id.strip()
            for trader_id in os.getenv("TRADER_IDS", "").split(",")
            if trader_id.strip()
        )
        if len(set(trader_ids)) != len(trader_ids):
            raise ConfigurationError("TRADER_IDS must not contain duplicates")

        trader_strategies = tuple(
            strategy.strip()
            for strategy in os.getenv("TRADER_STRATEGIES", "").split(",")
            if strategy.strip()
        )
        if len(set(trader_strategies)) != len(trader_strategies):
            raise ConfigurationError("TRADER_STRATEGIES must not contain duplicates")
        unsupported_strategies = set(trader_strategies) - set(SUPPORTED_STRATEGIES)
        if unsupported_strategies:
            unsupported = ", ".join(sorted(unsupported_strategies))
            raise ConfigurationError(f"unsupported TRADER_STRATEGIES: {unsupported}")

        raw_scenario = os.getenv("SCENARIO_PATH", "").strip()
        return cls(
            backend_base_url=backend_base_url,
            backend_shard_urls=backend_shard_urls,
            simulation_market_mode=_choice(
                "SIMULATION_MARKET_MODE",
                SCHEDULED,
                SUPPORTED_MARKET_MODES,
            ),
            tick_interval_ms=_positive_int("TICK_INTERVAL_MS", 1_000) or 1_000,
            request_timeout_ms=_positive_int("REQUEST_TIMEOUT_MS", 5_000) or 5_000,
            status_log_interval_ticks=(
                _positive_int("RUNNER_STATUS_LOG_INTERVAL_TICKS", 60) or 60
            ),
            max_traders=_positive_int("MAX_TRADERS"),
            http_concurrency=_positive_int(
                "HTTP_CONCURRENCY",
                HTTP_CONCURRENCY_DEFAULT,
                maximum=HTTP_CONCURRENCY_MAXIMUM,
            )
            or HTTP_CONCURRENCY_DEFAULT,
            trader_ids=trader_ids,
            trader_strategies=trader_strategies,
            runner_shard_index=_non_negative_int("RUNNER_SHARD_INDEX"),
            scenario_path=Path(raw_scenario) if raw_scenario else None,
            metrics_bind=os.getenv("METRICS_BIND", "0.0.0.0").strip() or "0.0.0.0",
            metrics_port=_non_negative_int("METRICS_PORT"),
        )
