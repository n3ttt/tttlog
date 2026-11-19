"""Panes on a grid: move and resize with snapping and pushing, minimize, pop out and
put back, drop where you want, and layouts kept per operator. Positions are checked
in grid cells, so these behave the same on Mac, Windows and Linux."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent

from tttlog.ui.docks import COLS, push_down
from test_rig import _pump, app, win  # noqa: F401  (fixtures)


def _settle(app, ms=200):
    _pump(app, lambda: False, ms)


def _cells(w):
    return {p.objectName()[5:]: p.grid.getRect() for p in w.panes}


def _show(app, win):
    win.resize(1280, 800); win.show(); _settle(app, 400)
    win.reset_layout(); _settle(app)
    return win.canvas


def _cell_px(c, x, y):
    """Global point of the top-left of grid cell (x, y), a little inside it."""
    r = c.to_px(QRect(x, y, 1, 1))
    return c.mapToGlobal(r.topLeft() + QPoint(3, 3))


def test_push_down():
    r = {"a": QRect(0, 0, 4, 4), "b": QRect(2, 2, 4, 4), "c": QRect(2, 6, 4, 2), "d": QRect(10, 0, 2, 2)}
    out = push_down(r, "a")
    assert out["a"] == r["a"]
    assert out["b"].y() == 4                        # pushed just below a
    assert out["c"].y() == 8                        # ...and c below b in turn
    assert out["d"] == r["d"]                       # not in the way: untouched


class _Grid:
    """A grid on its own (no main window): panes in a 1000 x 600 window, so there's a
    known amount of room (22 rows)."""

    def __init__(self, app, layout):
        from PySide6.QtWidgets import QLabel, QScrollArea
        from tttlog.ui.docks import GridCanvas, Pane
        self.app = app
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.c = GridCanvas(); self.scroll.setWidget(self.c)
        self.p = {}
        for name, r in layout.items():
            pane = Pane(name, QLabel(name), self.c)
            self.c.add(pane, QRect(*r))
            self.p[name] = pane
        self.scroll.resize(1000, 600); self.scroll.show(); _settle(app)
        self.c.relayout(); _settle(app)

    def cells(self):
        return {n: p.grid.getRect() for n, p in self.p.items()}

    def drag(self, name, dcols=0, drows=0, resize=False):
        """Drag a pane's title bar (or its corner grip) by whole cells."""
        c, pane = self.c, self.p[name]
        start = (pane.grip if resize else pane.bar).mapToGlobal(QPoint(6, 6))
        d = QPoint(round(dcols * (c.col_w() + 4)), drows * (22 + 4))
        (c.begin_resize if resize else c.begin_move)(pane, start)
        (c.drag_resize if resize else c.drag_move)(start + d)
        _settle(self.app, 50)
        return start, d

    def drop(self):
        self.c.end_drag(); _settle(self.app)

    def close(self):
        self.scroll.close()


def test_move_snaps_and_pushes_only_whats_in_the_way(app):
    g = _Grid(app, {"A": (0, 0, 8, 6), "B": (10, 0, 8, 6), "C": (10, 8, 8, 4), "D": (30, 0, 8, 6)})
    assert g.c.rows() == 22
    start, _ = g.drag("A", dcols=10)                       # onto B
    assert g.c.ghost.isVisible()
    assert g.cells()["B"][1] == 6 and g.cells()["C"][1] >= 12   # B slides down under A, C under B
    g.c.drag_move(start); _settle(app, 50)                 # dragged back: they slide back (fluid)
    assert g.cells()["B"] == (10, 0, 8, 6) and g.cells()["C"] == (10, 8, 8, 4)
    g.drag("A", dcols=10); g.drop()
    assert g.cells()["A"] == (10, 0, 8, 6) and g.cells()["D"] == (30, 0, 8, 6)   # D not in the way
    assert not g.c.ghost.isVisible()
    g.close()


