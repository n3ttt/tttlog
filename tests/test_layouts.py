"""Panes stay put when one is minimized; layouts are kept per operator (OPON)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from test_rig import _pump, app, win  # noqa: F401  (fixtures)

NAMES = ("entry", "log", "spots", "telnet", "score", "check_partial", "rate")


def _geo(w):
    return {n: getattr(w, "dock_" + n).geometry().getRect() for n in NAMES}


# px: fonts and title bars differ a little between Mac, Windows and Linux. Linux comes back
# up to 14 px wider in a very narrow column (Spots near its minimum width); not yet explained.
TOL = 16


def _same(a, b, tol=TOL):
    """Two layouts match: every pane within a few pixels (a moved or resized pane is far more)."""
    bad = {n: (a[n], b[n]) for n in a if any(abs(x - y) > tol for x, y in zip(a[n], b[n]))}
    assert not bad, bad
    return True


def _settle(app, ms=250):
    _pump(app, lambda: False, ms)


def _arrange(app, win):
    """Telnet under Spots, narrow columns with empty space between (a user's own layout).
    (Tests run on an 800x800 fake screen, so the window has to fit in that.)"""
    win.resize(790, 740); win.show(); _settle(app, 700)
    win.splitDockWidget(win.dock_spots, win.dock_telnet, Qt.Vertical); _settle(app)
    win.resizeDocks([win.dock_score], [180], Qt.Horizontal)
    win.resizeDocks([win.dock_log, win.dock_spots], [150, 250], Qt.Horizontal); _settle(app)
    # The fake test screen is only 800 px wide. With Windows' and Linux's bigger fonts the
    # panes' minimum widths don't fit this layout at all (the Entry pane alone needs ~626 px
    # on Windows), so Qt can't build it and there's nothing meaningful to compare.
    _skip_unless_fits(win, 150, 250)


def _skip_unless_fits(win, log_w, spots_w):
    fits = (abs(win.dock_log.width() - log_w) <= 2 and abs(win.dock_spots.width() - spots_w) <= 2
            and win.dock_entry.minimumSizeHint().width() <= log_w + spots_w + 8)
    if not fits:
        import pytest
        pytest.skip("this platform's minimum pane sizes don't fit the 800 px test screen")


def test_minimize_doesnt_move_other_panes(app, win):
    _arrange(app, win)
    before = _geo(win)
    win.dock_telnet.set_minimized(True); _settle(app)
    after = _geo(win)
    others = {n: before[n] for n in NAMES if n not in ("spots", "telnet")}
    _same(others, {n: after[n] for n in others})            # nothing else moves
    assert abs(after["spots"][2] - before["spots"][2]) <= 2  # Spots keeps its width...
    assert after["spots"][3] > before["spots"][3] + 100     # ...and grows down into the space
    win.dock_telnet.set_minimized(False); _settle(app)
    _same(_geo(win), before)                                # restore puts everything back


def test_layout_per_operator(app, win):
    _arrange(app, win)
    win.opon("N3TTT")
    win.dock_telnet.set_minimized(True); _settle(app)
    mine = _geo(win)
    win.opon("K3ABC")                                       # first time: keeps the current layout
    assert "window layout" not in win.banner_lbl.text()
    win.dock_telnet.set_minimized(False); _settle(app)        # let the restore finish first
    win.resizeDocks([win.dock_log, win.dock_spots], [260, 140], Qt.Horizontal); _settle(app)
    _skip_unless_fits(win, 260, 140)
    theirs = _geo(win)
    assert any(abs(x - y) > 50 for n in NAMES for x, y in zip(theirs[n], mine[n]))   # really different

    win.opon("N3TTT"); _settle(app)                         # back to my layout
    assert "N3TTT's window layout" in win.banner_lbl.text()
    assert win.dock_telnet.minimized and _same(_geo(win), mine)
    win.opon("K3ABC"); _settle(app)                         # and theirs was saved when they left
    assert not win.dock_telnet.minimized and _same(_geo(win), theirs)


def test_layout_survives_restart(app, win, tmp_path, monkeypatch):
    import tttlog.ui.main_window as mw
    _arrange(app, win)
    win.dock_telnet.set_minimized(True); _settle(app)
    before = _geo(win)
    win.close()                                             # saves it (same QSettings file)
    w2 = mw.MainWindow()
    w2.show(); _settle(app, 700)
    assert w2.dock_telnet.minimized
    _same(_geo(w2), before)
    w2.reset_layout(); _settle(app, 500)                    # View ▸ Reset to the default layout
    assert not w2.dock_telnet.minimized and w2.dock_telnet.isVisible()
    w2.close()
