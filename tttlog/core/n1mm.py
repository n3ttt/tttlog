"""N1MM Logger+ compatible UDP packets.

Other shack programs listen for these: Green Heron's GH Everyware (rotor turns and
band-following antenna switching), rotor programs, band decoders, and others.

* RadioInfo  -> port 12060: frequency, mode, operator, running (every 10 s and on change)
* Rotor turn / stop -> port 12040, the same layout N1MM sends (Alt+J / Ctrl+Alt+J)
"""
from __future__ import annotations

from xml.sax.saxutils import escape

RADIO_PORT = 12060
ROTOR_PORT = 12040


def _freq10(khz: float) -> str:
    """kHz -> N1MM's tens-of-Hz integer (14025.5 kHz -> '1402550')."""
    return str(int(round(khz * 100)))


def _band_mhz(khz: float) -> str:
    """The band as N1MM writes it in rotor packets: 1.8, 3.5, 7, 14, 21, 28, 50..."""
    edges = [(1800, "1.8"), (3500, "3.5"), (5300, "5"), (7000, "7"), (10100, "10"), (14000, "14"),
             (18068, "18"), (21000, "21"), (24890, "24"), (28000, "28"), (50000, "50"), (144000, "144"),
             (420000, "432")]
    out = edges[0][1]
    for lo, name in edges:
        if khz >= lo:
            out = name
    return out


def radio_mode(mode: str, khz: float) -> str:
    m = (mode or "").upper()
    if m == "SSB":
        return "LSB" if khz < 10000 and not 5300 <= khz <= 5410 else "USB"
    return m or "USB"


def radio_info(*, station: str, mycall: str, op: str, khz: float, mode: str, running: bool,
               transmitting: bool = False, radio_nr: int = 1) -> bytes:
    f = _freq10(khz)
    tf = lambda b: "True" if b else "False"
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<RadioInfo>'
           f"<app>tttlog</app><StationName>{escape(station)}</StationName><RadioNr>{radio_nr}</RadioNr>"
           f"<Freq>{f}</Freq><TXFreq>{f}</TXFreq><Mode>{escape(radio_mode(mode, khz))}</Mode>"
           f"<mycall>{escape(mycall)}</mycall><OpCall>{escape(op)}</OpCall><IsRunning>{tf(running)}</IsRunning>"
           f"<FocusEntry>0</FocusEntry><EntryWindowHwnd>0</EntryWindowHwnd><Antenna>0</Antenna><Rotors></Rotors>"
           f"<FocusRadioNr>{radio_nr}</FocusRadioNr><IsStereo>False</IsStereo><IsSplit>False</IsSplit>"
           f"<ActiveRadioNr>{radio_nr}</ActiveRadioNr><IsTransmitting>{tf(transmitting)}</IsTransmitting>"
           "<FunctionKeyCaption></FunctionKeyCaption><RadioName></RadioName><AuxAntSelected>-1</AuxAntSelected>"
           "<AuxAntSelectedName></AuxAntSelectedName><IsConnected>True</IsConnected></RadioInfo>")
    return xml.encode("utf-8")


def rotor_turn(rotor: str, azimuth: float, khz: float, offset: float = 0.0, bidirectional: bool = False) -> bytes:
    """Turn to an azimuth. (N1MM's own layout: no XML header.)"""
    return ("<N1MMRotor>"
            f"<rotor>{escape(rotor)}</rotor><goazi>{azimuth % 360:.1f}</goazi><offset>{offset:.1f}</offset>"
            f"<bidirectional>{1 if bidirectional else 0}</bidirectional><freqband>{_band_mhz(khz)}</freqband>"
            "</N1MMRotor>").encode("utf-8")


def rotor_stop(rotor: str, khz: float) -> bytes:
    return ("<N1MMRotor><stop>"
            f"<rotor>{escape(rotor)}</rotor><freqband>{_band_mhz(khz)}</freqband>"
            "</stop></N1MMRotor>").encode("utf-8")


def parse_targets(text: str, default_port: int) -> list[tuple[str, int]]:
    """'127.0.0.1:12060 192.168.1.255' -> [(host, port), ...] (spaces or commas between)."""
    out = []
    for part in text.replace(",", " ").split():
        host, _, port = part.rpartition(":") if ":" in part else (part, "", "")
        try:
            p = int(port) if port else default_port
        except ValueError:
            continue
        if host and 0 < p < 65536:
            out.append((host, p))
    return out
