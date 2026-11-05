"""Pull Day 7 report numbers from Prometheus at fixed KST times (30 min windows).

Usage: python3 pull_report.py <prom_base_url> "11-04 13:15,11-04 15:15"
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = sys.argv[1]
KST = timezone(timedelta(hours=9))
W = "30m"

QUERIES = {
    "depth_qty": 'sum(last_over_time(orderbook_depth[1h]))',
    "orders_s": f'sum(increase(orders_submitted_total[{W}]))/1800',
    "cancel_s": f'sum(increase(http_requests_total{{method="DELETE"}}[{W}]))/1800',
    "book_get_s": f'sum(increase(http_requests_total{{method="GET",route="api/v1/books/<str:symbol>/"}}[{W}]))/1800',
    "trades_s": f'sum(increase(trades_executed_total[{W}]))/1800',
    "post_p50_ms": f'1000*histogram_quantile(0.5, sum by (le) (increase(http_request_duration_seconds_bucket{{method="POST"}}[{W}])))',
    "post_p99_ms": f'1000*histogram_quantile(0.99, sum by (le) (increase(http_request_duration_seconds_bucket{{method="POST"}}[{W}])))',
    "del_p50_ms": f'1000*histogram_quantile(0.5, sum by (le) (increase(http_request_duration_seconds_bucket{{method="DELETE"}}[{W}])))',
    "cpu_cores": f'sum(rate(process_cpu_seconds_total{{job="stock-market-backend"}}[{W}]))',
    "cpu_max_shard": f'max(rate(process_cpu_seconds_total{{job="stock-market-backend"}}[{W}]))',
    "rss_gib": 'sum(last_over_time(process_resident_memory_bytes{job="stock-market-backend"}[1h]))/2^30',
    "up_frac": f'avg(avg_over_time(up{{job="stock-market-backend"}}[{W}]))',
    "http_5xx_s": f'sum(increase(http_requests_total{{status=~"5.."}}[{W}]))/1800',
    "rejected_s": f'sum(increase(orders_rejected_total[{W}]))/1800',
    "runner_sub_s": f'sum(increase(runner_orders_submitted_total[{W}]))/1800',
    "runner_inflight": 'sum(runner_http_in_flight)',
    "open_orders": 'sum(last_over_time(orderbook_open_orders[1h]))',
    "expired_s": f'sum(increase(orders_expired_total[{W}]))/1800',
}

# Usage: python3 pull_report.py <prom_base_url> "11-02 17:20,11-03 17:45"
TIMES = sys.argv[2].split(",")


def q(expr, ts):
    url = f"{BASE}/api/v1/query?" + urllib.parse.urlencode({"query": expr, "time": ts})
    with urllib.request.urlopen(url, timeout=30) as r:
        res = json.load(r)["data"]["result"]
    if not res:
        return None
    return float(res[0]["value"][1])


rows = []
for t in TIMES:
    dt = datetime.strptime(f"2026-{t}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    ts = dt.timestamp()
    row = {"t": t}
    for k, e in QUERIES.items():
        try:
            row[k] = q(e, ts)
        except Exception as exc:  # noqa: BLE001
            row[k] = f"err:{exc}"
    rows.append(row)

keys = ["t"] + list(QUERIES)
print("\t".join(keys))
for r in rows:
    print("\t".join("-" if r[k] is None else (f"{r[k]:.3g}" if isinstance(r[k], float) else str(r[k])) for k in keys))
