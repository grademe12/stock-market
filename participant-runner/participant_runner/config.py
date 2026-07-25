from dataclasses import dataclass
import os


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
    max_traders: int | None
    trader_ids: tuple[str, ...]

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

        return cls(
            backend_base_url=backend_base_url,
            tick_interval_ms=_positive_int("TICK_INTERVAL_MS", 1_000) or 1_000,
            request_timeout_ms=_positive_int("REQUEST_TIMEOUT_MS", 5_000) or 5_000,
            max_traders=_positive_int("MAX_TRADERS"),
            trader_ids=trader_ids,
        )
