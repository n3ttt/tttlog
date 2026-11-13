"""Headless smoke test of the main window (QT_QPA_PLATFORM=offscreen)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tttlog import config
from tttlog.contests.engine import Station
from tttlog.core.db import Log


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def private_settings(tmp_path, monkeypatch):
    """Keep tests out of the real app's saved settings (last log, window layout)."""
    from PySide6.QtCore import QSettings
    import tttlog.ui.main_window as mw
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(mw, "QSettings", lambda *a: QSettings(ini, QSettings.IniFormat))


def test_log_flow(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "STATION_FILE", tmp_path / "cfg" / "station.yaml")
    monkeypatch.setattr(config, "MACROS_FILE", tmp_path / "cfg" / "macros.yaml")
    config.save_station(Station(call="N3TTT", state="DE", cq_zone=5))
    from tttlog.ui.main_window import MainWindow
    w = MainWindow()
    w.settings.clear()
    db = tmp_path / "t.db"
    l = Log(db); l.set_meta("contest_id", "ARRL-DX-SSB"); l.close()
    w.open_log(db)

    w.call.setText("14250"); w.on_enter()               # QSY by typing freq
    assert w.freq_khz == 14250

    w.call.setText("DL1ABC"); w._live_check("DL1ABC")
    assert "NEW MULT" in w.banner_lbl.text()
    w.on_enter()                                        # no exch -> sends F2
    assert "TX F2" in w.tx_lbl.text()
    w.exch.setText("100"); w.on_enter()                 # logs
    assert len(w.qsos) == 1 and w.qsos[0].points == 3

    w.call.setText("DL1ABC"); w._live_check("DL1ABC")
    assert "DUPE" in w.banner_lbl.text()
    w.wipe()

    w.call.setText("W1AW"); w._live_check("W1AW")
    assert "Not valid" in w.banner_lbl.text()
    w.wipe()

    w.call.setText("G4XYZ"); w.exch.setText("BADPWR!"); w.on_enter()
    assert "bad PWR" in w.banner_lbl.text() and len(w.qsos) == 1
    w.exch.setText("KW"); w.on_enter()
    assert len(w.qsos) == 2
    assert w.score_lbl.text().endswith("12")

    w.toggle_run(); w.fkey(0)
    assert "N3TTT" in w.tx_lbl.text()
    w.close()


def _pump(app, cond, ms=3000):
    from PySide6.QtCore import QElapsedTimer
    t = QElapsedTimer(); t.start()
    while not cond() and t.elapsed() < ms:
        app.processEvents()
    return cond()


