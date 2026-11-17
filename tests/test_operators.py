"""Per-operator rates and OPON."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tttlog import config
from tttlog.contests.engine import Station
from tttlog.core import rates
from tttlog.core.db import Log
from tttlog.core.models import QSO
from tttlog.export.cabrillo import operators

T0 = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)


def q(call, op, minutes, khz=14200.0):
    return QSO(call=call, freq_khz=khz, mode="SSB", operator=op, station_call="N3TTT",
               time_utc=T0 + timedelta(minutes=minutes))


def test_rates_by_operator():
    log = [q(f"K{i}AA", "N3TTT", i) for i in range(12)] + [q(f"W{i}BB", "K3ABC", 30 + i) for i in range(3)]
    now = T0 + timedelta(minutes=40)
    rows = rates.by_operator(log, now)
    assert [(r.op, r.qsos) for r in rows] == [("N3TTT", 12), ("K3ABC", 3)]
    assert rows[0].summary.last10 > 0 and rows[1].summary.last10 == 0      # K3ABC hasn't 10 yet
    assert rows[1].summary.last15_count == 3
    assert rates.operators(log) == ["N3TTT", "K3ABC"]
    assert operators(log, Station(call="N3TTT")) == "N3TTT K3ABC"


def test_hourly_for_one_op_keeps_mults_log_wide():
    log = [q("DL1A", "N3TTT", 0), q("DL2B", "K3ABC", 5), q("G4C", "K3ABC", 6)]
    keys = lambda x: [x.call[:1]]                       # D, G
    rows = rates.hourly(log, mult_keys=keys, only=lambda x: x.operator == "K3ABC")
    assert rows[0].qsos == 2 and rows[0].mults == 1    # DL was N3TTT's mult, G was K3ABC's


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_opon_sets_operator(app, tmp_path, monkeypatch):
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
    assert w.current_op == "N3TTT"

    w.call.setText("DL1ABC"); w.on_enter()
    w.call.setText("opon k3abc"); w.on_enter()          # OPON <call> in the call field
    assert w.current_op == "K3ABC" and "OP K3ABC" in w.radio_lbl.text()
    assert w.call.text() == ""
    w.call.setText("W1AW"); w.on_enter()
    assert [x.operator for x in w.qsos] == ["N3TTT", "K3ABC"]

    w.call.setText("OPON 12"); w.on_enter()              # junk is refused
    assert w.current_op == "K3ABC" and "doesn't look like" in w.banner_lbl.text()

    p = w.rate_pane
    assert [p.ops.item(r, 0).text() for r in range(p.ops.rowCount())] == ["K3ABC", "N3TTT"] or \
           sorted(p.ops.item(r, 0).text() for r in range(p.ops.rowCount())) == ["K3ABC", "N3TTT"]
    p._pick_op("K3ABC")
    assert p.op_pick.currentText() == "K3ABC  (you)" and p.vals["last15"].text().startswith("1 ")
    w.close()