def test_pushed_pane_shrinks_at_the_bottom(app):
    g = _Grid(app, {"A": (0, 0, 8, 10), "B": (10, 6, 8, 12), "C": (10, 18, 8, 4)})
    g.drag("A", dcols=10); g.drop()                        # A (10 rows) onto B: B must fit in 22 rows
    cells = g.cells()
    assert cells["A"] == (10, 0, 8, 10)
    b, cc = cells["B"], cells["C"]
    assert b[1] == 10 and b[1] + b[3] <= cc[1]             # B moved down and got shorter...
    assert cc[1] + cc[3] <= 22                             # ...and nothing went off the bottom
    g.close()


def test_move_refused_when_nothing_can_fit(app):
    g = _Grid(app, {"A": (0, 0, 8, 21), "B": (10, 4, 8, 18)})
    g.drag("A", dcols=10); g.drop()                        # 1 row left below A: B can't fit (min 2)
    assert g.cells() == {"A": (0, 0, 8, 21), "B": (10, 4, 8, 18)}   # so A stays where it was
    g.close()


def test_hard_stop_at_the_edges(app):
    g = _Grid(app, {"A": (0, 0, 8, 6)})
    g.drag("A", dcols=100, drows=100); g.drop()            # way off the bottom right
    a = g.cells()["A"]
    assert a[0] + a[2] == 48 and a[1] + a[3] == 22         # stopped at the corner, still on screen
    assert g.p["A"].geometry().bottom() <= g.scroll.viewport().height()
    g.drag("A", dcols=-100, drows=-100); g.drop()
    assert g.cells()["A"][:2] == (0, 0)
    g.drag("A", dcols=100, drows=100, resize=True); g.drop()   # resize stops at the edges too
    assert g.cells()["A"] == (0, 0, 48, 22)
    g.close()


def test_resize_pushes_and_snaps(app):
    g = _Grid(app, {"A": (0, 0, 8, 6), "B": (10, 0, 8, 6)})
    g.drag("A", dcols=3, resize=True); g.drop()
    assert g.cells()["A"] == (0, 0, 11, 6)
    assert g.cells()["B"][1] == 6                          # was beside it: pushed down
    g.close()


def test_minimize_moves_nothing_else(app, win):
    c = _show(app, win)
    before = _cells(win)
    win.dock_spots.set_minimized(True); _settle(app)
    assert _cells(win) == before                                     # cells unchanged...
    assert win.dock_spots.height() < 40                              # ...it just rolls up
    win.dock_spots.set_minimized(False); _settle(app)
    assert _cells(win) == before


def test_pop_out_and_put_back_where_it_was(app, win):
    c = _show(app, win)
    tel = win.dock_telnet
    home = tel.grid.getRect()
    tel.setFloating(True); _settle(app)
    assert tel.isFloating() and tel.isWindow()
    assert tel.windowFlags() & Qt.WindowMinimizeButtonHint
    # meanwhile Spots is stretched down into Telnet's spot
    win.dock_spots.grid.setHeight(win.dock_spots.grid.height() + 4); c.relayout()
    tel.toggle_floating(); _settle(app)                               # ⇲
    assert not tel.isFloating() and tel.grid.getRect() == home       # exactly where it was...
    sp = win.dock_spots.grid
    assert sp.y() + sp.height() <= home[1] or sp.y() >= home[1] + home[3] or \
        sp.x() + sp.width() <= home[0] or sp.x() >= home[0] + home[2]  # ...with no overlap


def test_drop_popped_out_pane_where_you_want(app, win):
    c = _show(app, win)
    tel = win.dock_telnet
    tel.setFloating(True); _settle(app)
    bar = tel.bar

    def send(kind, gpos, buttons):
        ev = QMouseEvent(kind, QPointF(bar.mapFromGlobal(gpos)), QPointF(gpos), Qt.LeftButton, buttons,
                         Qt.NoModifier)
        app.sendEvent(bar, ev)

    target = _cell_px(c, 3, 2) + QPoint(int(c.col_w()), 8)          # cursor on its title, near the left
    send(QEvent.MouseButtonPress, bar.mapToGlobal(QPoint(30, 8)), Qt.LeftButton)
    send(QEvent.MouseMove, target, Qt.LeftButton)
    assert c.ghost.isVisible()                                       # shows where it will land
    send(QEvent.MouseButtonRelease, target, Qt.NoButton)
    _settle(app)
    assert not tel.isFloating() and tel.grid.topLeft() == QPoint(3, 2)
    e = win.dock_entry.grid                                          # what was there got bumped down
    assert e.y() >= tel.grid.y() + tel.grid.height() or e.x() >= tel.grid.x() + tel.grid.width()

    tel.setFloating(True); _settle(app)
    assert c.drop_floating(tel, c.mapToGlobal(QPoint(-200, -200))) is False
    assert tel.isFloating()                                          # dropped off the window: stays out
    tel.setFloating(False)


