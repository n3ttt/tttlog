"""Bandmap: spots on a frequency scale, the radio marker, click to go, and stepping
up and down the band (Ctrl+Down / Ctrl+Up) for S&P."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect

from tttlog.ui.bandmap_pane import layout_labels, tick_step
from test_rig import _pump, app, win  # noqa: F401  (fixtures)
from test_run_sp import _spot_line


def test_label_layout_and_ticks():
    assert layout_labels([100, 104, 108, 200], 0, 16) == [92, 108, 124, 192]   # close ones stack, others stay
    assert tick_step(8.0) == (1, 5) and tick_step(60.0) == (0.5, 1) and tick_step(2.0) == (5, 25)


def _spots(win):
    win.set_mode("CW"); win.set_freq(14030.0)
    for c, f in [("JA1AA", 14025.0), ("DL1ABC", 14036.0), ("VK2XYZ", 14041.0), ("ZS6ABC", 21010.0)]:
        win._take_cluster_text(_spot_line(c, f))


def test_bandmap_shows_the_band(app, win):
    win.resize(1280, 800); win.show(); _pump(app, lambda: False, 300)
    _spots(win)
    bm = win.bandmap
    _pump(app, lambda: False, 400)
    assert bm.band == "20m" and bm.radio_khz == 14030.0
    assert [s.call for s in sorted(bm.visible_spots(), key=lambda s: s.freq_khz)] == ["JA1AA", "DL1ABC", "VK2XYZ"]
    assert _pump(app, lambda: "20m · 3 mults" in bm.summary.text(), 3000), bm.summary.text()   # slow CI Macs
    bm.canvas.repaint()
    calls = [s.call for _r, s in bm.canvas._hits]
    assert calls == ["JA1AA", "DL1ABC", "VK2XYZ"]
    r, s = bm.canvas._hits[1]                                 # click DL1ABC's label
    bm.canvas.spotClicked.emit(s)
    assert win.freq_khz == 14036.0 and win.call.text() == "DL1ABC"
    bm.band_box.setCurrentText("15m")                         # look at another band
    assert [s.call for s in bm.visible_spots()] == ["ZS6ABC"]
    z = bm.ppk
    bm.zoom(1)
    assert bm.ppk > z


def test_step_up_and_down_the_band(app, win):
    _spots(win)
    win.next_spot(+1); assert win.call.text() == "DL1ABC" and win.freq_khz == 14036.0
    win.next_spot(+1); assert win.call.text() == "VK2XYZ"
    win.next_spot(+1); assert "No more needed spots above" in win.banner_lbl.text()
    win.next_spot(-1); assert win.call.text() == "DL1ABC"
    win.next_spot(-1); assert win.call.text() == "JA1AA"
    assert win.shortcut_actions["spot_higher"].shortcut().toString() == "Ctrl+Down"


def test_new_pane_finds_free_space(app, win):
    win.resize(1280, 800); win.show(); _pump(app, lambda: False, 300)
    c = win.canvas
    r = c.find_free(4, 1, prefer=QRect(25, 0, 4, 6))
    assert (r.x(), r.y()) != (25, 0)                          # Bandmap is there: somewhere else
    from tttlog.ui.docks import overlaps
    assert not any(overlaps(QRect(r.x(), r.y(), 4, 1), c.occupied(p)) for p in c.on_grid())
