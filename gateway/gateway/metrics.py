"""Prometheus metrics for the gateway, written with the standard library only.

The gateway image has no third-party packages, so this module keeps a few
counters and histograms under one lock and renders the text exposition
format itself. Served at ``/gateway/metrics``.

What it answers: where a request's time goes before and after the matcher.

    kernel accept queue   gateway_listen_queue (sampled at scrape time)
    accept -> handler     gateway_accept_wait_seconds (thread start, GIL)
    handler total         gateway_request_duration_seconds
      of which matcher    gateway_upstream_duration_seconds
"""

from __future__ import annotations

from bisect import bisect_left
import os
import resource
import threading
import time

# Finer than the prometheus_client defaults below 0.1s and doubling above,
# so a p50 that moves from a few ms to hundreds of ms stays readable.
DURATION_BUCKETS = (
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.2,
    0.4,
    0.8,
    1.6,
    3.2,
    6.4,
)


class Histogram:
    __slots__ = ("bounds", "counts", "total", "count")

    def __init__(self, bounds: tuple[float, ...] = DURATION_BUCKETS) -> None:
        self.bounds = bounds
        self.counts = [0] * (len(bounds) + 1)  # last slot is +Inf
        self.total = 0.0
        self.count = 0

    def observe(self, value: float) -> None:
        # bisect_left puts a value equal to a bound into that bound's bucket (le).
        self.counts[bisect_left(self.bounds, value)] += 1
        self.total += value
        self.count += 1


