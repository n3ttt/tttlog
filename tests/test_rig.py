"""Radio (CAT): protocol, and following / tuning a fake radio over TCP."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path

import pytest

from tttlog import config
from tttlog.contests.engine import Station
from tttlog.core.db import Log
from tttlog.core.rig import Dialect, from_logger_mode, split_replies, to_logger_mode


def test_dialects():
    flex, yaesu, ken = Dialect("flex"), Dialect("yaesu"), Dialect("kenwood")
    assert flex.parse("FA00014074000") == ("freq", 14074.0)
    assert flex.parse("ZZMD07") == ("mode", "DIGU") and flex.parse("ZZMD04") == ("mode", "CWU")
    assert yaesu.parse("FA014025500") == ("freq", 14025.5) and yaesu.parse("MD0C") == ("mode", "DIGU")
    assert ken.parse("MD2") == ("mode", "USB") and ken.parse("ID908") is None
    assert flex.set_freq(7025.25) == b"FA00007025250;" and yaesu.set_freq(7025.25) == b"FA007025250;"
    assert flex.set_mode("CWU") == b"ZZMD04;" and yaesu.set_mode("USB") == b"MD02;"
    assert flex.poll() == [b"FA;", b"ZZMD;"]
    assert split_replies(b"FA00014074000;ZZMD07;FA0001") == (["FA00014074000", "ZZMD07"], b"FA0001")


def test_mode_mapping():
    gen = ["SSB", "CW", "FT8", "FT4", "RTTY", "AM", "FM"]
    assert to_logger_mode("USB", "CW", gen) == "SSB" and to_logger_mode("CWL", "SSB", gen) == "CW"
    assert to_logger_mode("DIGU", "FT4", gen) == "FT4"           # radio can't tell FT8 from FT4
    assert to_logger_mode("DIGU", "SSB", gen) == "FT8"
    assert from_logger_mode("SSB", 7200) == "LSB" and from_logger_mode("SSB", 14250) == "USB"
    assert from_logger_mode("SSB", 5330.5) == "USB" and from_logger_mode("FT8", 7074) == "DIGU"


# ---------------------------------------------------------------- fake radio
class FakeFlex:
    """Answers FA; / ZZMD; like SmartSDR CAT and records anything else sent."""

    def __init__(self):
        from PySide6.QtNetwork import QHostAddress, QTcpServer
        self.freq_hz, self.mode = 14074000, "07"
        self.writes: list[str] = []
        self.server = QTcpServer()
        assert self.server.listen(QHostAddress.LocalHost, 0)
        self.server.newConnection.connect(self._conn)
        self.port = self.server.serverPort()
        self.clients = []

    def _conn(self):
        c = self.server.nextPendingConnection()
        self.clients.append(c)
        buf = [b""]

        def read():
            buf[0] += bytes(c.readAll())
            *cmds, buf[0] = buf[0].split(b";")
            for cmd in (x.decode() for x in cmds):
                if cmd == "FA":
                    c.write(f"FA{self.freq_hz:011d};".encode())
                elif cmd == "ZZMD":
                    c.write(f"ZZMD{self.mode};".encode())
                elif cmd.startswith("FA"):
                    self.writes.append(cmd); self.freq_hz = int(cmd[2:])
                elif cmd.startswith("ZZMD"):
                    self.writes.append(cmd); self.mode = cmd[4:]
                else:
                    self.writes.append(cmd)
        c.readyRead.connect(read)


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
    db = tmp_path / "general_log.db"
    l = Log(db); l.set_meta("contest_id", "GENERAL"); l.close()
    w.open_log(db)
    w.set_mode("SSB"); w.set_freq(7200)
    yield w
    w.close()


def _cfg(radio, control):
    return {**config.DEFAULT_RIG, "enabled": True, "port": radio.port, "poll_ms": 150, "control": control}


def test_follow_only_never_writes(app, win):
    radio = FakeFlex()
    win.rig.start(_cfg(radio, control=False))
    assert _pump(app, lambda: win.freq_khz == 14074.0 and win.mode == "FT8")
    assert "● Radio (follow)" in win.rig_lbl.text()

    radio.freq_hz, radio.mode = 14025500, "04"                  # turn the dial, switch to CW
    assert _pump(app, lambda: win.freq_khz == 14025.5 and win.mode == "CW")
    assert win.band_pane.buttons["20m"].isChecked()

    win.band_pane.buttons["40m"].click()                         # follow-only: refused, radio untouched
    win.call.setText("7030"); win.on_enter()
    assert win.freq_khz == 14025.5 and "Tune the radio" in win.banner_lbl.text()
    win.set_mode("SSB")
    for _ in range(30):
        app.processEvents(); time.sleep(0.01)
    assert radio.writes == []                                    # nothing but read queries, ever

    win.call.setText("DL1ABC"); win.on_enter()                  # logs the radio's real frequency
    assert win.qsos[-1].freq_khz == 14025.5
    win.rig.stop()


def test_control_tunes_the_radio(app, win):
    radio = FakeFlex()
    win.rig.start(_cfg(radio, control=True))
    assert _pump(app, lambda: win.freq_khz == 14074.0 and "● Radio" in win.rig_lbl.text())
    win.set_mode("CW")
    win.band_pane.buttons["40m"].click()
    assert _pump(app, lambda: radio.freq_hz == 7025000 and radio.mode == "04")
    assert "ZZMD04" in radio.writes and "FA00007025000" in radio.writes
    for _ in range(60):                                          # stale polls don't bounce the display
        app.processEvents(); time.sleep(0.01)
    assert win.freq_khz == 7025.0 and win.mode == "CW"


def test_radio_gone_and_back(app, win):
    radio = FakeFlex()
    import tttlog.ui.rig_control as rc
    rc.RETRY_MS = 200
    win.rig._retry.setInterval(200)
    win.rig.start(_cfg(radio, control=False))
    assert _pump(app, lambda: win.rig.is_connected())
    for c in radio.clients:
        c.disconnectFromHost()
    assert _pump(app, lambda: "retrying" in win.rig.state)
    assert _pump(app, lambda: win.rig.state.startswith("connected to"))
    win.rig.stop()
    assert win.rig_lbl.isHidden()