def test_rate_and_cluster_panes(app, tmp_path, monkeypatch):
    """Fake telnet cluster on localhost: login, spots, filters, QSY, re-evaluate."""
    from PySide6.QtNetwork import QHostAddress, QTcpServer
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "STATION_FILE", tmp_path / "cfg" / "station.yaml")
    monkeypatch.setattr(config, "MACROS_FILE", tmp_path / "cfg" / "macros.yaml")
    monkeypatch.setattr(config, "CLUSTER_FILE", tmp_path / "cfg" / "cluster.yaml")
    monkeypatch.setattr(config, "COLORS_FILE", tmp_path / "cfg" / "colors.yaml")
    config.save_station(Station(call="N3TTT", state="DE", cq_zone=5))

    server = QTcpServer()
    assert server.listen(QHostAddress.LocalHost, 0)
    received = []
    conns = []

    def on_conn():
        c = server.nextPendingConnection()
        conns.append(c)
        c.readyRead.connect(lambda: received.append(bytes(c.readAll()).decode()))
        c.write(bytes([255, 251, 1]) + b"Welcome to FakeSpider\r\nlogin: ")
    server.newConnection.connect(on_conn)

    config.save_cluster({**config.DEFAULT_CLUSTER, "host": "127.0.0.1",
                         "port": server.serverPort(), "init_commands": ["sh/dx 5"]})
    from tttlog.ui.main_window import MainWindow
    w = MainWindow()
    w.settings.clear()
    db = tmp_path / "c.db"
    l = Log(db); l.set_meta("contest_id", "ARRL-DX-SSB"); l.close()
    w.open_log(db)

    w.cluster_connect(True)
    assert _pump(app, lambda: any("N3TTT" in r for r in received)), "no login sent"
    assert _pump(app, lambda: any("sh/dx 5" in r for r in received), 4000), "init cmd not sent"
    assert "Disconnect" == w.telnet_pane.conn_btn.text()

    from PySide6.QtCore import QDateTime, Qt
    hhmm = QDateTime.currentDateTimeUtc().toString("HHmm")
    for call, khz in [("DL1ABC", 14250.0), ("JA1AA", 14270.0), ("W1AW", 14280.0), ("G4XYZ", 21300.0)]:
        conns[0].write(f"DX de W3LPL:  {khz:.1f}  {call}   CQ   {hhmm}Z\r\n".encode())
    ok = _pump(app, lambda: len(w.spots_pane.spots) == 4)
    assert ok, (w.telnet_pane.console.toPlainText(), len(w.spots_pane.spots))
    _pump(app, lambda: False, 400)                     # let the debounced refresh run
    pane = w.spots_pane
    shown = lambda: [pane.table.item(r, 2).text() for r in range(pane.table.rowCount())]
    assert sorted(shown()) == ["DL1ABC", "G4XYZ", "JA1AA"]          # W1AW not needed
    assert "3 mults" in pane.summary_lbl.text()

    pane.search.setText("japan"); assert shown() == ["JA1AA"]
    pane.search.setText("")
    w.set_freq(21250.0); pane.band_box.setCurrentIndex(1)            # current band only
    assert shown() == ["G4XYZ"]
    pane.band_box.setCurrentIndex(0)
    pane.toggles["spot_dupe"].box.setChecked(True)                   # show dupes / can't-work too
    assert "W1AW" in shown()
    pane.toggles["spot_dupe"].box.setChecked(False)
    pane.toggles["spot_q"].box.setChecked(False)                      # mults only
    assert "W1AW" not in shown() and len(shown()) == 3
    pane.toggles["spot_q"].box.setChecked(True)
    assert config.load_colors()["spot_q"]["show"] is True              # checkbox state is saved
    pane.toggles["spot_mult"].set_color("#123456")
    assert config.load_colors()["spot_mult"]["color"] == "#123456"
    assert pane.table.item(0, 0).background().color().name() == "#123456"

    # Needed window: Germany needed on 20m and spotted; Japan spotted on 20m
    np = w.needed_pane
    _pump(app, lambda: False, 400)
    def cell(country, band):
        col = 1 + np._cols.index(band)
        row = next(i for i, r in enumerate(np._rows) if country in r.title)
        return np._rows[row].cells[band], np.table.item(row, col)
    st, it = cell("Germany", "20m")
    assert st == "needed_spotted" and it.text() == "●"
    assert "spotted now" in np.summary_lbl.text()
    # tick only "Needed & spotted": list shrinks to spotted countries only
    np.toggles["needed"].box.setChecked(False)
    assert {r.value for r in np._rows} == {"Fed. Rep. of Germany", "Japan", "England"}
    np.search.setText("japan")
    assert [r.value for r in np._rows] == ["Japan"]
    np.search.setText("")
    np.toggles["needed"].box.setChecked(True)

    # double-click DL1ABC -> QSY + S&P + call in entry line, then log it
    row = shown().index("DL1ABC")
    pane._activate_row(pane.table.model().index(row, 0))
    assert w.freq_khz == 14250.0 and not w.run_mode and w.call.text() == "DL1ABC"
    assert "NEW MULT" in w.banner_lbl.text()
    w.exch.setText("100"); w.on_enter()
    assert len(w.qsos) == 1
    _pump(app, lambda: False, 400)
    dl = next(s for s in pane.spots.spots() if s.call == "DL1ABC")
    assert dl.status == "DUPE" and "DL1ABC" not in shown()
    assert cell("Germany", "20m")[0] == "worked_spotted"
    assert cell("Germany", "15m")[0] == "needed"

    # double-click a spotted cell in Needed -> go to that spot
    row = next(i for i, r in enumerate(np._rows) if r.value == "Japan")
    np._activate(row, 1 + np._cols.index("20m"))
    assert w.call.text() == "JA1AA" and w.freq_khz == 14270.0

    # Telnet window can be hidden; spots keep coming
    w.dock_telnet.close()
    conns[0].write(f"DX de K3LR:  21310.0  PY2AA   CQ   {hhmm}Z\r\n".encode())
    assert _pump(app, lambda: len(pane.spots) == 5)

    # minimize (roll up) and pop out
    w.dock_spots.set_minimized(True)
    assert w.dock_spots.minimized and not pane.isVisible()
    w.restore_all_panes()
    assert not w.dock_spots.minimized
    w.dock_rate.toggle_floating()
    assert w.dock_rate.isFloating()
    assert w.dock_rate.windowFlags() & Qt.WindowMinimizeButtonHint
    w.dock_all_panes()
    assert not w.dock_rate.isFloating()

    # rate pane picked up the QSO
    assert w.rate_pane.table.rowCount() == 1
    assert w.rate_pane.vals["last60"].text() == "1"

    # Ctrl+G target: newest needed mult
    w.go_to_next_needed()
    assert w.call.text() in ("JA1AA", "G4XYZ")

    # typed command goes to the cluster
    w.telnet_pane.cmd.setText("sh/dx 10"); w._cluster_cmd()
    assert _pump(app, lambda: any("sh/dx 10" in r for r in received))
    w.cluster_connect(False)
    assert w.telnet_pane.conn_btn.text() == "Connect"
    w.close()
    server.close()


def test_entry_pane_is_compact(app, tmp_path, monkeypatch):
    for name in ("CONFIG_DIR", "STATION_FILE", "MACROS_FILE", "CLUSTER_FILE", "COLORS_FILE"):
        monkeypatch.setattr(config, name, tmp_path / "cfg" / name.lower())
    from tttlog.ui.main_window import MainWindow
    w = MainWindow()
    w.settings.clear()
    w.resize(1400, 1000); w.show()
    for _ in range(20):
        app.processEvents()
    assert w.centralWidget() is None
    e = w.dock_entry
    assert not e.bar.close_btn.isVisible() or not e.closable
    assert e.height() < 260, e.height()                    # just the entry, no blank space
    assert w.dock_log.geometry().top() >= e.geometry().bottom()
    assert w.dock_log.height() > 600                       # the space went to the panes
    assert w.call.height() >= w.call.sizeHint().height()   # entry fields not squashed
    w.close()
