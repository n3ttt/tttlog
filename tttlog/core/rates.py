"""QSO rate figures for the Rate pane.

All functions are pure: give them the log (any order) and "now" and they
return numbers, so they are easy to test and cheap to recompute every tick.
Dupes are ignored everywhere; a dupe isn't a QSO for rate purposes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable

from .models import QSO

MIN_SPAN = timedelta(minutes=1)   # floor so 2 quick QSOs don't read "7200/hr"


def _good(qsos: Iterable[QSO]) -> list[QSO]:
    return sorted((q for q in qsos if not q.is_dupe), key=lambda q: (q.time_utc, q.id or 0))


def rate_last_n(qsos: Iterable[QSO], n: int, now: datetime) -> float:
    """QSOs/hour over the last n QSOs, measured from the nth-last QSO to now.

    Returns 0 until there are n QSOs, so "Last 100" doesn't show a fake figure
    in the first hour.
    """
    good = _good(qsos)
    if len(good) < n or n <= 0:
        return 0.0
    span = max(now - good[-n].time_utc, MIN_SPAN)
    return n * 3600 / span.total_seconds()


def count_since(qsos: Iterable[QSO], minutes: int, now: datetime) -> int:
    start = now - timedelta(minutes=minutes)
    return sum(1 for q in _good(qsos) if start < q.time_utc <= now)


@dataclass
class HourRow:
    hour: datetime                                   # start of the clock hour (UTC)
    by_band: dict[str, int] = field(default_factory=dict)
    qsos: int = 0
    mults: int = 0


def hourly(qsos: Iterable[QSO],
           mult_keys: Callable[[QSO], list] | None = None,
           is_valid: Callable[[QSO], bool] | None = None,
           only: Callable[[QSO], bool] | None = None) -> list[HourRow]:
    """One row per clock hour that has QSOs, oldest first.

    `mult_keys(q)` returns the mult keys a QSO counts toward; the first time a
    key appears it is counted as a new mult in that hour. `is_valid(q)` lets
    the caller drop QSOs that don't count in the contest. `only(q)` limits the
    rows to some QSOs (one operator) while mults stay new-to-the-whole-log.
    """
    rows: dict[datetime, HourRow] = {}
    seen: set = set()
    for q in _good(qsos):
        if is_valid and not is_valid(q):
            continue
        new = 0
        if mult_keys:
            for k in mult_keys(q):
                if k not in seen:
                    seen.add(k)
                    new += 1
        if only and not only(q):
            continue
        h = q.time_utc.replace(minute=0, second=0, microsecond=0)
        row = rows.setdefault(h, HourRow(hour=h))
        row.qsos += 1
        band = q.band or "?"
        row.by_band[band] = row.by_band.get(band, 0) + 1
        row.mults += new
    return [rows[h] for h in sorted(rows)]


@dataclass
class RateSummary:
    last10: float
    last100: float
    last60_count: int
    last15_count: int
    best60: int

    @property
    def last15_rate(self) -> int:
        return self.last15_count * 4


def best_60(qsos: Iterable[QSO]) -> int:
    """Most QSOs in any rolling 60-minute window."""
    times = [q.time_utc for q in _good(qsos)]
    best, lo = 0, 0
    for hi, t in enumerate(times):
        while t - times[lo] >= timedelta(minutes=60):
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def summary(qsos: Iterable[QSO], now: datetime, best: bool = True) -> RateSummary:
    """best=False skips best 60 (the only figure that needs the whole log)."""
    good = _good(qsos)                       # sort once; the figures below take the sorted list
    recent = [q for q in good[-2000:] if q.time_utc > now - timedelta(minutes=60)]
    return RateSummary(last10=rate_last_n(good[-10:], 10, now),
                       last100=rate_last_n(good[-100:], 100, now),
                       last60_count=sum(1 for q in recent if q.time_utc <= now),
                       last15_count=sum(1 for q in recent if now - timedelta(minutes=15) < q.time_utc <= now),
                       best60=best_60(good) if best else 0)


def op_of(q: QSO) -> str:
    return (q.operator or q.station_call or "?").upper()


def operators(qsos: Iterable[QSO]) -> list[str]:
    """Operators in the log, in the order they first logged."""
    seen: dict[str, None] = {}
    for q in _good(qsos):
        seen.setdefault(op_of(q), None)
    return list(seen)


@dataclass
class OpRow:
    op: str
    qsos: int
    summary: RateSummary
    share: float                                     # fraction of the log's QSOs


def by_operator(qsos: Iterable[QSO], now: datetime) -> list[OpRow]:
    """Rates for each operator, most QSOs first."""
    good = _good(qsos)
    groups: dict[str, list[QSO]] = {}
    for q in good:
        groups.setdefault(op_of(q), []).append(q)
    rows = [OpRow(op, len(g), summary(g, now), len(g) / len(good)) for op, g in groups.items()]
    return sorted(rows, key=lambda r: (-r.qsos, r.op))