def test_drag_by_title_bar_on_the_grid(app, win):
    c = _show(app, win)
    rate, bar = win.dock_rate, win.dock_rate.bar

    def send(kind, gpos, buttons):
        ev = QMouseEvent(kind, QPointF(bar.mapFromGlobal(gpos)), QPointF(gpos), Qt.LeftButton, buttons,
                         Qt.NoModifier)
        app.sendEvent(bar, ev)

    start = bar.mapToGlobal(QPoint(30, 8))
    down = QPoint(0, 3 * (22 + 4))                                    # three rows down
    send(QEvent.MouseButtonPress, start, Qt.LeftButton)
    send(QEvent.MouseMove, start + down, Qt.LeftButton)
    send(QEvent.MouseButtonRelease, start + down, Qt.NoButton)
    _settle(app)
    assert rate.grid.y() == 14 + 3


def test_close_and_reopen_comes_back_in_place(app, win):
    _show(app, win)
    sc = win.dock_score
    home = sc.grid.getRect()
    sc.close(); _settle(app)
    assert not sc.isVisible() and not sc.toggleViewAction().isChecked()
    sc.toggleViewAction().setChecked(True); _settle(app)
    assert sc.isVisible() and sc.grid.getRect() == home


def test_layout_per_operator(app, win):
    c = _show(app, win)
    win.opon("N3TTT")
    win.dock_telnet.set_minimized(True)
    c.place(win.dock_log, QRect(2, 12, 5, 16)); _settle(app)
    mine = _cells(win)
    win.opon("K3ABC")                                                # first time: keeps the current layout
    assert "window layout" not in win.banner_lbl.text()
    win.dock_telnet.set_minimized(False)
    c.place(win.dock_log, QRect(2, 10, 10, 10)); _settle(app)
    theirs = _cells(win)
    assert theirs != mine

    win.opon("N3TTT"); _settle(app)                                  # back to my layout
    assert "N3TTT's window layout" in win.banner_lbl.text()
    assert win.dock_telnet.minimized and _cells(win) == mine
    win.opon("K3ABC"); _settle(app)                                  # and theirs was saved when they left
    assert not win.dock_telnet.minimized and _cells(win) == theirs


def test_layout_survives_restart(app, win):
    import tttlog.ui.main_window as mw
    c = _show(app, win)
    win.dock_telnet.set_minimized(True)
    c.place(win.dock_rate, QRect(10, 30, 6, 7))
    win.dock_score.close()
    before = _cells(win)
    win.close()                                                      # saves it (same settings file)
    w2 = mw.MainWindow()
    w2.show(); _settle(app, 300)
    assert _cells(w2) == before
    assert w2.dock_telnet.minimized and not w2.dock_score.shown
    w2.reset_layout(); _settle(app)                                  # View ▸ Reset to the default layout
    assert not w2.dock_telnet.minimized and w2.dock_score.shown
    w2.close()


def test_layout_autosaves_without_closing(app, win):
    """Moved, rolled up or closed: saved within a couple of seconds, so a crash or a
    power cut doesn't lose it."""
    import tttlog.ui.main_window as mw
    c = _show(app, win)
    win.opon("N3TTT")
    c.place(win.dock_rate, QRect(10, 30, 6, 7))
    win.dock_telnet.set_minimized(True)
    win.dock_score.close()
    before = _cells(win)
    _settle(app, 1800)                                   # no close: the autosave has to do it
    w2 = mw.MainWindow()
    w2.show(); _settle(app, 300)
    assert _cells(w2) == before
    assert w2.dock_telnet.minimized and not w2.dock_score.shown
    w2.close()
