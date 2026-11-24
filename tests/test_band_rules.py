"""Multi-op band-change rules: CQ WW 10-minute rule, band changes per clock hour, and
asking before a spot changes band; the Needed pane's Spotted column."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone

from tttlog.contests.engine import load_rules
from tttlog.core import band_rules as br
from tttlog.core.models import QSO
from test_rig import app, win  # noqa: F401  (fixtures)

T = datetime(2026, 11, 28, 14, 0, tzinfo=timezone.utc)


def q(mins, khz, name=""):
    return QSO(call="K1AA", freq_khz=khz, mode="CW", time_utc=T + timedelta(minutes=mins), station_name=name)


def test_contest_limits():
    assert br.limits(load_rules("CQ-WW-CW"), "MS") == {"min_minutes": 10, "mult_station": True}
    assert br.limits(load_rules("CQ-WW-SSB"), "M2") == {"changes_per_hour": 8}
    assert br.limits(load_rules("ARRL-DX-SSB"), "MS") == {"changes_per_hour": 10}
    assert br.limits(load_rules("ARRL-DX-SSB"), "M2") == {"changes_per_hour": 6}
    assert br.limits(load_rules("CQ-WW-CW"), "") == {} and br.limits(load_rules("CQ-WW-CW"), "MM") == {}


def test_ten_minute_rule():
    lim = {"min_minutes": 10}
    log = [q(0, 7025), q(3, 14025), q(5, 14030)]                  # on 20 m since 14:03
    c = br.check(lim, log, "40m", T + timedelta(minutes=8))
    assert not c.ok and c.current == "20m" and "until 1413Z" in c.why and c.free_at == T + timedelta(minutes=13)
    assert br.check(lim, log, "20m", T + timedelta(minutes=8)).ok   # staying isn't a change
    c = br.check(lim, log, "40m", T + timedelta(minutes=13))
    assert c.ok and "since 1403Z" in c.status
    assert br.check(lim, [], "40m", T).ok                          # no QSOs yet


def test_changes_per_hour():
    lim = {"changes_per_hour": 2}
    log = [q(-5, 7025), q(1, 14025), q(2, 7030)]                  # 13:55 on 40, then 2 changes in the 14:00 hour
    assert br.changes_this_hour(br._bands(log), T + timedelta(minutes=3)) == 2
    c = br.check(lim, log, "20m", T + timedelta(minutes=3))
    assert not c.ok and "more at 1500Z" in c.why and "2 of 2" in c.status
    assert br.check(lim, log, "40m", T + timedelta(minutes=3)).ok
    assert br.check(lim, log, "20m", T + timedelta(minutes=61)).ok   # new clock hour


def _spot(win, call, khz, status="MULT"):
    from tttlog.core.cluster import Spot
    s = Spot(spotter="W3LPL", freq_khz=khz, call=call, comment="", time_utc=datetime.now(timezone.utc))
    s.status = status
    return s


def test_spot_on_another_band_asks(app, win, monkeypatch):
    import tttlog.ui.main_window as mw
    from tttlog.core.db import Log
    db = win.log.path.parent / "ww.db"
    l = Log(db); l.set_meta("contest_id", "CQ-WW-CW"); l.set_meta("category", "MS"); l.set_meta("tx_role", "run")
    l.close()
    win.open_log(db)
    assert win.category == "MS" and win.tx_role == "run"
    win.set_freq(14025); win.call.setText("DL1ABC"); win.exch.setText("14"); win.on_enter()
    assert len(win.qsos) == 1
    asked = []

    def answer(yes):
        def f(parent, title, text, *a):
            asked.append(text)
            return mw.QMessageBox.Yes if yes else mw.QMessageBox.No
        return f

    monkeypatch.setattr(mw.QMessageBox, "question", answer(False))
    assert win.go_to_spot(_spot(win, "JA1AA", 14030)) and not asked      # same band: no question
    assert not win.go_to_spot(_spot(win, "VK2XYZ", 7010))               # 40 m: asks, says no
    assert "NOT ALLOWED NOW" in asked[-1] and "10-minute rule" in asked[-1]
    assert win.freq_khz == 14030                                        # didn't move
    monkeypatch.setattr(mw.QMessageBox, "question", answer(True))
    assert win.go_to_spot(_spot(win, "VK2XYZ", 7010)) and win.freq_khz == 7010
    assert "10-minute rule" in win.bandrule_lbl.text() and "20m" in win.bandrule_lbl.text()  # red: go back
    win.tx_role = "mult"
    win.go_to_spot(_spot(win, "W1AW", 14040, status="Q"))
    assert "may only work new multipliers" in asked[-1]


def test_needed_pane_spotted_column(app, win):
    from tttlog.ui.needed_pane import NeededPane
    from tttlog.core.db import Log
    db = win.log.path.parent / "cwt.db"
    l = Log(db); l.set_meta("contest_id", "CWOPS-CWT"); l.close()
    win.open_log(db)
    p = win.needed_pane
    from test_run_sp import _spot_line
    win.set_mode("CW"); win.set_freq(7030)
    win._take_cluster_text(_spot_line("K3LR", 14031.0, datetime.now(timezone.utc).strftime("%H%M")))
    p.refresh()
    hdr = [p.table.horizontalHeaderItem(c).text() for c in range(p.table.columnCount())]
    assert hdr[-1] == "Spotted"
    row = next(r for r in range(p.table.rowCount()) if p.table.item(r, 0).text() == "K3LR")
    assert p.table.item(row, p.table.columnCount() - 1).text() == "20m 14031.0 K3LR"
    got = []
    p.spotActivated.connect(got.append)
    p.table.cellClicked.emit(row, p.table.columnCount() - 1)       # a single click goes
    assert got and got[0].call == "K3LR"
    assert isinstance(p, NeededPane)
