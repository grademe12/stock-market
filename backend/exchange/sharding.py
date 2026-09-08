"""Deterministic symbol-to-matcher assignment. Keep this module Django-free."""

from collections.abc import Sequence


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
