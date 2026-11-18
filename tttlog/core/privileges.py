"""US amateur license privileges (FCC Part 97.301 / 97.305), HF through 70 cm.

check(license, khz, mode) says whether that license class may transmit
there in that mode, and why not. Kinds of emission:

  cw     CW (allowed anywhere in a band the licensee has any privileges on)
  data   RTTY, FT8, FT4, PSK... (the CW/data segments; all-mode segments)
  phone  SSB, AM, FM, voice

The whole signal has to fit: LSB occupies about 3 kHz below the dial
frequency, USB / data about 3 kHz above it.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import band_from_khz

CLASSES = ["Extra", "Advanced", "General", "Technician", "Novice"]

E, A, G, T, N = "Extra", "Advanced", "General", "Technician", "Novice"
EAG = {E, A, G}
ALL = {E, A, G, T, N}
TECH_UP = {E, A, G, T}                  # Technician and up (VHF/UHF)

PHONE_BW = 3.0          # kHz an SSB / data signal occupies beside the dial frequency
CW_BW = 0.1


@dataclass(frozen=True)
class Segment:
    lo: float
    hi: float
    classes: frozenset
    kinds: frozenset            # subset of {"cw", "data", "phone"}


def _seg(lo, hi, classes, kinds):
    return Segment(lo, hi, frozenset(classes), frozenset(kinds))


CD = {"cw", "data"}
ALLK = {"cw", "data", "phone"}

SEGMENTS: list[Segment] = [
    # 160m
    _seg(1800, 2000, EAG, ALLK),
    # 80m / 75m
    _seg(3500, 3600, {E}, CD), _seg(3525, 3600, {A, G, T, N}, CD),
    _seg(3600, 4000, {E}, ALLK - {"data"}), _seg(3700, 4000, {A}, ALLK - {"data"}),
    _seg(3800, 4000, {G}, ALLK - {"data"}),
    # 60m: five USB channels (dial frequencies; 2.8 kHz wide plus rounding), General and up
    *[_seg(f, f + PHONE_BW, EAG, ALLK) for f in (5330.5, 5346.5, 5357.0, 5371.5, 5403.5)],
    # 40m
    _seg(7000, 7125, {E}, CD), _seg(7025, 7125, {A, G, T, N}, CD),
    _seg(7125, 7300, {E, A}, ALLK - {"data"}), _seg(7175, 7300, {G}, ALLK - {"data"}),
    # 30m: CW and data only
    _seg(10100, 10150, EAG, CD),
    # 20m
    _seg(14000, 14150, {E}, CD), _seg(14025, 14150, {A, G}, CD),
    _seg(14150, 14350, {E}, ALLK - {"data"}), _seg(14175, 14350, {A}, ALLK - {"data"}),
    _seg(14225, 14350, {G}, ALLK - {"data"}),
    # 17m
    _seg(18068, 18110, EAG, CD), _seg(18110, 18168, EAG, ALLK - {"data"}),
    # 15m
    _seg(21000, 21200, {E}, CD), _seg(21025, 21200, {A, G, T, N}, CD),
    _seg(21200, 21450, {E}, ALLK - {"data"}), _seg(21225, 21450, {A}, ALLK - {"data"}),
    _seg(21275, 21450, {G}, ALLK - {"data"}),
    # 12m
    _seg(24890, 24930, EAG, CD), _seg(24930, 24990, EAG, ALLK - {"data"}),
    # 10m
    _seg(28000, 28300, ALL, CD), _seg(28300, 29700, EAG, ALLK - {"data"}),
    _seg(28300, 28500, {T, N}, {"cw", "phone"}),
    # 6m, 2m: CW only at the bottom, then everything
    _seg(50000, 50100, TECH_UP, {"cw"}), _seg(50100, 54000, TECH_UP, ALLK),
    _seg(144000, 144100, TECH_UP, {"cw"}), _seg(144100, 148000, TECH_UP, ALLK),
    # 70cm
    _seg(420000, 450000, TECH_UP, ALLK),
]


def normalize(license: str) -> str:
    """'g', 'General', 'general class' -> 'General'; '' / unknown -> ''."""
    words = (license or "").strip().lower().split()
    if not words:
        return ""
    return next((c for c in CLASSES if c.lower().startswith(words[0])), "")


def kind_of(mode: str) -> str:
    m = (mode or "").upper()
    if m == "CW":
        return "cw"
    if m in ("SSB", "USB", "LSB", "AM", "FM", "PH"):
        return "phone"
    return "data"


def _occupied(khz: float, mode: str) -> tuple[float, float]:
    """The part of the band the signal takes up."""
    m = (mode or "").upper()
    if m == "CW":
        return khz - CW_BW, khz + CW_BW
    if m in ("AM", "FM"):
        return khz - PHONE_BW, khz + PHONE_BW
    if m in ("SSB", "PH", "LSB", "USB"):
        lsb = m == "LSB" or (m != "USB" and khz < 10000 and not 5300 <= khz <= 5410)
        return (khz - PHONE_BW, khz) if lsb else (khz, khz + PHONE_BW)
    return khz, khz + PHONE_BW                               # data: USB, audio above the dial


def segments(license: str, band: str | None = None, mode: str | None = None) -> list[Segment]:
    lic = normalize(license)
    out = [s for s in SEGMENTS if lic in s.classes]
    if band:
        out = [s for s in out if band_from_khz((s.lo + s.hi) / 2) == band]
    if mode:
        k = kind_of(mode)
        out = [s for s in out if k in s.kinds]
    return out


def _merged(segs: list[Segment]) -> list[tuple[float, float]]:
    spans = sorted((s.lo, s.hi) for s in segs)
    out: list[list[float]] = []
    for lo, hi in spans:
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [(a, b) for a, b in out]


def check(license: str, khz: float, mode: str) -> str:
    """'' if the license allows transmitting `mode` on `khz`, else a short reason.
    No license class set -> no limits (non-US stations, or not wanted)."""
    lic = normalize(license)
    if not lic:
        return ""
    band = band_from_khz(khz)
    if band is None:
        return f"{khz:,.1f} kHz is outside the amateur bands"
    lo, hi = _occupied(khz, mode)
    kind = kind_of(mode)
    spans = _merged(segments(lic, band, mode))
    if any(a <= lo and hi <= b for a, b in spans):
        return ""
    if not segments(lic, band):
        return f"{lic} class has no privileges on {band}"
    label = {"cw": "CW", "data": "data", "phone": "phone"}[kind]
    if not spans:
        return f"{lic} class has no {label} privileges on {band}"
    where = ", ".join(f"{a:g}–{b:g}" for a, b in spans)
    if any(a <= khz <= b for a, b in spans):
        return f"Too close to the edge of {lic} {band} {label} privileges ({where} kHz)"
    return f"Outside {lic} privileges: {band} {label} is {where} kHz"


def inside(license: str, band: str, mode: str, khz: float) -> float | None:
    """`khz` if allowed, else the nearest usable frequency on that band for that mode
    (None if the class can't use that mode on the band at all)."""
    if not check(license, khz, mode):
        return khz
    spans = _merged(segments(license, band, mode))
    if not spans:
        return None
    a0, b0 = _occupied(khz, mode)
    lo, hi = a0 - khz, b0 - khz              # where the signal sits relative to the dial
    best = None
    for a, b in spans:
        cand = min(max(khz, a - lo + 0.5), b - hi - 0.5)      # keep half a kHz inside
        if a <= cand + lo and cand + hi <= b and (best is None or abs(cand - khz) < abs(best - khz)):
            best = cand
    if best is None:
        return None
    return float(round(best))
