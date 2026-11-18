"""US license privileges: the band-plan table and how the app uses it."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path

import pytest

from tttlog import config
from tttlog.core.privileges import check, inside, normalize
from test_rig import _pump, app, win  # noqa: F401  (fixtures)


@pytest.mark.parametrize("lic,khz,mode,ok", [
    ("General", 14230, "SSB", True), ("General", 14200, "SSB", False),
    ("General", 14226, "SSB", True),                         # USB: 14226-14229 is inside 14225-14350
    ("General", 3802, "SSB", False), ("General", 3805, "SSB", True),   # LSB: needs 3 kHz below
    ("General", 14074, "FT8", True), ("General", 14020, "CW", False), ("Extra", 14020, "CW", True),
    ("Extra", 3550, "SSB", False), ("Extra", 3650, "SSB", True), ("Advanced", 7130, "SSB", True),
    ("General", 7150, "SSB", False), ("General", 7180, "SSB", True),
    ("General", 10136, "FT8", True), ("General", 10130, "SSB", False),
    ("General", 5330.5, "SSB", True), ("General", 5340, "SSB", False),     # 60m channels only
    ("Technician", 14025, "CW", False), ("Technician", 7030, "CW", True),
    ("Technician", 7200, "SSB", False), ("Technician", 28400, "SSB", True),
    ("Technician", 28074, "FT8", True), ("Technician", 28600, "SSB", False),
    ("Technician", 50050, "SSB", False), ("Technician", 50125, "SSB", True),
    ("Technician", 146520, "FM", True), ("Novice", 1830, "CW", False),
    ("General", 3900, "CW", True),                          # CW is allowed in phone segments too
    ("General", 3900, "FT8", False),                        # data isn't
    ("", 7000, "SSB", True),                                # no class set: no limits
])
def test_band_plan(lic, khz, mode, ok):
    assert (check(lic, khz, mode) == "") is ok, check(lic, khz, mode)


def test_messages_and_helpers():
    assert check("G", 14200, "SSB") == "Outside General privileges: 20m phone is 14225–14350 kHz"
    assert "Too close to the edge" in check("General", 3802, "SSB")
    assert check("Technician", 14025, "CW") == "Technician class has no privileges on 20m"
    assert check("Technician", 7200, "SSB") == "Technician class has no phone privileges on 40m"
    assert normalize("g") == "General" and normalize("tech") == "Technician" and normalize("") == ""
    assert inside("General", "20m", "SSB", 14250) == 14250
    assert inside("General", "20m", "SSB", 14200) == 14226
    assert inside("General", "80m", "SSB", 3700) == 3804                   # LSB room below
    assert inside("General", "20m", "CW", 14010) == 14026
    assert inside("Technician", "40m", "SSB", 7200) is None


# ---------------------------------------------------------------- in the app
def _general(win):
    from tttlog.contests.engine import Station
    win.station = Station(call="N3TTT", cq_zone=5, license_class="General")
    config.save_station(win.station)


def test_warns_outside_and_clears(app, win):
    _general(win)
    win.set_mode("SSB")
    win.set_freq(14200)
    assert win.banner_lbl.text().startswith("⚠ Outside General privileges")
    win.set_freq(14250)
    assert win.banner_lbl.text() == ""


def test_band_buttons_stay_inside(app, win):
    _general(win)
    win.set_mode("SSB")
    win.settings.setValue("band_freq/20m/SSB", 14180)          # last there as an Extra, say
    win.band_pane.buttons["20m"].click()
    assert win.freq_khz == 14226 and not win.privilege_problem()
    win.band_pane.buttons["30m"].click()                       # no phone on 30m at all
    assert win.freq_khz == 14226 and "no SSB privileges on 30m" in win.banner_lbl.text()


def test_keyer_wont_transmit_outside(app, win):
    _general(win)
    sent = []
    win.keyer.send_voice = lambda p: sent.append(p) or True
    win.keyer.send_cw = lambda t: sent.append(t) or True
    from tttlog.core.keyer import write_wav
    write_wav(win.wav_path("cq.wav"), b"\0\0" * 800, 8000)
    win.set_mode("SSB"); win.set_freq(14200)
    win.fkey(0)
    assert not sent and win.banner_lbl.text().startswith("Not sending: Outside General")
    win.set_freq(14250); win.fkey(0)
    assert len(sent) == 1
    win.set_mode("CW"); win.set_freq(14010); win.fkey(0)
    assert len(sent) == 1


def test_operator_has_own_class(app, win):
    _general(win)
    win.set_mode("SSB"); win.set_freq(14200)
    assert win.privilege_problem()
    win.opon("K3ABC")                                          # guest: station's class until set
    assert "Operating ▸ Operator's license class" in win.banner_lbl.text()
    win.set_license_class("K3ABC", "Extra")
    assert win.license_class == "Extra" and not win.privilege_problem()
    win.opon("N3TTT")
    assert win.license_class == "General"


def test_spots_outside_are_struck_through(app, win):
    from tttlog.core.cluster import Spot
    _general(win)
    for call, khz in (("DL1ABC", 14200), ("JA1AA", 14250)):
        win.spots_pane.add_spot(Spot(call=call, freq_khz=khz, spotter="W3LPL", mode="SSB"), win.engine, win.qsos)
    win.spots_pane.refresh()
    rows = {win.spots_pane.table.item(r, 2).text(): win.spots_pane.table.item(r, 2)
            for r in range(win.spots_pane.table.rowCount())}
    assert rows["DL1ABC"].font().strikeOut() and "General" in rows["DL1ABC"].toolTip()
    assert not rows["JA1AA"].font().strikeOut()
