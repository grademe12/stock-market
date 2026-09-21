"""Build Prometheus HTTP SD that stays on the public gateway entry."""

from __future__ import annotations

from exchange.sharding import advertised_hostname


def advertised_scrape_target(host_header: str, default_port: int) -> str:
    """Turn an HTTP Host header into host:port for Prometheus targets."""
    if default_port < 1:
        raise ValueError("default_port must be at least 1")
    hostname = advertised_hostname(host_header)
    port = _port_from_host_header(host_header, default_port)
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{host}:{port}"


def prometheus_sd_targets(target: str, shard_count: int) -> list[dict[str, object]]:
    """Advertise one public target per shard, with a gateway metrics path."""
    if not target.strip():
        raise ValueError("target is required")
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    return [
        {
            "targets": [target],
            "labels": {
                "matcher_shard": str(index),
                "__metrics_path__": f"/metrics/{index}/",
            },
        }
        for index in range(shard_count)
    ]


def _port_from_host_header(host_header: str, default_port: int) -> int:
    host = host_header.strip()
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            raise ValueError("invalid IPv6 host header")
        rest = host[end + 1 :]
        if rest.startswith(":"):
            return _parse_port(rest[1:])
        return default_port
    if host.count(":") == 1:
        return _parse_port(host.split(":", 1)[1])
    return default_port


def _parse_port(raw: str) -> int:
    port = int(raw)
    if port < 1:
        raise ValueError("port must be at least 1")
    return port
