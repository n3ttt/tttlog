"""WSJT-X connector: decode its UDP packets and log what it logs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path

import pytest

from tttlog import config
from tttlog.contests.engine import Station
from tttlog.core import wsjtx
from tttlog.core.db import Log

ADIF = ("<call:6>JA1XYZ <gridsquare:4>PM95 <mode:3>FT8 <rst_sent:3>-12 <rst_rcvd:3>-08 "
        "<qso_date:8>20261118 <time_on:6>183015 <qso_date_off:8>20261118 <time_off:6>183130 "
        "<band:3>20m <freq:9>14.075512 <station_callsign:5>N3TTT <my_gridsquare:4>FM19 "
        "<name:4>TARO <eor>")


def test_parse_packets():
    m = wsjtx.parse(wsjtx.build(wsjtx.LOGGED_ADIF, "WSJT-X", adif=ADIF))
    assert m.type == wsjtx.LOGGED_ADIF and m.id == "WSJT-X" and "JA1XYZ" in m.text
    hb = wsjtx.parse(wsjtx.build(wsjtx.HEARTBEAT, "JTDX", version="2.2.159"))
    assert hb.type == wsjtx.HEARTBEAT and hb.id == "JTDX" and hb.text == "2.2.159"
    assert wsjtx.parse(wsjtx.build(wsjtx.CLOSE)).type == wsjtx.CLOSE
    assert wsjtx.parse(wsjtx.build(wsjtx.QSO_LOGGED)) is None          # same QSO as type 12: ignored
    assert wsjtx.parse(b"junk") is None
    assert wsjtx.parse(wsjtx.build(wsjtx.LOGGED_ADIF, adif=ADIF)[:-10]) is None   # cut short


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, cond, ms=3000):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end and not cond():
        app.processEvents()
        time.sleep(0.01)
    return cond()


def _send(port, data):
    from PySide6.QtNetwork import QHostAddress, QUdpSocket
    s = QUdpSocket()
    s.writeDatagram(data, QHostAddress(QHostAddress.LocalHost), port)
    s.close()


def _free_udp_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import tttlog.ui.main_window as mw
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(mw, "QSettings", lambda *a: QSettings(ini, QSettings.IniFormat))
    for name in ("STATION_FILE", "MACROS_FILE", "CLUSTER_FILE", "COLORS_FILE"):
        monkeypatch.setattr(config, name, tmp_path / "cfg" / Path(getattr(config, name)).name)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    config.save_station(Station(call="N3TTT", cq_zone=5))
    w = mw.MainWindow()
    yield w
    w.close()


def test_wsjtx_qso_goes_in_the_log(app, win, tmp_path):
    port = _free_udp_port()
    win.wsjtx_cfg = {"enabled": True, "address": "127.0.0.1", "port": port}
    assert win.wsjtx.start(win.wsjtx_cfg)

    _send(port, wsjtx.build(wsjtx.LOGGED_ADIF, adif=ADIF))           # no log open yet
    assert _pump(app, lambda: "no log is open" in win.banner_lbl.text())

    db = tmp_path / "general_log.db"
    l = Log(db); l.set_meta("contest_id", "GENERAL"); l.close()
    win.open_log(db)

    _send(port, wsjtx.build(wsjtx.HEARTBEAT, version="2.7.0"))
    assert _pump(app, lambda: not win.wsjtx_lbl.isHidden() and "● WSJT-X" in win.wsjtx_lbl.text())

    _send(port, wsjtx.build(wsjtx.LOGGED_ADIF, adif=ADIF))
    assert _pump(app, lambda: len(win.qsos) == 1)
    q = win.qsos[0]
    assert (q.call, q.mode, q.band, q.rst_sent, q.rst_rcvd) == ("JA1XYZ", "FT8", "20m", "-12", "-08")
    assert abs(q.freq_khz - 14075.512) < 0.01 and q.exch_rcvd == "PM95 TARO"
    assert q.operator == "N3TTT" and q.contest_id == "GENERAL" and q.uid
    assert win.log.find_uid(q.uid) is not None                      # saved, and shared (has an event)
    assert win.sync.count() == 1

    _send(port, wsjtx.build(wsjtx.LOGGED_ADIF, adif=ADIF))           # sent again: not logged twice
    assert _pump(app, lambda: "already in the log" in win.banner_lbl.text())
    assert len(win.qsos) == 1

    _send(port, wsjtx.build(wsjtx.CLOSE))
    assert _pump(app, lambda: "○" in win.wsjtx_lbl.text())
    win.wsjtx.stop()
    assert win.wsjtx_lbl.isHidden()
