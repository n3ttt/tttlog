"""Beam headings, and N1MM-compatible UDP (RadioInfo, rotor turn/stop) as GH Everyware
receives it: a local UDP listener stands in for it."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from tttlog import config
from tttlog.core import geo, n1mm
from tttlog.contests.engine import Station
from test_rig import _pump, app, win  # noqa: F401  (fixtures)


def test_geo():
    assert geo.grid_to_latlon("FM29") == (39.5, -75.0)
    lat, lon = geo.grid_to_latlon("fn31pr")
    assert round(lat, 2) == 41.73 and round(lon, 2) == -72.71
    assert geo.grid_to_latlon("ZZ99") is None and geo.grid_to_latlon("") is None
    fm29 = (39.5, -75.0)
    assert round(geo.bearing(fm29, (36.0, 139.0))) == 333           # Japan: northwest over the pole
    assert round(geo.bearing(fm29, (51.5, 0.0))) == 50              # London: northeast
    assert geo.long_path(333) == 153 and geo.long_path(270) == 90
    assert 10_800 < geo.distance_km(fm29, (36.0, 139.0)) < 11_000


def test_packets():
    assert n1mm.rotor_turn("Tribander", 312.44, 14025.0) == (
        b"<N1MMRotor><rotor>Tribander</rotor><goazi>312.4</goazi><offset>0.0</offset>"
        b"<bidirectional>0</bidirectional><freqband>14</freqband></N1MMRotor>")
    assert n1mm.rotor_stop("", 21010.0) == b"<N1MMRotor><stop><rotor></rotor><freqband>21</freqband></stop></N1MMRotor>"
    ri = n1mm.radio_info(station="RUN", mycall="N3TTT", op="K3ABC", khz=7025.5, mode="SSB", running=True).decode()
    assert "<Freq>702550</Freq>" in ri and "<Mode>LSB</Mode>" in ri and "<IsRunning>True</IsRunning>" in ri
    assert "<OpCall>K3ABC</OpCall>" in ri and ri.startswith('<?xml version="1.0" encoding="utf-8"?>')
    assert n1mm.parse_targets("127.0.0.1:12060, 192.168.1.255 pc:9", 12060) == \
        [("127.0.0.1", 12060), ("192.168.1.255", 12060), ("pc", 9)]


@pytest.fixture
def listener(app):
    from PySide6.QtNetwork import QHostAddress, QUdpSocket
    socks, got = [], {"radio": [], "rotor": []}
    for kind in ("radio", "rotor"):
        s = QUdpSocket()
        assert s.bind(QHostAddress.LocalHost, 0)
        s.readyRead.connect(lambda s=s, kind=kind: [got[kind].append(bytes(s.receiveDatagram().data()))
                                                    for _ in range(100) if s.hasPendingDatagrams()])
        socks.append(s)
    yield socks[0].localPort(), socks[1].localPort(), got
    for s in socks:
        s.close()


def test_beam_and_rotor(app, win, listener):
    rport, tport, got = listener
    win.station = Station(call="N3TTT", cq_zone=5, grid="FM29")
    win.call.setText("JA1AA"); win._on_call_edited("JA1AA")
    assert win.beam_lbl.text().startswith("Beam 3")         # northwest, ~330°
    win.turn_rotor()                                        # rotor control still off
    assert "Rotor control is off" in win.banner_lbl.text()

    win.n1mm_cfg = {**config.DEFAULT_N1MM, "radio": True, "radio_targets": f"127.0.0.1:{rport}",
                    "rotor": True, "rotor_targets": f"127.0.0.1:{tport}", "rotor_name": "Tribander"}
    win.broadcast.configure(win.n1mm_cfg, win._radio_info)
    assert _pump(app, lambda: got["radio"])                 # RadioInfo straight away
    win.set_freq(14025.0)
    assert _pump(app, lambda: any(b"<Freq>1402500</Freq>" in p for p in got["radio"]))

    win.turn_rotor()
    assert _pump(app, lambda: got["rotor"])
    pkt = got["rotor"][-1].decode()
    sp = win.beam_to("JA1AA")[0]
    assert f"<goazi>{sp:.1f}</goazi>" in pkt and "<rotor>Tribander</rotor>" in pkt and "<freqband>14</freqband>" in pkt
    assert "Turning the beam" in win.banner_lbl.text()
    win.turn_rotor(long_path=True)
    assert _pump(app, lambda: len(got["rotor"]) == 2)
    assert f"<goazi>{geo.long_path(sp):.1f}</goazi>" in got["rotor"][-1].decode()
    win.stop_rotor()
    assert _pump(app, lambda: len(got["rotor"]) == 3) and b"<stop>" in got["rotor"][-1]


def test_heading_without_a_grid_uses_my_country(app, win):
    win.station = Station(call="N3TTT", cq_zone=5)
    assert win.beam_to("DL1ABC") is not None                 # from the USA's centre point
    win.station = Station(call="N0CALL", cq_zone=5)
    assert win.beam_to("DL1ABC") is None
