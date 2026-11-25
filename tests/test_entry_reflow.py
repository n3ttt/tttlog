"""The Entry pane rearranges itself to its size; the radio refresh button reconnects."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_rig import _pump, app, win  # noqa: F401  (fixtures)


def _rows(win, widget):
    g = win._ent_grid
    return g.getItemPosition(g.indexOf(widget))[0]


def test_entry_reflows_with_width(app, win):  # noqa: F811
    for w, shape, cols in [(900, "wide", 6), (450, "medium", 4), (300, "narrow", 3), (200, "narrow", 2)]:
        win._reflow_entry(w, 320)
        assert win._entry_shape == shape and win._fk_cols == cols, w
        if shape == "wide":
            assert _rows(win, win.call) == _rows(win, win.exch)        # one line
        else:
            assert _rows(win, win.exch) > _rows(win, win.call)         # exchange under the call
        positions = {win._fk_grid.getItemPosition(win._fk_grid.indexOf(b))[:2] for b in win.fbuttons}
        assert len(positions) == 12                                     # every F-key has its own cell
    win._reflow_entry(900, 320)
    small = win._entry_pt
    win._reflow_entry(1400, 520)
    assert win._entry_pt > small                                       # bigger pane, bigger entry text
    win._reflow_entry(900, 320)
    assert win._entry_pt == small


def test_real_window_reflows(app, win):  # noqa: F811
    """The Entry pane's own size drives it (window shown, panes laid out)."""
    win.show()
    win.reset_layout()
    win.resize(1400, 900)
    assert _pump(app, lambda: win._entry_box.width() > 540 and win._entry_shape == "wide")
    win.resize(700, 700)                     # panes scale with the window
    assert _pump(app, lambda: win._entry_box.width() < 540 and win._entry_shape != "wide")
    assert win._fk_cols < 6


def test_typing_doesnt_reflow(app, win):  # noqa: F811
    win.show()
    win._reflow_entry(450, 320)
    _pump(app, lambda: False, 300)            # let the first layout settle (slow on CI Macs)
    before = (win._entry_shape, win._fk_cols, win._entry_pt, win.call.geometry())
    for ch in "DL1ABC":
        win.call.setText(win.call.text() + ch); win._on_call_edited(win.call.text())
        app.processEvents()
    assert (win._entry_shape, win._fk_cols, win._entry_pt, win.call.geometry()) == before


def test_radio_refresh(app, win):  # noqa: F811
    from tests.test_civ import FakeIcom, _cfg
    win.refresh_radio()
    assert "isn't set up" in win.banner_lbl.text()
    radio = FakeIcom()
    win.rig_cfg = _cfg(radio, control=False)
    win.rig.start(win.rig_cfg)
    assert _pump(app, lambda: win.rig.is_connected())
    assert win.rig_refresh_btn.isVisibleTo(win)
    radio.freq_hz = 7_030_000
    for c in radio.clients:                       # the radio drops off (power, USB)
        c.abort()
    win.rig_refresh_btn.click()
    assert "Reconnecting" in win.banner_lbl.text()
    assert _pump(app, lambda: win.rig.is_connected() and win.freq_khz == 7030.0)
    win.rig.stop()