class GatewayMetrics:
    def __init__(self, *, listen_port: int | None = None, clock=time.perf_counter) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self.listen_port = listen_port
        self._requests: dict[tuple[str, str], int] = {}
        self._durations: dict[str, Histogram] = {}
        self._upstream: dict[str, Histogram] = {}
        self._upstream_errors: dict[str, int] = {}
        self._accept_wait = Histogram()
        self._in_flight = 0

    def now(self) -> float:
        return self._clock()

    def request_started(self) -> None:
        with self._lock:
            self._in_flight += 1

    def request_finished(self, method: str, status: int, seconds: float) -> None:
        key = (method, str(status))
        with self._lock:
            self._in_flight -= 1
            self._requests[key] = self._requests.get(key, 0) + 1
            histogram = self._durations.get(method)
            if histogram is None:
                histogram = self._durations[method] = Histogram()
            histogram.observe(seconds)

    def observe_accept_wait(self, seconds: float) -> None:
        with self._lock:
            self._accept_wait.observe(seconds)

    def observe_upstream(self, shard: int, seconds: float, *, failed: bool = False) -> None:
        label = str(shard)
        with self._lock:
            histogram = self._upstream.get(label)
            if histogram is None:
                histogram = self._upstream[label] = Histogram()
            histogram.observe(seconds)
            if failed:
                self._upstream_errors[label] = self._upstream_errors.get(label, 0) + 1

    def render(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            durations = {key: _copy(value) for key, value in self._durations.items()}
            upstream = {key: _copy(value) for key, value in self._upstream.items()}
            upstream_errors = dict(self._upstream_errors)
            accept_wait = _copy(self._accept_wait)
            in_flight = self._in_flight

        lines: list[str] = []
        _header(lines, "gateway_requests_total", "counter", "Requests answered by the gateway.")
        for (method, status), value in sorted(requests.items()):
            lines.append(f'gateway_requests_total{{method="{method}",status="{status}"}} {value}')

        _header(
            lines,
            "gateway_request_duration_seconds",
            "histogram",
            "From the handler starting to the response written, by method.",
        )
        for method, histogram in sorted(durations.items()):
            _histogram(lines, "gateway_request_duration_seconds", f'method="{method}"', histogram)

        _header(
            lines,
            "gateway_upstream_duration_seconds",
            "histogram",
            "Matcher round trip (connect, request, read) by shard.",
        )
        for shard, histogram in sorted(upstream.items()):
            _histogram(lines, "gateway_upstream_duration_seconds", f'shard="{shard}"', histogram)

        _header(lines, "gateway_upstream_errors_total", "counter", "Matcher round trips that failed (502).")
        for shard, value in sorted(upstream_errors.items()):
            lines.append(f'gateway_upstream_errors_total{{shard="{shard}"}} {value}')

        _header(
            lines,
            "gateway_accept_wait_seconds",
            "histogram",
            "From accept() to the handler thread starting. Grows when threads wait for the GIL.",
        )
        _histogram(lines, "gateway_accept_wait_seconds", "", accept_wait)

        _header(lines, "gateway_in_flight_requests", "gauge", "Requests being handled right now.")
        lines.append(f"gateway_in_flight_requests {in_flight}")

        _header(lines, "gateway_threads", "gauge", "Live Python threads in the gateway process.")
        lines.append(f"gateway_threads {threading.active_count()}")

        if self.listen_port is not None:
            queue = listen_queue_length(self.listen_port)
            if queue is not None:
                _header(
                    lines,
                    "gateway_listen_queue",
                    "gauge",
                    "Connections accepted by the kernel but not yet by the gateway (ss Recv-Q).",
                )
                lines.append(f"gateway_listen_queue {queue}")

        usage = resource.getrusage(resource.RUSAGE_SELF)
        _header(lines, "process_cpu_seconds_total", "counter", "User and system CPU time of the gateway.")
        lines.append(f"process_cpu_seconds_total {usage.ru_utime + usage.ru_stime:.3f}")
        rss = resident_memory_bytes()
        if rss is not None:
            _header(lines, "process_resident_memory_bytes", "gauge", "Resident memory of the gateway.")
            lines.append(f"process_resident_memory_bytes {rss}")
        return "\n".join(lines) + "\n"


def _copy(histogram: Histogram) -> Histogram:
    copied = Histogram(histogram.bounds)
    copied.counts = list(histogram.counts)
    copied.total = histogram.total
    copied.count = histogram.count
    return copied


def _header(lines: list[str], name: str, kind: str, help_text: str) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {kind}")


def _histogram(lines: list[str], name: str, labels: str, histogram: Histogram) -> None:
    prefix = f"{labels}," if labels else ""
    cumulative = 0
    for bound, count in zip(histogram.bounds, histogram.counts):
        cumulative += count
        lines.append(f'{name}_bucket{{{prefix}le="{bound}"}} {cumulative}')
    cumulative += histogram.counts[-1]
    lines.append(f'{name}_bucket{{{prefix}le="+Inf"}} {cumulative}')
    suffix = f"{{{labels}}}" if labels else ""
    lines.append(f"{name}_sum{suffix} {histogram.total:.6f}")
    lines.append(f"{name}_count{suffix} {histogram.count}")


_TCP_LISTEN = "0A"


def listen_queue_length(port: int, *, sources: tuple[str, ...] = ("/proc/net/tcp", "/proc/net/tcp6")) -> int | None:
    """Current accept-queue length of the listening socket on ``port``.

    For a socket in LISTEN state the kernel reports the accept queue in the
    ``rx_queue`` column of /proc/net/tcp (what ``ss`` shows as Recv-Q). The
    gateway runs with host networking, so this is the host's socket.
    Returns None when the file is unavailable (not Linux, sandboxed).
    """
    found = False
    total = 0
    for source in sources:
        try:
            with open(source, encoding="ascii") as handle:
                text = handle.read()
        except OSError:
            continue
        found = True
        total += parse_listen_queue(text, port)
    return total if found else None


def parse_listen_queue(text: str, port: int) -> int:
    wanted = f"{port:04X}"
    total = 0
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 5 or fields[3] != _TCP_LISTEN:
            continue
        if fields[1].rsplit(":", 1)[-1] != wanted:
            continue
        rx_queue = fields[4].split(":", 1)[1]
        total += int(rx_queue, 16)
    return total


def resident_memory_bytes() -> int | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return pages * os.sysconf("SC_PAGE_SIZE")
