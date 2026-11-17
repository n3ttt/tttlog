"""Core data model: one QSO."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# Band edges in kHz (amateur HF, 6m, 2m, 70cm). Used to derive band from frequency.
BANDS_KHZ = [
    ("160m", 1800, 2000),
    ("80m", 3500, 4000),
    ("60m", 5330, 5410),
    ("40m", 7000, 7300),
    ("30m", 10100, 10150),
    ("20m", 14000, 14350),
    ("17m", 18068, 18168),
    ("15m", 21000, 21450),
    ("12m", 24890, 24990),
    ("10m", 28000, 29700),
    ("6m", 50000, 54000),
    ("2m", 144000, 148000),
    ("70cm", 420000, 450000),
]

# Cabrillo mode codes
CABRILLO_MODE = {"SSB": "PH", "USB": "PH", "LSB": "PH", "AM": "PH", "FM": "FM",
                 "CW": "CW", "RTTY": "RY", "FT8": "DG", "FT4": "DG", "PSK31": "DG"}


def band_from_khz(khz: float) -> str | None:
    for name, lo, hi in BANDS_KHZ:
        if lo <= khz <= hi:
            return name
    return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass
class QSO:
    call: str
    freq_khz: float
    mode: str                      # SSB, CW, RTTY ...
    rst_sent: str = "59"
    rst_rcvd: str = "59"
    exch_sent: str = ""            # contest exchange we sent (e.g. "DE")
    exch_rcvd: str = ""            # contest exchange we received (e.g. "100")
    time_utc: datetime = field(default_factory=utc_now)
    station_call: str = ""         # our call used on air
    operator: str = ""
    contest_id: str = ""
    id: int | None = None          # DB row id (local to this computer)
    uid: str = ""                  # same on every networked station; set when first logged
    station_name: str = ""         # which computer logged it (local network), e.g. "RUN1"
    # filled in by the contest engine
    country: str = ""
    cq_zone: int | None = None
    points: int = 0
    is_dupe: bool = False

    @property
    def band(self) -> str | None:
        return band_from_khz(self.freq_khz)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["time_utc"] = self.time_utc.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "QSO":
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        d["time_utc"] = datetime.fromisoformat(d["time_utc"])
        return cls(**d)


def new_uid() -> str:
    return uuid.uuid4().hex
