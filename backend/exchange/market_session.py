from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


SEOUL = ZoneInfo("Asia/Seoul")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)
SCHEDULED = "scheduled"
ALWAYS_OPEN = "always_open"
SUPPORTED_MARKET_MODES = frozenset({SCHEDULED, ALWAYS_OPEN})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MarketSession:
    """KST weekday regular-session policy shared by matcher and runner."""

    def __init__(self, mode: str = SCHEDULED) -> None:
        if mode not in SUPPORTED_MARKET_MODES:
            allowed = ", ".join(sorted(SUPPORTED_MARKET_MODES))
            raise ValueError(f"mode must be one of: {allowed}")
        self.mode = mode

    def is_open(self, now: datetime | None = None) -> bool:
        local = self._localize(now)
        if self.mode == ALWAYS_OPEN:
            return True
        return (
            local.weekday() < 5
            and MARKET_OPEN <= local.time() < MARKET_CLOSE
        )

    def session_date(self, now: datetime | None = None) -> date | None:
        """Return the local trading-day date, or None for scheduled weekends."""
        local = self._localize(now)
        if self.mode == ALWAYS_OPEN or local.weekday() < 5:
            return local.date()
        return None

    def next_open(self, now: datetime | None = None) -> datetime:
        """Return when trading can next proceed, expressed in Asia/Seoul."""
        local = self._localize(now)
        if self.mode == ALWAYS_OPEN or self.is_open(local):
            return local

        if local.weekday() < 5 and local.time() < MARKET_OPEN:
            return datetime.combine(local.date(), MARKET_OPEN, tzinfo=SEOUL)

        candidate = local.date() + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return datetime.combine(candidate, MARKET_OPEN, tzinfo=SEOUL)

    @staticmethod
    def _localize(now: datetime | None) -> datetime:
        current = _utc_now() if now is None else now
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("market session datetime must be timezone-aware")
        return current.astimezone(SEOUL)
