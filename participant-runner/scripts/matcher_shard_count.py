#!/usr/bin/env python3
"""Print SIMULATION_SHARD_COUNT from the matcher /api/v1/ready/ response."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main() -> int:
    _load_env(Path(__file__).resolve().parent.parent / ".env")
    base_url = os.environ.get("BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        with urlopen(f"{base_url}/api/v1/ready/", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print(f"matcher ready check failed: {exc.__class__.__name__}", flush=True)
        return 1
    shard_count = payload.get("shard_count")
    if not isinstance(shard_count, int) or shard_count < 1:
        print("ready payload is missing shard_count", flush=True)
        return 1
    print(shard_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
