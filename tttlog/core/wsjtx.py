"""WSJT-X UDP messages (also JTDX, MSHV and others that copy the protocol).

WSJT-X sends small datagrams to its "UDP Server" (Settings > Reporting).
Each one is a Qt QDataStream, big-endian:

    quint32 magic 0xADBCCBDA, quint32 schema, quint32 type, utf8 id, ...

where a "utf8" string is a quint32 byte length (0xFFFFFFFF = null) followed
by UTF-8 bytes. tttlog only needs:

    0  Heartbeat    (to show WSJT-X is there)
    6  Close        (WSJT-X quit)
    12 Logged ADIF  (one ADIF record of the QSO you just logged)

Type 5 (QSO Logged) carries the same QSO as separate fields and arrives
alongside type 12, so it is ignored to avoid logging every QSO twice.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = 0xADBCCBDA
HEARTBEAT, STATUS, QSO_LOGGED, CLOSE, LOGGED_ADIF = 0, 1, 5, 6, 12


@dataclass
class Message:
    type: int
    id: str                 # the sending program's name, e.g. "WSJT-X" or "WSJT-X - IC7300"
    text: str = ""          # Logged ADIF: the ADIF; Heartbeat: "version revision"


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def u32(self) -> int:
        if self.pos + 4 > len(self.data):
            raise ValueError("short packet")
        (v,) = struct.unpack_from(">I", self.data, self.pos)
        self.pos += 4
        return v

    def utf8(self) -> str:
        n = self.u32()
        if n == 0xFFFFFFFF:
            return ""
        if self.pos + n > len(self.data):
            raise ValueError("short string")
        s = self.data[self.pos:self.pos + n].decode("utf-8", "replace")
        self.pos += n
        return s


def parse(data: bytes) -> Message | None:
    """Decode one datagram; None if it isn't a WSJT-X message tttlog uses."""
    try:
        r = _Reader(data)
        if r.u32() != MAGIC:
            return None
        r.u32()                                     # schema (2 or 3); layout of these types is the same
        kind = r.u32()
        ident = r.utf8()
        if kind == LOGGED_ADIF:
            return Message(kind, ident, r.utf8())
        if kind == HEARTBEAT:
            r.u32()                                 # max schema
            return Message(kind, ident, f"{r.utf8()} {r.utf8()}".strip())
        if kind == CLOSE:
            return Message(kind, ident)
    except ValueError:
        return None
    return None


# -- building packets (tests, and a stand-in WSJT-X) ---------------------------
def _s(text: str | None) -> bytes:
    if text is None:
        return struct.pack(">I", 0xFFFFFFFF)
    b = text.encode("utf-8")
    return struct.pack(">I", len(b)) + b


def build(kind: int, ident: str = "WSJT-X", *, adif: str = "", version: str = "2.7.0",
          revision: str = "") -> bytes:
    out = struct.pack(">III", MAGIC, 2, kind) + _s(ident)
    if kind == LOGGED_ADIF:
        out += _s(adif)
    elif kind == HEARTBEAT:
        out += struct.pack(">I", 3) + _s(version) + _s(revision)
    return out
