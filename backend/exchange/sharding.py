"""Deterministic symbol-to-matcher assignment. Keep this module Django-free."""

from collections.abc import Sequence
from urllib.parse import urlparse, urlunparse


def matcher_shard(position: int, shard_count: int) -> int:
    """Return the shard index for the ticker at this universe position."""
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if position < 0:
        raise ValueError("position must be at least 0")
    return position % shard_count


def owned_tickers(
    tickers: Sequence[str],
    shard_index: int,
    shard_count: int,
) -> tuple[str, ...]:
    """Keep every shard_count-th ticker starting at shard_index."""
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be in range(shard_count)")
    if shard_count == 1:
        return tuple(tickers)
    return tuple(
        ticker
        for position, ticker in enumerate(tickers)
        if matcher_shard(position, shard_count) == shard_index
    )


def shard_for_ticker(
    tickers: Sequence[str],
    ticker: str,
    shard_count: int,
) -> int | None:
    """Look up the shard for a ticker in an ordered universe, or None."""
    try:
        return matcher_shard(tickers.index(ticker), shard_count)
    except ValueError:
        return None


def advertised_hostname(host_header: str) -> str:
    """Strip a :port suffix from an HTTP Host header."""
    if not host_header.strip():
        raise ValueError("host header is required")
    host = host_header.strip()
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            raise ValueError("invalid IPv6 host header")
        return host[1:end]
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def matcher_topology_from_ready(payload: object) -> tuple[int, int, int]:
    """Read shard_index, shard_count, listen_port from /api/v1/ready/."""
    if not isinstance(payload, dict):
        raise ValueError("ready payload must be an object")
    try:
        shard_index = int(payload["shard_index"])
        shard_count = int(payload["shard_count"])
        listen_port = int(payload["listen_port"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("ready payload is missing shard topology") from exc
    if shard_count < 1 or not 0 <= shard_index < shard_count or listen_port < 1:
        raise ValueError("ready payload has an invalid shard topology")
    return shard_index, shard_count, listen_port


def matcher_shard_urls(
    seed_url: str,
    *,
    shard_index: int,
    shard_count: int,
    listen_port: int,
) -> tuple[str, ...]:
    """Build host-network shard URLs from one seed and that process's topology."""
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be in range(shard_count)")
    parsed = urlparse(seed_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("seed URL must be an absolute http(s) URL")
    base_port = listen_port - shard_index
    if base_port < 1:
        raise ValueError("listen_port is inconsistent with shard_index")
    path = parsed.path.rstrip("/")
    urls: list[str] = []
    for index in range(shard_count):
        port = base_port + index
        hostname = parsed.hostname
        netloc = f"[{hostname}]:{port}" if ":" in hostname else f"{hostname}:{port}"
        if parsed.username is not None:
            userinfo = parsed.username
            if parsed.password is not None:
                userinfo = f"{userinfo}:{parsed.password}"
            netloc = f"{userinfo}@{netloc}"
        urls.append(urlunparse((parsed.scheme, netloc, path, "", "", "")))
    return tuple(urls)


def resolve_matcher_shard_urls(
    configured: Sequence[str],
    *,
    shard_index: int,
    shard_count: int,
    listen_port: int,
) -> tuple[str, ...]:
    """Keep an explicit URL list when it already matches, otherwise expand ports."""
    seeds = tuple(url.rstrip("/") for url in configured if url and url.strip())
    if not seeds:
        raise ValueError("at least one shard URL is required")
    if len(seeds) == shard_count:
        return seeds
    hosts = {urlparse(url).hostname for url in seeds}
    if len(hosts) > 1:
        raise ValueError(
            f"configured {len(seeds)} shard URLs but matcher reports {shard_count} shards"
        )
    return matcher_shard_urls(
        seeds[0],
        shard_index=shard_index,
        shard_count=shard_count,
        listen_port=listen_port,
    )


def prometheus_sd_targets(hostname: str, shard_count: int, *, base_port: int = 8000) -> list[dict[str, object]]:
    """Prometheus HTTP SD payload for host-network matcher processes."""
    if not hostname.strip():
        raise ValueError("hostname is required")
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if base_port < 1:
        raise ValueError("base_port must be at least 1")
    return [
        {
            "targets": [f"{hostname}:{base_port + index}"],
            "labels": {"matcher_shard": str(index)},
        }
        for index in range(shard_count)
    ]
