"""HamQTH lookups with a fake server (same XML HamQTH sends)."""
import time

import pytest

from tttlog.core import callbook
from tttlog.core.callbook import CallbookError, HamQTH, location, looks_like_call, parse_lookup

HEAD = b'<?xml version="1.0"?><HamQTH version="2.8" xmlns="https://www.hamqth.com">'
SESSION = HEAD + b"<session><session_id>sid-1</session_id></session></HamQTH>"
BAD_LOGIN = HEAD + b"<session><error>Wrong user name or password</error></session></HamQTH>"
EXPIRED = HEAD + b"<session><error>Session does not exist or expired</error></session></HamQTH>"
NOT_FOUND = HEAD + b"<session><error>Callsign not found</error></session></HamQTH>"
OK2CQR = HEAD + (b"<search><callsign>ok2cqr</callsign><nick>Petr</nick><qth>Neratovice</qth>"
                 b"<country>Czech Republic</country><grid>jo70ga</grid><latitude>50.25</latitude>"
                 b"<longitude>14.51</longitude></search></HamQTH>")
DL1ABC = HEAD + (b"<search><callsign>dl1abc</callsign><nick>Hans</nick><grid>JO31</grid>"
                 b"</search></HamQTH>")
NOGRID = HEAD + (b"<search><callsign>w6xx</callsign><nick>Al</nick><us_state>CA</us_state>"
                 b"<latitude>37.4</latitude><longitude>-122.1</longitude></search></HamQTH>")


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class Fake:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, params):
        self.calls.append(params)
        key = "login" if "u" in params else params["callsign"]
        a = self.answers[key]
        return a.pop(0) if isinstance(a, list) else a


def test_parse_and_location():
    rec, err = parse_lookup(OK2CQR)
    assert err == "" and rec["call"] == "OK2CQR" and rec["grid"] == "JO70GA" and rec["name"] == "Petr"
    (lat, lon), what = location(rec)
    assert what == "JO70GA" and 50.0 < lat < 50.05 and 14.5 < lon < 14.6    # grid square wins
    rec, _ = parse_lookup(NOGRID)
    assert location(rec) == ((37.4, -122.1), "lat/lon") and rec["state"] == "CA"
    assert parse_lookup(NOT_FOUND) == (None, "Callsign not found")
    assert location(None) is None and location({"call": "X1X", "grid": ""}) is None


def test_lookup_caches_and_relogs(tmp_path):
    fake = Fake({"login": SESSION, "OK2CQR": [EXPIRED, OK2CQR], "W6XX": NOGRID, "N0NE": NOT_FOUND})
    cb = HamQTH("n3ttt", "pw", tmp_path / "cache.json", fetch=fake)
    assert cb.lookup("ok2cqr")["grid"] == "JO70GA"            # expired session -> logged in again
    assert sum("u" in c for c in fake.calls) == 2
    assert fake.calls[-1] == {"id": "sid-1", "callsign": "OK2CQR", "prg": "tttlog"}
    n = len(fake.calls)
    assert cb.lookup("OK2CQR")["grid"] == "JO70GA" and len(fake.calls) == n   # cached
    assert cb.lookup("N0NE") is None and cb.cached("N0NE") == {}             # remembered as unknown
    # the cache survives a restart
    again = HamQTH("n3ttt", "pw", tmp_path / "cache.json", fetch=Fake({}))
    assert again.cached("OK2CQR")["grid"] == "JO70GA"
    # and expires
    again.cache["OK2CQR"]["t"] = time.time() - 31 * 86400
    assert again.cached("OK2CQR") is None


def test_bad_login_and_network_errors():
    with pytest.raises(CallbookError, match="Wrong user name"):
        HamQTH("n3ttt", "bad", fetch=Fake({"login": BAD_LOGIN})).lookup("OK2CQR")

    def down(params):
        raise OSError("no route to host")
    with pytest.raises(CallbookError, match="can't reach HamQTH"):
        HamQTH("n3ttt", "pw", fetch=down).test_login()


def test_looks_like_call():
    assert all(map(looks_like_call, ["N3TTT", "DL1ABC", "K1A", "VP2E/N3TTT", "N3TTT/P", "3DA0RU"]))
    assert not any(map(looks_like_call, ["N3", "14025", "DL", "ABC", ""]))


def test_window_aims_at_the_grid(app, tmp_path, monkeypatch):
    import os
    from PySide6.QtCore import QSettings
    from tttlog import config
    from tttlog.contests.engine import Station
    from tttlog.core.db import Log
    import tttlog.ui.main_window as mw
    for name in ("STATION_FILE", "MACROS_FILE", "CLUSTER_FILE", "COLORS_FILE", "CALLBOOK_FILE"):
        monkeypatch.setattr(config, name, tmp_path / "cfg" / getattr(config, name).name)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(mw, "QSettings", lambda *a: QSettings(str(tmp_path / "w.ini"), QSettings.IniFormat))
    config.save_station(Station(call="N3TTT", state="DE", cq_zone=5, grid="FM29"))
    w = mw.MainWindow()
    db = tmp_path / "c.db"
    l = Log(db); l.set_meta("contest_id", "ARRL-DX-SSB"); l.close()
    w.open_log(db)

    w.call.setText("W6XX"); w._on_call_edited("W6XX")
    centre = w.beam_to("W6XX")
    assert "United States centre" in w.beam_lbl.text()       # no callbook: country centre

    fake = Fake({"login": SESSION, "W6XX": NOGRID, "DL1ABC": DL1ABC, "DK9XX": NOT_FOUND, "DL2BAD": NOT_FOUND})
    w.callbook = HamQTH("n3ttt", "pw", fetch=fake)
    w._on_call_edited("W6XX")
    assert _pump(app, lambda: "lat/lon (HamQTH)" in w.beam_lbl.text())
    precise = w.beam_to("W6XX")
    assert abs(precise[0] - centre[0]) > 10                   # California vs middle of the US
    assert 270 < precise[0] < 300                             # DE -> CA is about west-northwest

    w.call.setText("DL1ABC"); w._on_call_edited("DL1ABC")
    assert _pump(app, lambda: "JO31 (HamQTH)" in w.beam_lbl.text())
    w.call.setText("DK9XX"); w._on_call_edited("DK9XX")       # unknown to HamQTH: country centre
    assert _pump(app, lambda: w.callbook.cached("DK9XX") == {})
    assert "Germany centre" in w.beam_lbl.text()

    w.callbook = HamQTH("n3ttt", "bad", fetch=Fake({"login": BAD_LOGIN}))
    w.call.setText("DL2BAD"); w._on_call_edited("DL2BAD")
    assert _pump(app, lambda: "HamQTH lookup" in w.banner_lbl.text())
    w.close()


def _pump(app, cond, secs=3.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return cond()
