"""General (everyday, non-contest) log."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tttlog import config
from tttlog.contests.engine import ContestEngine, Station, list_contests, load_rules
from tttlog.core.cluster import SpotList, parse_spot
from tttlog.core.cty import CtyDat
from tttlog.core.db import Log
from tttlog.core.models import QSO
from tttlog.export.adif import export_adif, import_adif

FIX = Path(__file__).parent / "fixtures" / "cty_sample.dat"
T0 = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def eng():
    return ContestEngine(load_rules("GENERAL"), CtyDat(FIX), Station(call="N3TTT", cq_zone=5))


def q(call, khz=14200.0, mode="SSB", minutes=0, notes=""):
    return QSO(call=call, freq_khz=khz, mode=mode, exch_rcvd=notes,
               time_utc=T0 + timedelta(minutes=minutes))


def test_general_is_listed_first():
    assert list_contests()[0]["id"] == "GENERAL"


def test_no_dupes_no_points_dxcc_counted(eng):
    log = eng.rescore([q("DL1ABC"), q("DL1ABC", minutes=5), q("W1AW", 7200, minutes=9),
                       q("G4XYZ", 144300, minutes=12)])          # 2m works in a general log
    assert not any(x.is_dupe for x in log)
    s = eng.score(log)
    assert s.qsos == 4 and s.points == 0 and s.mults == 3      # DL, W, G once each
    assert not eng.is_dupe("DL1ABC", "20m", "SSB", log)
    assert [x.time_utc for x in eng.worked_before("dl1abc", log)] == [T0 + timedelta(minutes=5), T0]


def test_free_text_exchange_is_optional(eng):
    assert not eng.exchange_required()
    assert eng.validate_rcvd("") == []
    assert eng.parse_rcvd("bob denver co") == {"notes": "BOB DENVER CO"}
    assert eng.sent_exchange() == ""


def test_rst_default_follows_mode(eng):
    assert eng.default_rst("CW") == "599" and eng.default_rst("SSB") == "59"
    assert eng.default_rst("FT8") == "-10" and eng.default_rst(None) == "59"
    cw = ContestEngine(load_rules("CQ-WW-CW"), CtyDat(FIX), Station(call="N3TTT"))
    assert cw.default_rst("CW") == "599"                          # plain string defaults still work


def test_ft8_spots_are_workable(eng):
    sl = SpotList()
    now = datetime(2026, 11, 1, 18, 30, tzinfo=timezone.utc)
    sl.add(parse_spot("DX de KB3Z:  14074.0  JA1XYZ   FT8 -12dB  1829Z", now))
    sl.evaluate(eng, [])
    s = sl.spots()[0]
    assert s.mode == "DIGI" and s.status == "MULT"                # new one, not "can't work"


def test_adif_round_trip_keeps_notes(eng, tmp_path):
    log = [q("DL1ABC", notes="HANS MUNICH"), q("W1AW", 7030, "CW")]
    for x in log:
        x.contest_id = "GENERAL"
    p = tmp_path / "g.adi"
    export_adif(log, p)
    text = p.read_text()
    assert "<COMMENT:11>HANS MUNICH" in text and "CONTEST_ID" not in text
    back = import_adif(p, general=True)
    assert back[0].exch_rcvd == "HANS MUNICH" and back[1].mode == "CW"


def test_old_log_gets_uids(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)                                      # a log from before networking
    c.executescript("""CREATE TABLE qso (id INTEGER PRIMARY KEY AUTOINCREMENT, time_utc TEXT NOT NULL,
        call TEXT NOT NULL, freq_khz REAL NOT NULL, band TEXT, mode TEXT NOT NULL, rst_sent TEXT,
        rst_rcvd TEXT, exch_sent TEXT, exch_rcvd TEXT, station_call TEXT, operator TEXT,
        contest_id TEXT, country TEXT, cq_zone INTEGER, points INTEGER, is_dupe INTEGER);""")
    c.execute("INSERT INTO qso (time_utc, call, freq_khz, mode) VALUES (?,?,?,?)",
              (T0.isoformat(), "DL1ABC", 14200, "SSB"))
    c.commit(); c.close()
    log = Log(db)
    (x,) = log.all()
    assert len(x.uid) == 32 and log.find_uid(x.uid).call == "DL1ABC"


# ------------------------------------------------------------------ UI
@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_general_log_ui(app, tmp_path, monkeypatch):
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
    assert w.score_table.isColumnHidden(2)

    w.call.setText("DL1ABC"); w._live_check("DL1ABC")
    assert "NEW ONE" in w.banner_lbl.text()
    w.exch.setText("HANS"); w.on_enter()                    # logs at once: no contest exchange
    assert len(w.qsos) == 1 and w.qsos[0].exch_rcvd == "HANS"

    w.call.setText("DL1ABC"); w._live_check("DL1ABC")
    assert "Worked 1×" in w.banner_lbl.text() and "DUPE" not in w.banner_lbl.text()
    w.on_enter()                                            # call only: logs, no notes needed
    assert len(w.qsos) == 2 and not w.qsos[1].is_dupe

    w.call.setText("CW"); w.on_enter()                      # type a mode to switch
    assert w.mode == "CW" and w.rst.text() == "599"
    assert "DXCC 1" in w.score_lbl.text()
    w.close()
