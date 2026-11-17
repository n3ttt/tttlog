"""The window has to fit small screens (netbooks, 1366x768 with scaling, VMs)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from tttlog import config


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import tttlog.ui.main_window as mw
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(mw, "QSettings", lambda *a: QSettings(ini, QSettings.IniFormat))
    for name in ("STATION_FILE", "MACROS_FILE", "CLUSTER_FILE", "COLORS_FILE"):
        monkeypatch.setattr(config, name, tmp_path / "cfg" / Path(getattr(config, name)).name)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    w = mw.MainWindow()
    yield w
    w.close()


def test_window_can_shrink_to_small_screen(win):
    win.show()
    win._default_tabs(); win._default_sizes()
    m = win.minimumSizeHint()
    assert m.width() <= 640 and m.height() <= 400, m
    win.resize(800, 480)
    assert win.size().toTuple() == (800, 480)


def test_oversized_saved_window_is_pulled_onto_screen(win):
    avail = win.screen().availableGeometry()
    win.resize(avail.width() + 500, avail.height() + 500)
    win.move(avail.right() + 200, avail.bottom() + 200)
    win._fit_to_screen()
    assert win.width() <= avail.width() and win.height() <= avail.height()
    assert avail.contains(win.pos())


def test_display_size_setting(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    win.set_display_size(80)
    assert int(win.settings.value("ui_scale")) == 80
    assert [a.data() for a in win.scale_menu.actions() if a.isChecked()] == [80]
