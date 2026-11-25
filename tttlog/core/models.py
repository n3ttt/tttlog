"""Core data model: one QSO."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# Band edges in kHz (amateur HF, 6m, 2m, 70cm). Used to derive band from frequency.
BANDS_KHZ = [
    ("2200m", 135.7, 137.8),
    ("630m", 472, 479),
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
    ("1.25m", 222000, 225000),
    ("70cm", 420000, 450000),
    ("33cm", 902000, 928000),
    ("23cm", 1240000, 1300000),
    ("13cm", 2300000, 2450000),
]

# Cabrillo mode codes
CABRILLO_MODE = {"SSB": "PH", "USB": "PH", "LSB": "PH", "AM": "PH", "FM": "FM",
                 "CW": "CW", "RTTY": "RY", "FT8": "DG", "FT4": "DG", "PSK31": "DG"}


# Where a band button puts you the first time (after that, back where you last
# were on that band in that kind of mode). Usual calling / activity spots.
BAND_START_KHZ = {
    "CW":   {"160m": 1820, "80m": 3525, "60m": 5332, "40m": 7025, "30m": 10110, "20m": 14025,
             "17m": 18080, "15m": 21025, "12m": 24900, "10m": 28025, "6m": 50090, "2m": 144050,
             "70cm": 432100},
    "SSB":  {"160m": 1850, "80m": 3800, "60m": 5330.5, "40m": 7200, "20m": 14250, "17m": 18130,
             "15m": 21300, "12m": 24950, "10m": 28400, "6m": 50125, "2m": 144200, "70cm": 432100},
    "AM":   {"160m": 1885, "80m": 3885, "40m": 7290, "20m": 14286, "10m": 29000, "6m": 50400},
    "FM":   {"10m": 29600, "6m": 52525, "2m": 146520, "70cm": 446000},
    "RTTY": {"80m": 3580, "40m": 7080, "20m": 14080, "15m": 21080, "10m": 28080},
    "DIGI": {"160m": 1840, "80m": 3573, "60m": 5357, "40m": 7074, "30m": 10136, "20m": 14074,
             "17m": 18100, "15m": 21074, "12m": 24915, "10m": 28074, "6m": 50313, "2m": 144174,
             "70cm": 432174},
}


def mode_group(mode: str) -> str:
    """Which BAND_START_KHZ table a mode uses (FT8, FT4, PSK... are all DIGI)."""
    m = (mode or "").upper()
    if m in ("USB", "LSB", "SSB", "PH"):
        return "SSB"
    return m if m in BAND_START_KHZ else "DIGI"


def band_start_khz(band: str, mode: str) -> float | None:
    """A sensible frequency on `band` for `mode` (falls back to the CW end, then the band edge)."""
    table = BAND_START_KHZ[mode_group(mode)]
    if band in table:
        return float(table[band])
    if band in BAND_START_KHZ["CW"]:                  # e.g. SSB on 30m, FM on 40m
        return float(BAND_START_KHZ["CW"][band])
    edge = next((lo for name, lo, _hi in BANDS_KHZ if name == band), None)
    return float(edge) if edge is not None else None


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
    dxcc: int | None = None        # ADIF DXCC entity number when a file (LoTW) gave one: beats cty.dat
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
