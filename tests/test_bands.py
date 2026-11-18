"""Band buttons."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from tttlog import config
from tttlog.contests.engine import Station
from tttlog.core.db import Log
from tttlog.core.models import band_start_khz, mode_group


def test_band_start_frequencies():
    assert band_start_khz("20m", "CW") == 14025 and band_start_khz("20m", "SSB") == 14250
    assert band_start_khz("20m", "FT8") == 14074 and mode_group("FT4") == "DIGI"
    assert band_start_khz("30m", "SSB") == 10110            # no phone on 30m: CW end
    assert band_start_khz("2m", "FM") == 146520


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_band_buttons(app, tmp_path, monkeypatch):
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
    p = w.band_pane
    assert "2m" in p.buttons and "30m" in p.buttons                 # the log's own bands

    w.set_mode("SSB")
    p.buttons["40m"].click()
    assert w.freq_khz == 7200 and p.buttons["40m"].isChecked()
    w.set_freq(7185.5)                                              # tune around on 40
    p.buttons["20m"].click()
    assert w.freq_khz == 14250 and not p.buttons["40m"].isChecked()
    p.buttons["40m"].click()
    assert w.freq_khz == 7185.5                                     # back where you were

    w.set_mode("CW")
    p.buttons["40m"].click()
    assert w.freq_khz == 7025                                       # CW has its own spot
    w.call.setText("3525"); w.on_enter()                            # typed QSY lights the band
    assert p.buttons["80m"].isChecked()
    w.close()

