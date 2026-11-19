"""Radio (CAT) protocol: the part that doesn't need sockets or serial ports.

Three dialects of the same ";"-terminated ASCII command set:

* flex    FlexRadio through SmartSDR (Mac: SmartSDR for Mac's CAT TCP port;
          Windows: SmartSDR CAT's TCP/serial ports). FA = 11-digit Hz,
          mode via ZZMD (Flex's own mode numbers).
* kenwood Kenwood TS-590/890/2000, Elecraft K3/K4 and others that speak the
          Kenwood set. FA = 11-digit Hz, MD = Kenwood mode digit.
* yaesu   Yaesu FTDX10 / FTDX101 / FT-710 / FT-991A. FA = 9-digit Hz,
          MD0 = mode character.

Icom radios speak CI-V instead (binary frames): see civ.py, picked with
make_dialect(cfg) when cfg["dialect"] == "icom".

Reads: frequency and mode (polled). Writes (only when tttlog is allowed to
control the radio): frequency and mode.
"""
from __future__ import annotations

from dataclasses import dataclass

DIALECTS = {
    "flex": "FlexRadio (SmartSDR CAT)",
    "kenwood": "Kenwood / Elecraft",
    "yaesu": "Yaesu (FTDX10, FTDX101, FT-710, FT-991A)",
    "icom": "Icom (CI-V: IC-7300, IC-7610, IC-9700, IC-705, ...)",
}

# radio mode code -> radio mode name
FLEX_MODES = {"00": "LSB", "01": "USB", "03": "CWL", "04": "CWU", "05": "FM", "06": "AM",
              "07": "DIGU", "09": "DIGL", "10": "SAM", "11": "NFM", "12": "DFM", "30": "RTTY"}
KENWOOD_MODES = {"1": "LSB", "2": "USB", "3": "CWU", "4": "FM", "5": "AM", "6": "RTTY",
                 "7": "CWL", "9": "RTTY"}
YAESU_MODES = {"1": "LSB", "2": "USB", "3": "CWU", "4": "FM", "5": "AM", "6": "RTTY",
               "7": "CWL", "8": "DIGL", "9": "RTTY", "A": "DIGFM", "B": "NFM", "C": "DIGU",
               "D": "AM", "E": "FM"}


def to_logger_mode(radio_mode: str, current: str, allowed: list[str]) -> str | None:
    """Radio mode -> tttlog mode. Digital: keep the current digital mode (FT8 vs
    FT4 can't be told apart from the radio), else the log's first digital mode."""
    m = radio_mode.upper()
    if m in ("LSB", "USB"):
        return "SSB"
    if m in ("CWU", "CWL"):
        return "CW"
    if m in ("AM", "SAM"):
        return "AM"
    if m in ("FM", "NFM", "DFM"):
        return "FM"
    if m == "RTTY":
        return "RTTY"
    if m.startswith("DIG"):
        digital = [x for x in allowed if x not in ("SSB", "CW", "AM", "FM", "RTTY")]
        if current in digital or (not allowed and current not in ("SSB", "CW", "AM", "FM")):
            return current
        return digital[0] if digital else "FT8"
    return None


def from_logger_mode(mode: str, freq_khz: float) -> str:
    """tttlog mode -> radio mode name (SSB: LSB below 10 MHz except 60m)."""
    m = mode.upper()
    if m == "SSB":
        return "LSB" if freq_khz < 10000 and not 5300 <= freq_khz <= 5410 else "USB"
    if m == "CW":
        return "CWU"
    if m in ("AM", "FM", "RTTY"):
        return m
    return "DIGU"                                     # FT8, FT4, PSK...


@dataclass
class Dialect:
    name: str

    # -- queries -----------------------------------------------------------
    def poll(self) -> list[bytes]:
        if self.name == "flex":
            return [b"FA;", b"ZZMD;"]
        if self.name == "yaesu":
            return [b"FA;", b"MD0;"]
        return [b"FA;", b"MD;"]

    # -- commands ----------------------------------------------------------
    def set_freq(self, khz: float) -> bytes:
        hz = int(round(khz * 1000))
        if self.name == "yaesu":
            return f"FA{hz:09d};".encode()
        return f"FA{hz:011d};".encode()

    def set_mode(self, radio_mode: str) -> bytes | None:
        table = {"flex": FLEX_MODES, "kenwood": KENWOOD_MODES, "yaesu": YAESU_MODES}[self.name]
        code = next((c for c, n in table.items() if n == radio_mode), None)
        if code is None:
            return None
        if self.name == "flex":
            return f"ZZMD{code};".encode()
        if self.name == "yaesu":
            return f"MD0{code};".encode()
        return f"MD{code};".encode()

    # -- answers -----------------------------------------------------------
    def parse(self, reply: str) -> tuple[str, object] | None:
        """One reply (without the ';') -> ("freq", kHz) or ("mode", radio mode name)."""
        r = reply.strip()
        try:
            if r.startswith("FA") and r[2:].isdigit():
                return "freq", int(r[2:]) / 1000.0
            if self.name == "flex" and r.startswith("ZZMD"):
                return ("mode", FLEX_MODES[r[4:6]]) if r[4:6] in FLEX_MODES else None
            if self.name == "yaesu" and r.startswith("MD0"):
                return ("mode", YAESU_MODES[r[3:4]]) if r[3:4] in YAESU_MODES else None
            if self.name == "kenwood" and r.startswith("MD"):
                return ("mode", KENWOOD_MODES[r[2:3]]) if r[2:3] in KENWOOD_MODES else None
        except (ValueError, IndexError):
            return None
        return None


def split_replies(buf: bytes) -> tuple[list[str], bytes]:
    """Complete ';'-terminated replies, and what's left over."""
    *done, rest = buf.split(b";")
    return [d.decode("ascii", "replace").strip() for d in done if d.strip()], rest


def make_dialect(cfg: dict):
    """The protocol object for the configured radio."""
    name = cfg.get("dialect", "flex")
    if name == "icom":
        from .civ import MODELS, IcomDialect
        model = cfg.get("civ_model", "ic7300")
        addr = cfg.get("civ_addr")
        if not isinstance(addr, int) or not 0 < addr < 0xE0:
            addr = MODELS.get(model, MODELS["other"])[1]
        return IcomDialect(addr=addr, model=model)
    return Dialect(name)
