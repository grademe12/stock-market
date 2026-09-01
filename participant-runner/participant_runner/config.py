from dataclasses import dataclass
import os
from pathlib import Path

from exchange.participants.types import SUPPORTED_STRATEGIES


class ConfigurationError(ValueError):
    pass


def _positive_int(name: str, default: int | None = None) -> int | None:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < 1:
        raise ConfigurationError(f"{name} must be at least 1")
    return value


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Container/runtime settings, separate from individual trader profiles."""

    backend_base_url: str
    tick_interval_ms: int
    request_timeout_ms: int
    status_log_interval_ticks: int
    max_traders: int | None
    trader_ids: tuple[str, ...]
    trader_strategies: tuple[str, ...]
    scenario_path: Path | None

    @classmethod
    def from_environment(cls) -> "RunnerConfig":
        backend_base_url = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        if not backend_base_url.startswith(("http://", "https://")):
            raise ConfigurationError("BACKEND_BASE_URL must start with http:// or https://")

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
            tick_interval_ms=_positive_int("TICK_INTERVAL_MS", 1_000) or 1_000,
            request_timeout_ms=_positive_int("REQUEST_TIMEOUT_MS", 5_000) or 5_000,
            status_log_interval_ticks=(
                _positive_int("RUNNER_STATUS_LOG_INTERVAL_TICKS", 60) or 60
            ),
            max_traders=_positive_int("MAX_TRADERS"),
            trader_ids=trader_ids,
            trader_strategies=trader_strategies,
            scenario_path=Path(raw_scenario) if raw_scenario else None,
        )
