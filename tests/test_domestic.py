"""US domestic contests and CWT: exchanges, dupes, points, multipliers, serials,
Cabrillo lines. (The rules themselves should still be checked against each contest's
current official rules before it.)"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tttlog.contests.engine import ContestEngine, Station, load_rules
from tttlog.core.cty import CtyDat
from tttlog.core.models import QSO
from tttlog.export.cabrillo import qso_line

FIX = Path(__file__).parent / "fixtures" / "cty_sample.dat"
T0 = datetime(2027, 11, 6, 21, 0, tzinfo=timezone.utc)
ME = Station(call="N3TTT", name="Adam Zaimes", state="DE", cq_zone=5, section="DE", ss_check="99",
             ss_precedence="B", cwops="", fd_class="2A")


def eng(cid, station=ME):
    return ContestEngine(load_rules(cid), CtyDat(FIX), station)


def log(e, rows, mode=None):
    out = []
    for i, (call, khz, exch, *m) in enumerate(rows):
        q = QSO(call=call, freq_khz=khz, mode=(m[0] if m else mode or e.rules["modes"][0]), exch_rcvd=exch,
                time_utc=T0 + timedelta(minutes=i))
        q.exch_sent = e.sent_exchange(out, for_log=True)
        out.append(q)
    return e.rescore(out)


def test_all_contests_load():
    from tttlog.contests.engine import list_contests
    ids = {c["id"] for c in list_contests()}
    assert {"NAQP-CW", "NAQP-SSB", "CWOPS-CWT", "ARRL-SS-CW", "ARRL-SS-SSB", "ARRL-10", "ARRL-160",
            "ARRL-FD"} <= ids


def test_naqp():
    e = eng("NAQP-CW")
    assert e.sent_exchange() == "ADAM DE" and not e.uses_rst
    assert e.validate_rcvd("JOE PA", "W1AW") == [] and e.validate_rcvd("", "W1AW") == ["missing NAME"]
    l = log(e, [("W1AW", 14025, "JOE CT"), ("K3LR", 14030, "TIM PA"), ("VE3XX", 14040, "BOB ON"),
                ("XE1AA", 14050, "JUAN XE"), ("DL1ABC", 14060, "HANS"), ("W1AW", 7025, "JOE CT"),
                ("W1AW", 14026, "JOE CT")])
    s = e.score(l)
    assert s.qsos == 6 and s.dupes == 1 and s.points == 6
    assert s.mult_sets["States/Prov"] == {("20m", "CT"), ("20m", "PA"), ("20m", "ON"), ("40m", "CT")}
    assert s.mult_sets["NA DXCC"] == {("20m", "Mexico")}          # Germany isn't North American
    assert s.total == 6 * 5


def test_cwt():
    e = eng("CWOPS-CWT")
    assert e.sent_exchange() == "ADAM DE"                         # no member number: the state
    e2 = eng("CWOPS-CWT", Station(call="N3TTT", name="Adam", state="DE", cwops="3456"))
    assert e2.sent_exchange() == "ADAM 3456"
    l = log(e, [("W1AW", 14025, "JOE 1"), ("K3LR", 14030, "TIM 123"), ("W1AW", 7025, "JOE 1"),
                ("DL1ABC", 14040, "HANS DL")])
    s = e.score(l)
    assert s.qsos == 4 and s.mults == 3 and s.total == 12          # calls count once, on any band
    assert e.validate_rcvd("JOE", "W1AW") == ["missing NR/ST"]


def test_sweepstakes():
    e = eng("ARRL-SS-CW")
    assert e.sent_exchange([]) == "1 B N3TTT 99 DE"               # serial, prec, call, check, section
    assert e.sent_exchange([], for_log=True) == "1 B 99 DE"       # the call isn't logged twice
    assert e.validate_rcvd("12 A 72 CT", "W1AW") == []
    assert e.validate_rcvd("12 A 72 XX", "W1AW") == ["bad SEC: XX"]
    assert e.validate_rcvd("12 Z 72 CT", "W1AW") == ["bad PREC: Z"]
    l = log(e, [("W1AW", 14025, "12 A 72 CT"), ("K3LR", 7025, "40 B 77 WPA"), ("W1AW", 3550, "13 A 72 CT")])
    s = e.score(l)
    assert s.qsos == 2 and s.dupes == 1                           # once per contest, any band
    assert s.points == 4 and s.mults == 2 and s.total == 8
    assert [q.exch_sent for q in l] == ["1 B 99 DE", "2 B 99 DE", "3 B 99 DE"]   # serials count up
    line = qso_line(l[0], "N3TTT", e.uses_rst)
    assert line.split()[5:] == ["N3TTT", "1", "B", "99", "DE", "W1AW", "12", "A", "72", "CT"]


def test_arrl_10():
    e = eng("ARRL-10")
    assert e.uses_rst and e.sent_exchange() == "DE"
    assert e.validate_rcvd("PA", "K3LR") == [] and e.validate_rcvd("123", "DL1ABC") == []
    assert e.validate_rcvd("ZZ", "K3LR") == ["bad ST/PROV or NR: ZZ"]
    l = log(e, [("K3LR", 28400, "PA", "SSB"), ("K3LR", 28030, "PA", "CW"), ("K3LR", 28410, "PA", "SSB"),
                ("DL1ABC", 28420, "15", "SSB"), ("VE3XX", 28040, "ON", "CW")])
    s = e.score(l)
    assert s.dupes == 1 and s.points == 2 + 4 + 2 + 4               # phone 2, CW 4
    assert s.mult_sets["St/Prov"] == {("SSB", "PA"), ("CW", "PA"), ("CW", "ON")}   # CW and phone apart
    assert s.mult_sets["DXCC"] == {("SSB", "Fed. Rep. of Germany")}


def test_arrl_160():
    e = eng("ARRL-160")
    assert e.validate_rcvd("", "DL1ABC") == []                     # DX send no section
    assert e.validate_rcvd("", "K3LR") == ["missing SEC"]          # W/VE must
    l = log(e, [("K3LR", 1820, "WPA"), ("DL1ABC", 1825, ""), ("KL7AA", 1830, "AK"), ("K3LR", 1835, "WPA")])
    s = e.score(l)
    assert s.dupes == 1 and s.points == 2 + 5 + 2                  # W/VE (Alaska too) 2, DX 5
    assert s.mult_sets["Sections"] == {("WPA",), ("AK",)} and s.mult_sets["DXCC"] == {("Fed. Rep. of Germany",)}


def test_field_day():
    e = eng("ARRL-FD")
    assert e.sent_exchange() == "2A DE" and not e.uses_rst
    assert e.validate_rcvd("3A WPA", "K3LR") == [] and e.validate_rcvd("1D DX", "DL1ABC") == []
    l = log(e, [("K3LR", 14250, "3A WPA", "SSB"), ("K3LR", 14030, "3A WPA", "CW"),
                ("K3LR", 14074, "3A WPA", "FT8"), ("K3LR", 14260, "3A WPA", "SSB"), ("W1AW", 7040, "5A CT", "CW")])
    s = e.score(l)
    assert s.dupes == 1 and s.points == 1 + 2 + 2 + 2               # phone 1, CW and digital 2
    assert s.total == s.points                                     # no multipliers


def test_needed_lists_every_section():
    from tttlog.core import needed
    e = eng("ARRL-SS-CW")
    sec = next(m for m in needed.mult_defs(e) if m["type"] == "sec")
    cols, rows = needed.need_grid(e, sec, log(e, [("W1AW", 14025, "1 A 72 CT")]), [])
    assert len(rows) == 85 and cols == ["All"]
    assert next(r for r in rows if r.value == "CT").cells["All"] == "worked"
    e10 = eng("ARRL-10")
    cols, _ = needed.need_grid(e10, needed.mult_defs(e10)[0], [], [])
    assert cols == ["SSB", "CW"]                                   # 10 m: phone and CW columns


def test_sweepstakes_in_the_window(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from test_rig import app as _app  # noqa: F401
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from PySide6.QtCore import QSettings
    import tttlog.ui.main_window as mw
    from tttlog import config
    from tttlog.core.db import Log
    import pytest
    mp = pytest.MonkeyPatch()
    ini = str(tmp_path / "s.ini")
    mp.setattr(mw, "QSettings", lambda *a: QSettings(ini, QSettings.IniFormat))
    for name in ("STATION_FILE", "MACROS_FILE", "CLUSTER_FILE", "COLORS_FILE"):
        mp.setattr(config, name, tmp_path / "cfg" / Path(getattr(config, name)).name)
    mp.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    config.save_station(ME)
    try:
        w = mw.MainWindow()
        db = tmp_path / "ss.db"; l = Log(db); l.set_meta("contest_id", "ARRL-SS-CW"); l.close()
        w.open_log(db)
        assert w.rst.isHidden() and "NR PREC CK SEC" in w.exch.placeholderText()
        assert w.sent_lbl.text() == "Sent: 1 B N3TTT 99 DE"
        w.set_freq(14030); w.call.setText("W1AW"); w.exch.setText("12 A 72 CT"); w.on_enter()
        assert len(w.qsos) == 1 and w.qsos[0].exch_sent == "1 B 99 DE" and w.qsos[0].rst_sent == ""
        assert w.sent_lbl.text() == "Sent: 2 B N3TTT 99 DE"
        w.call.setText("K3LR"); w.exch.setText("40 B 77 XX"); w.on_enter()
        assert len(w.qsos) == 1 and "bad SEC: XX" in w.banner_lbl.text()
        w.close()
    finally:
        mp.undo()
