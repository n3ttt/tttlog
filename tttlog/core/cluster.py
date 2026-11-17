"""DX cluster: spot parsing, telnet cleanup, and the spot list.

Network I/O lives in the UI (Qt sockets, so nothing blocks the entry line);
everything here is plain Python and is unit-tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import QSO, band_from_khz

# "DX de W3LPL:     14025.0  DL1ABC       CQ up 1                    1234Z"
# DXSpider, AR-Cluster and CC Cluster all use this layout; the spotter may
# carry "-#" (skimmer) or "-1" style suffixes, and the time may be missing.
SPOT_RE = re.compile(
    r"^DX de\s+(?P<spotter>[A-Z0-9/#\-]+?)-?#?:?\s+"
    r"(?P<freq>\d+(?:\.\d+)?)\s+"
    r"(?P<call>[A-Z0-9/]+)\s*"
    r"(?P<comment>.*?)\s*"
    r"(?:(?P<time>\d{4})Z)?(?:\s+\S+)?\s*$",
    re.IGNORECASE)

# Login prompts seen on common cluster software.
LOGIN_RE = re.compile(r"(login|call(sign)?|enter your call.*)\s*:?\s*>?\s*$", re.IGNORECASE)

IAC = 255

# Approximate start of the phone segment per band (kHz). Below = CW/digital.
# Contest phone activity sits a little lower than the US band plan on 160/80.
PHONE_START = {"160m": 1840, "80m": 3600, "60m": 0, "40m": 7125, "20m": 14150,
               "17m": 18110, "15m": 21200, "12m": 24930, "10m": 28300, "6m": 50100,
               "2m": 144100, "70cm": 432100}

DIGI_WORDS = ("FT8", "FT4", "RTTY", "PSK", "JT65", "JS8")
DIGI_MODES = {"FT8", "FT4", "RTTY", "PSK31", "JS8", "DIGI"}


def split_telnet(data: bytes) -> tuple[bytes, bytes]:
    """Remove telnet IAC sequences; return (clean bytes, incomplete tail).

    TCP can split a negotiation sequence across reads, so an unfinished one at
    the end is handed back to be prefixed to the next read instead of leaking
    control bytes into the text.
    """
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b != IAC:
            out.append(b); i += 1; continue
        if i + 1 >= n:                       # lone IAC: wait for the command byte
            return bytes(out), data[i:]
        cmd = data[i + 1]
        if cmd == IAC:                       # escaped 255
            out.append(IAC); i += 2
        elif cmd in (251, 252, 253, 254):    # WILL/WONT/DO/DONT <opt>
            if i + 2 >= n:                   # option byte not here yet
                return bytes(out), data[i:]
            i += 3
        elif cmd == 250:                     # SB ... IAC SE
            end = data.find(bytes([IAC, 240]), i + 2)
            if end < 0:                      # subnegotiation not finished yet
                return bytes(out), data[i:]
            i = end + 2
        else:
            i += 2
    return bytes(out), b""


def strip_telnet(data: bytes) -> bytes:
    """Remove telnet IAC sequences from a complete chunk of bytes."""
    return split_telnet(data)[0]


def spot_command(call: str, khz: float, comment: str = "") -> str:
    """The cluster command that spots a station. DXSpider, AR-Cluster and
    CC Cluster all accept  DX <kHz> <call> [comment]."""
    call = call.strip().upper()
    if not call or not re.fullmatch(r"[A-Z0-9/]+", call):
        raise ValueError(f"not a callsign: {call!r}")
    if band_from_khz(khz) is None:
        raise ValueError(f"{khz} kHz is outside the ham bands")
    return f"DX {khz:.1f} {call}" + (f" {comment.strip()}" if comment.strip() else "")


def guess_mode(khz: float, comment: str = "") -> str:
    """Best guess at a spot's mode: comment keywords first, then band plan."""
    c = comment.upper()
    for w in DIGI_WORDS:
        if w in c:
            return "DIGI"
    if re.search(r"\bCW\b", c):
        return "CW"
    if re.search(r"\b(SSB|USB|LSB|PH)\b", c):
        return "SSB"
    band = band_from_khz(khz)
    if band is None:
        return "?"
    return "SSB" if khz >= PHONE_START.get(band, 0) else "CW"


