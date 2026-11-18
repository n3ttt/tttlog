"""Chasing mults: Ctrl+G steps through needed spots, the band-only setting, and the
Needed Spots pane's filters."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone

from tttlog.core.cluster import Spot
from test_rig import _pump, app, win  # noqa: F401  (fixtures)
from test_run_sp import _spot_line

T0 = datetime.now(timezone.utc)


def _feed(win, *spots):
    for call, khz, mins_ago in spots:
        win._take_cluster_text(_spot_line(call, khz, (T0 - timedelta(minutes=mins_ago)).strftime("%H%M")))


def test_repeat_key_steps_through_needed_spots(app, win):
    win.set_mode("CW"); win.set_freq(14030)
    _feed(win, ("JA1AA", 14025.0, 3), ("DL1ABC", 14010.0, 2), ("VK2XYZ", 21010.0, 1))
    order = [s.call for s in win.chase_list()]
    assert order == ["VK2XYZ", "DL1ABC", "JA1AA"]           # newest first
    win.go_to_next_needed(); assert win.call.text() == "VK2XYZ"
    win.go_to_next_needed(); assert win.call.text() == "DL1ABC"
    win.go_to_next_needed(); assert win.call.text() == "JA1AA"
    assert "3 of 3" in win.banner_lbl.text()
    win.go_to_next_needed(); assert win.call.text() == "VK2XYZ"     # wraps around
    win.set_freq(14200)                                     # moved away: starts again from the newest
    win.go_to_next_needed(); assert win.call.text() == "VK2XYZ"


def test_band_only(app, win):
    win.set_mode("CW"); win.set_freq(14030)
    win.set_chase_band_only(True)
    assert win.cluster_cfg["chase_band_only"] and win.chase_band_act.isChecked()
    _feed(win, ("JA1AA", 14025.0, 2), ("VK2XYZ", 21010.0, 1))
    assert [s.call for s in win.chase_list()] == ["JA1AA"]
    assert win.alerts.count() == 1 and "JA1AA" in win.alerts.item(0).text()   # 15m not announced
    win.set_chase_band_only(False)
    _feed(win, ("ZS6ABC", 21020.0, 0))
    assert win.alerts.count() == 2
    win.set_chase_band_only(True)                           # back on: the 15m one is hidden
    assert win.alerts.item(0).isHidden() and not win.alerts.item(1).isHidden()
    win.set_freq(21015)                                     # ...and shows again on 15m
    assert not win.alerts.item(0).isHidden() and win.alerts.item(1).isHidden()
    win.set_chase_band_only(False)


def test_needed_spots_pane_filters(app):
    from tttlog.ui.needed_spots_pane import NeededSpotsPane
    colors = {"spot_mult": {"color": "#bfe"}, "spot_q": {"color": "#ffd"}}
    p = NeededSpotsPane(colors)

    class Eng:
        rules = {"bands": ["40m", "20m", "15m"],
                 "mults": [{"type": "cq_zone", "label": "Zones"}, {"type": "dxcc", "label": "Countries"}]}
    p.set_engine(Eng())
    assert not p.mult_box.isHidden() and p.mult_box.count() == 3

    def spot(call, khz, status, mults=(), keys=()):
        s = Spot(call=call, freq_khz=khz, spotter="W3LPL", mode="CW", time_utc=T0)
        s.status, s.mults, s.keys = status, list(mults), list(keys)
        return s
    spots = [spot("JA1AA", 14025, "MULT", ["Zones", "Countries"], [("Zones", ("20m", 25)), ("Countries", ("20m", "Japan"))]),
             spot("DL1ABC", 14030, "MULT", ["Countries"], [("Countries", ("20m", "Germany"))]),
             spot("W1AW", 14040, "Q"), spot("VK2XYZ", 21010, "MULT", ["Zones"], [("Zones", ("15m", 30))]),
             spot("K3LR", 14050, "DUPE")]
    p.update_spots(spots, "20m"); p.refresh()
    calls = lambda: [p.table.item(r, 2).text() for r in range(p.table.rowCount())]
    assert calls() == ["JA1AA", "DL1ABC", "VK2XYZ", "W1AW"]          # mults first, no dupes
    assert p.table.item(0, 5).text() == "zone 25, Japan" and p.table.item(3, 5).text() == "new Q"
    p.band_box.setCurrentText("Band I'm on")
    assert calls() == ["JA1AA", "DL1ABC", "W1AW"]
    p.band_box.setCurrentText("15m")
    assert calls() == ["VK2XYZ"]
    p.band_box.setCurrentIndex(0)
    p.kind_box.setCurrentIndex(p.kind_box.findData("q"))
    assert calls() == ["W1AW"]
    p.kind_box.setCurrentIndex(p.kind_box.findData("both"))
    p.mult_box.setCurrentIndex(p.mult_box.findData("Zones"))
    assert calls() == ["JA1AA", "VK2XYZ"]
    assert "2 mults" in p.summary.text()


def test_new_pane_joins_an_older_saved_layout(app, win):
    win.resize(1280, 800); win.show(); _pump(app, lambda: False, 300)
    old = {k: v for k, v in win.canvas.to_dict().items() if k != "dock_Needed Spots"}
    win.canvas.from_dict(old); _pump(app, lambda: False, 200)
    ns = win.dock_needed_spots
    assert ns.minimized and ns.shown                        # rolled up, not on top of anything
    from tttlog.ui.docks import overlaps
    mine = win.canvas.occupied(ns)
    assert not any(overlaps(mine, win.canvas.occupied(p)) for p in win.canvas.on_grid() if p is not ns)
