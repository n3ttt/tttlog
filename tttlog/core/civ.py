"""Icom CI-V: binary frames, BCD frequencies, modes, PTT and CW.

Command numbers, default radio addresses and the CW speed table are taken
from Hamlib (rigs/icom/icom_defs.h, icom.c and the per-model files).

Frame:  FE FE <to> <from> <cmd> [<sub>] [data...] FD
        controller (tttlog) = E0; to = 00 is a "transceive" broadcast the radio
        sends by itself when the dial or mode changes (CI-V Transceive ON).
Replies to commands that don't return data: FB = OK, FA = NG (not accepted).
On a single-wire CI-V bus (CT-17, or USB with "CI-V USB Echo Back" ON) we
also hear our own frames; those are ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PR, FI, ACK, NAK, COL = 0xFE, 0xFD, 0xFB, 0xFA, 0xFC
CTRLID = 0xE0                  # tttlog's address on the bus

C_SND_FREQ, C_SND_MODE = 0x00, 0x01        # transceive broadcasts (no ack)
C_RD_FREQ, C_RD_MODE = 0x03, 0x04
C_SET_FREQ, C_SET_MODE = 0x05, 0x06
C_CTL_LVL, S_LVL_KEYSPD = 0x14, 0x0C
C_SND_CW = 0x17
C_CTL_MEM = 0x1A                             # sub 0x06 = data mode (0x04 on the IC-7200)
C_CTL_PTT, S_PTT = 0x1C, 0x00

# CI-V mode byte <-> tttlog's radio mode names (see rig.py)
MODE_FROM_ICOM = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CWU", 0x04: "RTTY", 0x05: "FM",
                  0x06: "FM", 0x07: "CWL", 0x08: "RTTY", 0x11: "AM", 0x12: "DIGU", 0x13: "DIGL"}
MODE_TO_ICOM = {"LSB": 0x00, "USB": 0x01, "AM": 0x02, "CWU": 0x03, "RTTY": 0x04, "FM": 0x05,
                "CWL": 0x07, "DIGU": 0x01, "DIGL": 0x00}

# key -> (name, default CI-V address, data-mode sub-command or None, CW text over CI-V)
MODELS = {
    "ic7300":    ("IC-7300", 0x94, 0x06, True),
    "ic7300mk2": ("IC-7300MK2", 0xB6, 0x06, True),
    "ic7610":    ("IC-7610", 0x98, 0x06, True),
    "ic7760":    ("IC-7760", 0xB2, 0x06, True),
    "ic7851":    ("IC-7851 / IC-7850", 0x8E, 0x06, True),
    "ic9700":    ("IC-9700", 0xA2, 0x06, True),
    "ic705":     ("IC-705", 0xA4, 0x06, True),
    "ic905":     ("IC-905", 0xAC, 0x06, True),
    "ic7100":    ("IC-7100", 0x88, 0x06, True),
    "ic7600":    ("IC-7600", 0x7A, 0x06, True),
    "ic7700":    ("IC-7700", 0x74, 0x06, True),
    "ic7410":    ("IC-7410", 0x80, 0x06, True),
    "ic7200":    ("IC-7200", 0x76, 0x04, False),
    "ic756pro3": ("IC-756PROIII", 0x6E, 0x06, False),
    "ic756pro2": ("IC-756PROII", 0x64, None, False),
    "ic7000":    ("IC-7000", 0x70, None, False),
    "ic746pro":  ("IC-746PRO", 0x66, None, False),
    "ic718":     ("IC-718", 0x5E, None, False),
    "other":     ("Other Icom (set the address)", 0x94, 0x06, True),
}

# Icom key-speed level (0-255) for 6-48 WPM: Hamlib's cw_lookup table
CW_LEVELS = [(0, 6), (7, 7), (12, 8), (19, 9), (25, 10), (31, 11), (37, 12), (43, 13), (49, 14),
             (55, 15), (61, 16), (67, 17), (73, 18), (79, 19), (84, 20), (91, 21), (97, 22),
             (103, 23), (108, 24), (114, 25), (121, 26), (128, 27), (134, 28), (140, 29),
             (144, 30), (151, 31), (156, 32), (164, 33), (169, 34), (175, 35), (182, 36),
             (188, 37), (192, 38), (199, 39), (203, 40), (211, 41), (215, 42), (224, 43),
             (229, 44), (234, 45), (239, 46), (244, 47), (250, 48)]
CW_CHUNK = 30                                   # characters per "send CW" command
CW_CHARS = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/?.-,:'()=+\"@ ")


# ---------------------------------------------------------------- encoding
def to_bcd(value: int, nbytes: int) -> bytes:
    """Little-endian packed BCD: 14_025_000 Hz, 5 bytes -> 00 50 02 14 00."""
    out = bytearray()
    for _ in range(nbytes):
        lo, value = value % 10, value // 10
        hi, value = value % 10, value // 10
        out.append(hi << 4 | lo)
    return bytes(out)


def from_bcd(data: bytes) -> int | None:
    """Inverse of to_bcd; None if a nibble isn't a decimal digit."""
    total, mult = 0, 1
    for b in data:
        lo, hi = b & 0x0F, b >> 4
        if lo > 9 or hi > 9:
            return None
        total += lo * mult + hi * mult * 10
        mult *= 100
    return total


def to_bcd_be(value: int, nbytes: int) -> bytes:
    """Big-endian packed BCD, used by levels: 128 -> 01 28."""
    return bytes(reversed(to_bcd(value, nbytes)))


def frame(to: int, cmd: int, sub: int | None = None, data: bytes = b"", frm: int = CTRLID) -> bytes:
    return bytes([PR, PR, to, frm, cmd] + ([sub] if sub is not None else [])) + data + bytes([FI])