@dataclass
class Spot:
    call: str
    freq_khz: float
    spotter: str
    comment: str = ""
    time_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mode: str = ""
    # filled by SpotList.evaluate()
    status: str = ""          # MULT | Q | DUPE | INVALID
    mults: list[str] = field(default_factory=list)
    keys: list = field(default_factory=list)   # (label, key) mult values this spot carries
    country: str = ""

    @property
    def band(self) -> str | None:
        return band_from_khz(self.freq_khz)


def parse_spot(line: str, now: datetime | None = None) -> Spot | None:
    """Parse one cluster line into a Spot, or None if it isn't a DX spot."""
    line = line.strip()
    if not line[:5].upper() == "DX DE":
        return None
    m = SPOT_RE.match(line)
    if not m:
        return None
    try:
        khz = float(m["freq"])
    except ValueError:
        return None
    if khz > 1_000_000:          # some nodes send Hz
        khz /= 1000
    now = now or datetime.now(timezone.utc)
    t = now.replace(second=0, microsecond=0)
    if m["time"]:
        hh, mm = int(m["time"][:2]), int(m["time"][2:])
        if hh < 24 and mm < 60:
            t = t.replace(hour=hh, minute=mm)
            if t > now + timedelta(minutes=5):       # spot from just before 0000Z
                t -= timedelta(days=1)
    comment = (m["comment"] or "").strip()
    return Spot(call=m["call"].upper(), freq_khz=khz, spotter=m["spotter"].upper().rstrip("-#:"),
                comment=comment, time_utc=t, mode=guess_mode(khz, comment))


class SpotList:
    """Latest spot per (call, band), aged out after max_age minutes."""

    def __init__(self, max_age_min: int = 30):
        self.max_age = timedelta(minutes=max_age_min)
        self._spots: dict[tuple, Spot] = {}

    def add(self, s: Spot) -> None:
        if s.band is None:
            return
        self._spots[(s.call, s.band)] = s

    def prune(self, now: datetime) -> None:
        cutoff = now - self.max_age
        self._spots = {k: s for k, s in self._spots.items() if s.time_utc >= cutoff}

    def clear(self) -> None:
        self._spots.clear()

    def __len__(self) -> int:
        return len(self._spots)

    def spots(self) -> list[Spot]:
        """Newest first."""
        return sorted(self._spots.values(), key=lambda s: s.time_utc, reverse=True)

    def evaluate(self, engine, log: list[QSO], only: list[Spot] | None = None) -> None:
        """Mark spots as MULT / Q / DUPE / INVALID against the current log.

        `only` limits the work to newly arrived spots; otherwise all are redone
        (call that after every QSO, edit or delete).
        """
        modes = engine.rules.get("modes", [])
        have = set()
        for p in log:
            if not p.is_dupe and engine.is_valid(p):
                have.update(engine.mult_values(p))
        for s in (only if only is not None else self._spots.values()):
            mode = s.mode if s.mode in ("SSB", "CW") else (modes[0] if modes else "SSB")
            if s.mode == "DIGI" and DIGI_MODES & set(modes):
                mode = next(m for m in modes if m in DIGI_MODES)
            probe = engine.annotate(QSO(call=s.call, freq_khz=s.freq_khz, mode=mode), log)
            s.country = probe.country
            s.mults = []
            s.keys = engine.mult_values(probe)
            wrong_mode = s.mode not in ("?", "") and modes and mode not in modes
            if wrong_mode or not engine.is_valid(probe):
                s.status = "INVALID"
                s.keys = []                       # can't be worked, so it doesn't count as spotted
            elif probe.is_dupe:
                s.status = "DUPE"
            else:
                s.mults = [lbl for lbl, key in s.keys if (lbl, key) not in have]
                s.status = "MULT" if s.mults else "Q"
