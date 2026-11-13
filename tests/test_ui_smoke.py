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
