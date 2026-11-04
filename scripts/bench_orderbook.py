"""Micro-benchmark: cost of one order-book operation at a fixed resting depth.

Usage (from the repo root):
    python3 scripts/bench_orderbook.py                       # reference + current
    python3 scripts/bench_orderbook.py --impl current --depths 10000,100000,1000000

The book is prefilled with N non-crossing resting orders spread over price
levels around a reference price, like the participant-runner profiles
(quantity 1-15, a few dozen levels per side). Each operation is then timed one
call at a time. Results are per call: median and p99 in microseconds.

Operations
    rest        submit a non-crossing order that rests in the book
    match       submit a crossing order (qty 15) that fills at the best price
    cancel      cancel a random resting order
    lookup      get_open_order for a random resting order
    snapshot    aggregated price levels (GET /books/)
    depth       what views._update_orderbook_depth does after every POST/DELETE

Only exchange.orderbook is imported, so Django is not needed.
"""

from __future__ import annotations

import argparse
import gc
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from exchange.orderbook.book import OrderBook  # noqa: E402
from exchange.orderbook.reference_book import ReferenceOrderBook  # noqa: E402
from exchange.orderbook.types import (  # noqa: E402
    OpenOrder,
    Order,
    OrderNotFoundError,
    OrderSide,
)

SYMBOL = "005930"
REFERENCE_PRICE = 70_000
PRICE_STEP = 100
LEVELS_PER_SIDE = 20

IMPLEMENTATIONS = {
    "reference": ReferenceOrderBook,
    "current": OrderBook,
}


def rss_mib() -> float:
    try:
        pages = int(Path("/proc/self/statm").read_text().split()[1])
    except OSError:
        return float("nan")
    return pages * 4096 / 2**20


def resting_order(rng: random.Random, side: OrderSide) -> Order:
    offset = rng.randint(1, LEVELS_PER_SIDE) * PRICE_STEP
    price = REFERENCE_PRICE - offset if side is OrderSide.BUY else REFERENCE_PRICE + offset
    return Order(
        user_id=f"bench-{rng.randrange(1000)}",
        symbol=SYMBOL,
        side=side,
        price=price,
        quantity=rng.randint(1, 15),
    )


def prefill(book, depth: int, rng: random.Random) -> list[Order]:
    orders = [resting_order(rng, OrderSide.BUY if i % 2 else OrderSide.SELL) for i in range(depth)]
    if isinstance(book, ReferenceOrderBook):
        # One submit per order would re-sort the whole list every time
        # (that is the cost being measured), so building 1M orders that way
        # would take hours. Build the same state directly and sort once.
        for order in orders:
            book._sequence += 1
            target = book._bids if order.side is OrderSide.BUY else book._asks
            target.append(OpenOrder(order=order, remaining_quantity=order.quantity, sequence=book._sequence))
        book._bids.sort(key=lambda item: (-item.order.price, item.sequence))
        book._asks.sort(key=lambda item: (item.order.price, item.sequence))
    else:
        for order in orders:
            book.submit(order)
    return orders


def depth_totals(book) -> tuple[int, int]:
    total = getattr(book, "total_quantity", None)
    if total is not None:
        return total(OrderSide.BUY), total(OrderSide.SELL)
    snapshot = book.snapshot()
    return (
        sum(level.quantity for level in snapshot.bids),
        sum(level.quantity for level in snapshot.asks),
    )


def best_bid_price(book) -> int:
    snapshot = book.snapshot() if isinstance(book, ReferenceOrderBook) else None
    if snapshot is not None:
        return snapshot.bids[0].price
    return book.best_price(OrderSide.BUY)


def time_calls(fn, repeats: int, setup=None) -> list[float]:
    samples = []
    for _ in range(repeats):
        arg = setup() if setup else None
        started = time.perf_counter()
        fn(arg)
        samples.append((time.perf_counter() - started) * 1e6)
    return samples


def bench_one(impl_name: str, depth: int, repeats: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    book = IMPLEMENTATIONS[impl_name](symbol=SYMBOL)
    gc.collect()
    rss_before = rss_mib()
    started = time.perf_counter()
    orders = prefill(book, depth, rng)
    prefill_s = time.perf_counter() - started
    rss_after = rss_mib()

    alive = [order.order_id for order in orders]

    def pick_alive():
        while True:
            order_id = alive[rng.randrange(len(alive))]
            if book.get_open_order(order_id) is not None:
                return order_id

    results: dict[str, object] = {
        "impl": impl_name,
        "depth": depth,
        "prefill_s": prefill_s,
        "rss_mib": rss_after - rss_before,
    }

    gc.disable()
    try:
        results["rest"] = time_calls(
            lambda order: book.submit(order),
            repeats,
            setup=lambda: resting_order(rng, OrderSide.BUY),
        )

        def crossing_order(_=None):
            return Order(
                user_id="bench-taker",
                symbol=SYMBOL,
                side=OrderSide.SELL,
                price=best_bid_price(book),
                quantity=15,
            )

        results["match"] = time_calls(lambda order: book.submit(order), repeats, setup=crossing_order)

        def cancel(order_id):
            try:
                book.cancel(order_id)
            except OrderNotFoundError:
                pass

        results["cancel"] = time_calls(cancel, repeats, setup=pick_alive)
        results["lookup"] = time_calls(lambda order_id: book.get_open_order(order_id), repeats, setup=pick_alive)
        results["snapshot"] = time_calls(lambda _: book.snapshot(), max(5, repeats // 10))
        results["depth"] = time_calls(lambda _: depth_totals(book), max(5, repeats // 10))
    finally:
        gc.enable()
    return results


OPERATIONS = ("rest", "match", "cancel", "lookup", "snapshot", "depth")


def percentile(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def fmt_us(value: float) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f} ms"
    return f"{value:.1f} us"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--impl", default="reference,current", help="comma list: reference,current")
    parser.add_argument("--depths", default="10000,100000,1000000")
    parser.add_argument("--repeats", type=int, default=200, help="calls per operation at the smallest depth")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    impls = [name.strip() for name in args.impl.split(",") if name.strip()]
    depths = [int(value) for value in args.depths.split(",")]

    print(f"python {sys.version.split()[0]}, levels/side={LEVELS_PER_SIDE}, qty 1-15, seed={args.seed}")
    print("per call: median / p99\n")
    header = ["impl", "depth", "prefill", "rss MiB", *OPERATIONS]
    print(" | ".join(header))
    print(" | ".join("---" for _ in header))
    for impl_name in impls:
        for depth in depths:
            # Fewer repeats at large depth for the O(n) reference, or it runs for minutes.
            repeats = args.repeats if impl_name == "current" else max(20, args.repeats * 10_000 // depth)
            result = bench_one(impl_name, depth, repeats, args.seed)
            cells = [
                impl_name,
                f"{depth:,}",
                f"{result['prefill_s']:.1f} s",
                f"{result['rss_mib']:.0f}",
            ]
            for op in OPERATIONS:
                samples = result[op]
                cells.append(f"{fmt_us(statistics.median(samples))} / {fmt_us(percentile(samples, 0.99))}")
            print(" | ".join(cells), flush=True)


if __name__ == "__main__":
    main()
