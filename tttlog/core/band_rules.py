"""Multi-op band-change rules: how soon, and how often, a transmitter may change band.

Each contest's rules file can say, per entry category:

    multi_op:
      MS: {min_minutes: 10, mult_station: true}   # CQ WW Multi-Single: 10-minute rule
      M2: {changes_per_hour: 8}                    # CQ WW Multi-Two: 8 changes a clock hour

  min_minutes       once a transmitter makes its first QSO on a band it stays there
                    this long (CQ WW: "periods begin with the first QSO on a band")
  changes_per_hour  band changes allowed per transmitter in a clock hour (00-59);
                    20 m -> 40 m -> 20 m is two
  mult_station      Multi-Single may run a second, multiplier-only signal on another
                    band with its own 10-minute clock (CQ WW)

Band changes are counted from the logged QSOs of this transmitter (the computer
that logged them), as the log checkers do.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

CATEGORIES = {
    "": "Single operator / no band-change limit",
    "MS": "Multi-operator, single transmitter (Multi-Single)",
    "M2": "Multi-operator, two transmitter (Multi-Two)",
    "MM": "Multi-operator, multi-transmitter (no band-change limit)",
}

# What this computer is, within the category
ROLES = {
    "MS": {"run": "Run station", "mult": "Multiplier station"},
    "M2": {"tx1": "Transmitter 1", "tx2": "Transmitter 2"},
}

# Cabrillo CATEGORY-OPERATOR / CATEGORY-TRANSMITTER for each category
CABRILLO = {
    "MS": {"OPERATOR": "MULTI-OP", "TRANSMITTER": "ONE"},
    "M2": {"OPERATOR": "MULTI-OP", "TRANSMITTER": "TWO"},
    "MM": {"OPERATOR": "MULTI-OP", "TRANSMITTER": "UNLIMITED"},
}


def limits(rules: dict, category: str) -> dict:
    """This contest's limits for the category ({} = none)."""
    return dict((rules or {}).get("multi_op", {}).get(category or "", {}) or {})


def describe(lim: dict) -> str:
    """'10-minute rule' / '8 band changes per clock hour' / ''."""
    parts = []
    if lim.get("min_minutes"):
        parts.append(f"{lim['min_minutes']}-minute rule")
    if lim.get("changes_per_hour"):
        parts.append(f"{lim['changes_per_hour']} band changes per clock hour")
    return ", ".join(parts)


@dataclass
class BandCheck:
    ok: bool                         # this band change is allowed now
    current: str | None              # the band this transmitter is on (its last QSO)
    status: str                      # where things stand, e.g. "on 20m since 1412Z"
    why: str = ""                    # why not, when not ok
    free_at: datetime | None = None  # when it will be allowed (not ok only)


def _bands(qsos) -> list[tuple[datetime, str]]:
    return [(q.time_utc, q.band) for q in sorted(qsos, key=lambda q: q.time_utc) if q.band]


def _band_since(seq) -> datetime | None:
    """When the transmitter's current stretch on its band began (its first QSO there)."""
    if not seq:
        return None
    band, start = seq[-1][1], seq[-1][0]
    for t, b in reversed(seq):
        if b != band:
            break
        start = t
    return start


def changes_this_hour(seq, now: datetime) -> int:
    hour = now.replace(minute=0, second=0, microsecond=0)
    before = [b for t, b in seq if t < hour]
    prev = before[-1] if before else None
    n = 0
    for t, b in seq:
        if hour <= t <= now:
            if prev is not None and b != prev:
                n += 1
            prev = b
    return n


def check(lim: dict, my_qsos, target_band: str | None, now: datetime) -> BandCheck:
    """May this transmitter (its logged QSOs: my_qsos) make its next QSO on target_band?"""
    seq = _bands(my_qsos)
    current = seq[-1][1] if seq else None
    parts, why, free_at = [], [], []
    change = current is not None and target_band is not None and target_band != current
    if lim.get("min_minutes") and current:
        since = _band_since(seq)
        until = since + timedelta(minutes=int(lim["min_minutes"]))
        parts.append(f"on {current} since {since:%H%M}Z")
        if now < until:
            parts[-1] += f", free to change at {until:%H%M}Z"
            if change:
                why.append(f"{lim['min_minutes']}-minute rule: on {current} since {since:%H%M}Z, "
                           f"can't change band until {until:%H%M}Z")
                free_at.append(until)
    if lim.get("changes_per_hour"):
        cap = int(lim["changes_per_hour"])
        n = changes_this_hour(seq, now)
        parts.append(f"{n} of {cap} band changes this hour")
        if change and n >= cap:
            nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            why.append(f"all {cap} band changes used this clock hour; more at {nxt:%H%M}Z")
            free_at.append(nxt)
    return BandCheck(ok=not why, current=current, status="; ".join(parts), why="; ".join(why),
                     free_at=max(free_at) if free_at else None)