def split_frames(buf: bytes) -> tuple[list[bytes], bytes]:
    """Complete frames (FE FE ... FD, without the markers) and what's left over.
    Garbage before a preamble and collision frames are dropped."""
    frames = []
    while True:
        start = buf.find(bytes([PR, PR]))
        if start < 0:
            return frames, buf[-1:] if buf.endswith(bytes([PR])) else b""
        while start + 2 < len(buf) and buf[start + 2] == PR:   # FE FE FE...: extra preambles
            start += 1
        end = buf.find(bytes([FI]), start + 2)
        if end < 0:
            return frames, buf[start:]
        body = buf[start + 2:end]
        if body and COL not in body[:1]:
            frames.append(body)
        buf = buf[end + 1:]


def cw_speed_level(wpm: int) -> int:
    wpm = max(6, min(48, int(wpm)))
    return next(level for level, w in CW_LEVELS if w >= wpm)


def cw_clean(text: str) -> str:
    return "".join(c for c in text.upper() if c in CW_CHARS)


# ---------------------------------------------------------------- the dialect
@dataclass
class IcomDialect:
    """Same job as rig.Dialect (poll / set_freq / set_mode / parse) for CI-V radios,
    plus PTT and CW. Keeps the last mode/filter/data state the radio reported."""
    addr: int = 0x94
    model: str = "ic7300"
    name: str = "icom"
    base_mode: int | None = None
    filt: int = 1
    data: bool = False
    data_ok: bool = True           # radio answers the data-mode query
    _asked_data: bool = field(default=False, repr=False)
    _naks: int = field(default=0, repr=False)

    @property
    def data_sub(self) -> int | None:
        return MODELS.get(self.model, MODELS["other"])[2] if self.data_ok else None

    @property
    def can_cw(self) -> bool:
        return MODELS.get(self.model, MODELS["other"])[3]

    def _f(self, cmd, sub=None, data=b"") -> bytes:
        return frame(self.addr, cmd, sub, data)

    # -- queries -----------------------------------------------------------
    def poll(self) -> list[bytes]:
        q = [self._f(C_RD_FREQ), self._f(C_RD_MODE)]
        if self.data_sub is not None:
            q.append(self._f(C_CTL_MEM, self.data_sub))
            self._asked_data = True
        return q

    def split(self, buf: bytes) -> tuple[list[bytes], bytes]:
        return split_frames(buf)

    # -- commands ----------------------------------------------------------
    def set_freq(self, khz: float) -> bytes:
        return self._f(C_SET_FREQ, data=to_bcd(int(round(khz * 1000)), 5))

    def set_mode(self, radio_mode: str) -> list[bytes] | None:
        code = MODE_TO_ICOM.get(radio_mode)
        if code is None:
            return None
        out = [self._f(C_SET_MODE, data=bytes([code, self.filt]))]
        if self.data_sub is not None and radio_mode in ("LSB", "USB", "DIGU", "DIGL"):
            dig = radio_mode.startswith("DIG")
            out.append(self._f(C_CTL_MEM, self.data_sub, bytes([1 if dig else 0, self.filt if dig else 0])))
            self.data = dig
        self.base_mode = code
        return out

    def ptt(self, on: bool) -> bytes:
        return self._f(C_CTL_PTT, S_PTT, bytes([1 if on else 0]))

    def cw_speed(self, wpm: int) -> bytes:
        return self._f(C_CTL_LVL, S_LVL_KEYSPD, to_bcd_be(cw_speed_level(wpm), 2))

    def cw(self, text: str) -> list[bytes]:
        t = cw_clean(text)
        return [self._f(C_SND_CW, data=t[i:i + CW_CHUNK].encode("ascii"))
                for i in range(0, len(t), CW_CHUNK) if t[i:i + CW_CHUNK].strip()]

    def cw_abort(self) -> list[bytes]:
        return [self._f(C_SND_CW, data=b"\xff"), self.ptt(False)]

    # -- answers -----------------------------------------------------------
    def mode_name(self) -> str | None:
        if self.base_mode is None:
            return None
        m = MODE_FROM_ICOM.get(self.base_mode)
        if self.data and m in ("USB", "LSB"):
            return "DIGU" if m == "USB" else "DIGL"
        return m

    def parse(self, body: bytes) -> list[tuple[str, object]]:
        """One frame body (to, from, cmd, ...) -> [("freq", kHz) / ("mode", name)]."""
        if len(body) < 3:
            return []
        to, frm, cmd, data = body[0], body[1], body[2], body[3:]
        if frm == CTRLID or to not in (CTRLID, 0x00) or frm != self.addr:
            return []                                # our own echo, or another device
        if cmd == NAK:
            # The data-mode query is the only one older radios refuse. Give up on
            # it after a few NGs in a row (one NG could be a refused tuning command).
            if self._asked_data:
                self._naks += 1
                if self._naks >= 3:
                    self.data_ok = False
            return []
        if cmd == ACK:
            return []
        if cmd in (C_RD_FREQ, C_SND_FREQ) and len(data) >= 5:
            hz = from_bcd(data[:5])
            return [("freq", hz / 1000.0)] if hz else []
        if cmd in (C_RD_MODE, C_SND_MODE) and data:
            if data[0] not in MODE_FROM_ICOM:
                return []
            self.base_mode = data[0]
            if len(data) > 1 and 1 <= data[1] <= 3:
                self.filt = data[1]
            return [("mode", self.mode_name())]
        sub = self.data_sub
        if cmd == C_CTL_MEM and sub is not None and len(data) >= 2 and data[0] == sub:
            self._asked_data, self._naks = False, 0
            self.data = data[1] != 0
            return [("mode", self.mode_name())] if self.base_mode is not None else []
        return []
