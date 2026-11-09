"""Injectable clock so quote expiry and traces are deterministic in tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class Clock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 9, 14, 2, 11, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> datetime:
        self._now = self._now + timedelta(seconds=seconds)
        return self._now

    def iso(self) -> str:
        return self._now.strftime("%Y-%m-%dT%H:%M:%S+0000")

    def hms(self) -> str:
        return self._now.strftime("%H:%M:%S")


class WallClock(Clock):
    """Real time. Live mode uses this so quote age, token expiry, and webhook
    timestamps are compared against the host's clock, not the fixed demo time."""

    def __init__(self) -> None:
        super().__init__(datetime.now(UTC))

    def now(self) -> datetime:
        return datetime.now(UTC)

    def advance(self, seconds: int) -> datetime:
        return self.now()

    def iso(self) -> str:
        return self.now().strftime("%Y-%m-%dT%H:%M:%S+0000")

    def hms(self) -> str:
        return self.now().strftime("%H:%M:%S")
