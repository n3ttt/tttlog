"""Panes on a grid (like a web dashboard).

The main window is a grid: columns scale with the window's width, rows are a
fixed height. Each pane is a tile on it:

* drag its title bar to move it; it snaps to the grid, and any pane it would
  overlap slides down out of the way while you drag (nothing else moves);
* drag the corner grip to resize it, with the same pushing;
* –  rolls it up to its title bar (nothing else moves); +  unrolls it;
* ⧉  pops it out into its own window (system minimize / zoom / close); ⇲ (or
  double-clicking the title) puts it back exactly where it was on the grid,
  bumping anything now in the way; or drag it by this title strip and drop it
  on the grid where you want it;
* ×  closes it (View menu brings it back where it was).

Positions are in grid cells, so a saved layout comes back the same on every
platform and screen size.
"""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

FLOAT_FLAGS = (Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint |
               Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint |
               Qt.WindowCloseButtonHint)

COLS = 48            # grid columns across the window (their width follows the window)
ROW_H = 22           # px per grid row
GAP = 4              # px between tiles
MIN_W, MIN_H = 2, 2  # smallest tile, in cells
ANIM_MS = 120

# Smallest a pane's contents may be squeezed to. Below what they need, they
# scroll instead of forcing the whole window to be bigger than a small screen.
PANE_MIN = QSize(60, 30)


def _shrinkable(widget: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidget(widget)
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.NoFrame)
    sc.setMinimumSize(PANE_MIN)
    return sc


def overlaps(a: QRect, b: QRect) -> bool:
    return a.x() < b.x() + b.width() and b.x() < a.x() + a.width() and \
        a.y() < b.y() + b.height() and b.y() < a.y() + a.height()


def push_down(rects: dict, moved: str, max_rows: int | None = None, fixed=()) -> dict | None:
    """rects: name -> QRect in cells. Move every rect that overlaps `moved` (and,
    in turn, anything those overlap) straight down just far enough. `moved` stays.

    With max_rows (the bottom of the window), a pushed rect that would go past it
    gets shorter instead, as short as needed (down to MIN_H) to leave room for what
    it pushes in turn; `fixed` ones (rolled up) can't shrink. If there's no way to
    fit everything, returns None: that move isn't allowed."""
    out = {n: QRect(r) for n, r in rects.items()}
    if max_rows is None:
        queue = [moved]
        while queue:
            a = queue.pop(0)
            for n, r in out.items():
                if n in (a, moved) or not overlaps(out[a], r):
                    continue
                r.moveTop(out[a].y() + out[a].height())
                queue.append(n)
        return out

    def settle(name: str, cur: dict) -> dict | None:
        """Push everything `name` now overlaps below it, recursively; None if it can't fit."""
        for n in list(cur):
            if n in (name, moved) or not overlaps(cur[name], cur[n]):
                continue
            top = cur[name].y() + cur[name].height()
            r = cur[n]
            if n in fixed:
                heights = [r.height()]
            else:
                heights = range(min(r.height(), max_rows - top), MIN_H - 1, -1)
            for h in heights:
                if top + h > max_rows:
                    continue
                trial = {k: QRect(v) for k, v in cur.items()}
                trial[n] = QRect(r.x(), top, r.width(), h)
                done = settle(n, trial)
                if done is not None:
                    cur = done
                    break
            else:
                return None
        return cur

    return settle(moved, out)


# ------------------------------------------------------------------ title bar
class PaneTitleBar(QWidget):
    def __init__(self, dock: "Pane"):
        super().__init__(dock)
        self.dock = dock
        self.setFixedHeight(ROW_H - 2)
        self.setCursor(Qt.OpenHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 0, 2, 0)
        h.setSpacing(2)
        self.title = QLabel(dock.windowTitle())
        self.title.setMinimumWidth(0)                # a narrow pane clips its title
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        f = self.title.font(); f.setBold(True); self.title.setFont(f)
        h.addWidget(self.title, 1)
        self.min_btn = self._btn("–", "Minimize (roll up to the title bar)", dock.toggle_minimized)
        self.float_btn = self._btn("⧉", "Pop out into its own window", dock.toggle_floating)
        self.close_btn = self._btn("×", "Close (reopen from the View menu)", dock.close)
        for b in (self.min_btn, self.float_btn, self.close_btn):
            h.addWidget(b)
        self.close_btn.setVisible(dock.closable)
        self._press = None

    def _btn(self, text, tip, slot):
        b = QToolButton(self)
        b.setText(text); b.setToolTip(tip); b.setAutoRaise(True)
        b.setFocusPolicy(Qt.NoFocus)
        b.setFixedSize(QSize(20, 18))
        b.setCursor(Qt.ArrowCursor)
        b.clicked.connect(slot)
        return b

    def sync(self):
        floating = self.dock.isFloating()
        self.float_btn.setText("⇲" if floating else "⧉")
        self.float_btn.setToolTip("Put it back where it was on the grid" if floating
                                  else "Pop out into its own window")
        self.min_btn.setVisible(not floating)        # popped out: the system minimize button
        self.min_btn.setText("+" if self.dock.minimized else "–")
        self.min_btn.setToolTip("Restore" if self.dock.minimized else "Minimize (roll up to the title bar)")
        self.setToolTip("Drag here and drop on the main window to put it on the grid there"
                        if floating else "Drag to move · corner grip to resize")

    def mouseDoubleClickEvent(self, ev):
        self.dock.toggle_floating()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)
        g = ev.globalPosition().toPoint()
        if self.dock.isFloating():
            self._press = ("float", g - self.dock.frameGeometry().topLeft())
        elif self.dock.canvas is not None:
            self._press = ("move", g)
            self.dock.canvas.begin_move(self.dock, g)
        self.setCursor(Qt.ClosedHandCursor)
        ev.accept()

    def mouseMoveEvent(self, ev):
        if not self._press:
            return super().mouseMoveEvent(ev)
        g = ev.globalPosition().toPoint()
        kind, start = self._press
        if kind == "float":
            self.dock.move(g - start)
            if self.dock.canvas is not None:
                self.dock.canvas.preview_drop(self.dock, g)
        elif self.dock.canvas is not None:
            self.dock.canvas.drag_move(g)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if not self._press:
            return super().mouseReleaseEvent(ev)
        kind, _ = self._press
        self._press = None
        self.setCursor(Qt.OpenHandCursor)
        g = ev.globalPosition().toPoint()
        if kind == "float" and self.dock.canvas is not None:
            self.dock.canvas.drop_floating(self.dock, g)
        elif self.dock.canvas is not None:
            self.dock.canvas.end_drag()
        ev.accept()


class ResizeGrip(QWidget):
    """Bottom-right corner: drag to resize the tile on the grid."""

    def __init__(self, dock: "Pane"):
        super().__init__(dock)
        self.dock = dock
        self.setFixedSize(12, 12)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setToolTip("Drag to resize")
        self._on = False

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setPen(QColor(128, 128, 128))
        for i in (3, 6, 9):
            p.drawLine(11, i, i, 11)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.dock.canvas is not None and not self.dock.isFloating():
            self._on = True
            self.dock.canvas.begin_resize(self.dock, ev.globalPosition().toPoint())
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._on:
            self.dock.canvas.drag_resize(ev.globalPosition().toPoint())
            ev.accept()

    def mouseReleaseEvent(self, ev):
        if self._on:
            self._on = False
            self.dock.canvas.end_drag()
            ev.accept()


# ------------------------------------------------------------------ a pane
class Pane(QFrame):
    """One tile. `grid` is its place in cells (x, y, width, height)."""
    topLevelChanged = Signal(bool)          # popped out / put back
    visibilityChanged = Signal(bool)

    def __init__(self, title: str, widget: QWidget, parent=None, closable: bool = True,
                 scroll: bool = True):
        super().__init__(parent)
        self.setObjectName(f"dock_{title}")
        self.setWindowTitle(title)
        self.setFrameShape(QFrame.StyledPanel)
        self.content = widget
        self.closable = closable
        self.minimized = False
        self.floating = False
        self.shown = True
        self.canvas: GridCanvas | None = None
        self.grid = QRect(0, 0, 6, 6)
        self._float_geo: QRect | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(1, 1, 1, 1)
        v.setSpacing(0)
        self.bar = PaneTitleBar(self)
        v.addWidget(self.bar)
        self.body = _shrinkable(widget) if scroll else widget
        v.addWidget(self.body, 1)
        self.grip = ResizeGrip(self)
        self._view_action = QAction(title, self, checkable=True, checked=True)
        self._view_action.toggled.connect(self._on_view_toggled)
        self.bar.sync()

    # QDockWidget-style API the main window uses
    def widget(self) -> QWidget:
        return self.body

    def isFloating(self) -> bool:
        return self.floating

    def toggleViewAction(self) -> QAction:
        return self._view_action

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.grip.move(self.width() - self.grip.width() - 1, self.height() - self.grip.height() - 1)
        self.grip.raise_()

    # -- show / close ------------------------------------------------------------
    def _on_view_toggled(self, on: bool):
        if on != self.shown:
            self.set_shown(on)

    def set_shown(self, on: bool):
        self.shown = on
        self._view_action.blockSignals(True)
        self._view_action.setChecked(on)
        self._view_action.blockSignals(False)
        if on:
            if self.floating:
                self.show()
            elif self.canvas is not None:
                self.canvas.place(self, self.grid)        # back where it was, bumping others
        else:
            self.hide()
            if self.canvas is not None:
                self.canvas.relayout()
                self.canvas.layoutChanged.emit()
        self.visibilityChanged.emit(on)

    def close(self):
        if self.floating:
            self.setFloating(False)                     # closed while popped out: goes home hidden
        self.set_shown(False)
        return True

    def closeEvent(self, ev):
        if self.floating:                               # the window's own close button
            ev.ignore()
            self.close()
            return
        super().closeEvent(ev)

    # -- minimize ------------------------------------------------------------------
    def toggle_minimized(self):
        self.set_minimized(not self.minimized)

    def set_minimized(self, on: bool):
        if self.floating:
            if on:
                self.showMinimized()
            return
        if on == self.minimized:
            return
        self.minimized = on
        self.body.setVisible(not on)
        self.grip.setVisible(not on)
        self.bar.sync()
        if self.canvas is not None:
            if on:
                self.canvas.relayout()                  # rolls up; nothing else moves
                self.canvas.layoutChanged.emit()
            else:
                self.canvas.place(self, self.grid)      # unrolls, bumping anything now below

    # -- pop out / put back --------------------------------------------------------
    def toggle_floating(self):
        self.setFloating(not self.floating)

    def setFloating(self, on: bool):
        if on == self.floating or self.canvas is None:
            return
        if on:
            if self.minimized:
                self.set_minimized(False)
            geo = self._float_geo or QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
            self.floating = True
            self.setParent(None)
            self.setWindowFlags(FLOAT_FLAGS if self.closable else FLOAT_FLAGS & ~Qt.WindowCloseButtonHint)
            self.setGeometry(geo)
            self.grip.hide()
            self.show()
            self.canvas.relayout()
        else:
            self._float_geo = self.geometry()
            self.floating = False
            self.setParent(self.canvas)
            self.setWindowFlags(Qt.Widget)
            self.grip.setVisible(not self.minimized)
            if self.shown:
                self.show()
                self.canvas.place(self, self.grid)
        self.bar.sync()
        self.topLevelChanged.emit(on)
        self.canvas.layoutChanged.emit()

    def _on_top_level(self, floating: bool):            # kept for the main window's startup code
        self.bar.sync()


# ------------------------------------------------------------------ the grid
class GridCanvas(QWidget):
    """Holds the tiles; columns follow the width, rows are ROW_H px."""
    layoutChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.panes: dict[str, Pane] = {}
        self._drag = None
        self._anims: list[QPropertyAnimation] = []
        self.ghost = QFrame(self)
        self.ghost.setStyleSheet("background: rgba(60, 130, 230, 50); border: 2px dashed rgb(60, 130, 230);"
                                 " border-radius: 4px;")
        self.ghost.hide()
        self.setMinimumSize(200, 100)

    # -- cells <-> pixels ----------------------------------------------------------
    def col_w(self) -> float:
        return max(4.0, (self.width() - GAP * (COLS + 1)) / COLS)

    def to_px(self, r: QRect) -> QRect:
        cw = self.col_w()
        x = round(GAP + r.x() * (cw + GAP))
        w = round(r.width() * cw + (r.width() - 1) * GAP)
        y = GAP + r.y() * (ROW_H + GAP)
        h = r.height() * ROW_H + (r.height() - 1) * GAP
        return QRect(x, y, w, h)

    def to_cell(self, p: QPoint) -> QPoint:
        cw = self.col_w()
        return QPoint(round((p.x() - GAP) / (cw + GAP)), round((p.y() - GAP) / (ROW_H + GAP)))

    # -- tiles ---------------------------------------------------------------------
    def add(self, pane: Pane, rect: QRect):
        pane.canvas = self
        pane.setParent(self)
        pane.grid = QRect(rect)
        self.panes[pane.objectName()] = pane
        pane.show()

    def on_grid(self) -> list[Pane]:
        return [p for p in self.panes.values() if p.shown and not p.floating]

    @staticmethod
    def occupied(p: Pane, r: QRect | None = None) -> QRect:
        r = QRect(r if r is not None else p.grid)
        if p.minimized:
            r.setHeight(1)
        return r

    def find_free(self, w: int, h: int, prefer: QRect | None = None) -> QRect:
        """A free spot w x h cells: `prefer` if it's free, else the first free one from
        the top left, else below everything."""
        taken = [self.occupied(p) for p in self.on_grid()]
        free = lambda r: not any(overlaps(r, t) for t in taken)
        if prefer is not None:
            r = QRect(prefer.x(), prefer.y(), w, h)
            if free(r):
                return QRect(prefer.x(), prefer.y(), w, prefer.height())
        bottom = max((t.y() + t.height() for t in taken), default=0)
        for y in range(0, bottom + 1):
            for x in range(0, COLS - w + 1):
                if free(QRect(x, y, w, h)):
                    return QRect(x, y, w, prefer.height() if prefer is not None else h)
        return QRect(0, bottom, w, prefer.height() if prefer is not None else h)

    def rows(self) -> int:
        """How many grid rows fit in the visible window (panes stop at its bottom)."""
        vp = self.parentWidget()
        h = vp.height() if vp is not None else self.height()
        return max(MIN_H, int((h - GAP) // (ROW_H + GAP)))

    def _fixed(self) -> set:
        return {p.objectName() for p in self.on_grid() if p.minimized}

    def _apply(self, new: dict, skip: Pane | None = None):
        """Take pushed positions (and shrunk heights) from push_down's result."""
        for p in self.on_grid():
            if p is skip or p.objectName() not in new:
                continue
            r = new[p.objectName()]
            p.grid.moveTop(r.y())
            if not p.minimized:
                p.grid.setHeight(r.height())

    def place(self, pane: Pane, rect: QRect):
        """Put a pane at rect, pushing anything it overlaps down (shrinking what would go
        off the bottom); others don't move otherwise."""
        rect = self._clamp(rect)
        tiles = {p.objectName(): self.occupied(p) for p in self.on_grid()}
        tiles[pane.objectName()] = self.occupied(pane, rect)
        new = push_down(tiles, pane.objectName(), self.rows(), self._fixed())
        if new is None:                                   # no room left: let it run below and scroll
            new = push_down(tiles, pane.objectName())
        pane.grid = rect
        self._apply(new, skip=pane)
        self.relayout(animate=True)
        self.layoutChanged.emit()

    def _clamp(self, r: QRect, fit: bool = True) -> QRect:
        """Keep a rect on the grid: inside the sides always, and (fit) above the bottom
        of the visible window too."""
        w = max(MIN_W, min(COLS, r.width()))
        h = max(MIN_H, r.height())
        y = max(0, r.y())
        if fit:
            rows = self.rows()
            h = min(h, max(MIN_H, rows))
            y = min(y, max(0, rows - h))
        return QRect(max(0, min(COLS - w, r.x())), y, w, h)

    def relayout(self, animate: bool = False, skip: Pane | None = None):
        for a in self._anims:
            a.stop()
        self._anims = []
        bottom = 0
        for p in self.on_grid():
            target = self.to_px(self.occupied(p))
            bottom = max(bottom, target.bottom())
            if p is skip:
                continue
            if animate and p.isVisible() and p.geometry() != target:
                a = QPropertyAnimation(p, b"geometry", self)
                a.setDuration(ANIM_MS)
                a.setEasingCurve(QEasingCurve.OutCubic)
                a.setEndValue(target)
                a.start()
                self._anims.append(a)
            else:
                p.setGeometry(target)
            p.show()
        self.setMinimumHeight(bottom + GAP + ROW_H)       # scrolls when tiles go below the window

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.relayout()

    def finish_animations(self):
        for a in self._anims:
            a.setCurrentTime(a.duration())
        self._anims = []

    # -- dragging (move / resize), live pushing --------------------------------------
    def begin_move(self, pane: Pane, gpos: QPoint):
        self.finish_animations()
        self._drag = {"pane": pane, "kind": "move", "start": gpos, "geo": QRect(pane.geometry()),
                      "base": {p.objectName(): QRect(p.grid) for p in self.on_grid()},
                      "target": QRect(pane.grid)}
        pane.raise_()

    def begin_resize(self, pane: Pane, gpos: QPoint):
        self.finish_animations()
        self._drag = {"pane": pane, "kind": "resize", "start": gpos, "geo": QRect(pane.geometry()),
                      "base": {p.objectName(): QRect(p.grid) for p in self.on_grid()},
                      "target": QRect(pane.grid)}
        pane.raise_()

    def drag_move(self, gpos: QPoint):
        d = self._drag
        if not d:
            return
        pane, delta = d["pane"], gpos - d["start"]
        geo = QRect(d["geo"])
        geo.translate(delta)
        vis_h = self.parentWidget().height() if self.parentWidget() is not None else self.height()
        geo.moveTo(max(0, min(self.width() - geo.width(), geo.x())),        # hard stop at the edges
                   max(0, min(vis_h - geo.height(), geo.y())))
        pane.move(geo.topLeft())                          # follows the mouse
        c = self.to_cell(geo.topLeft())
        target = self._clamp(QRect(c.x(), c.y(), pane.grid.width(), pane.grid.height()))
        self._preview(pane, target)

    def drag_resize(self, gpos: QPoint):
        d = self._drag
        if not d:
            return
        pane, delta = d["pane"], gpos - d["start"]
        geo = QRect(d["geo"])
        vis_h = self.parentWidget().height() if self.parentWidget() is not None else self.height()
        geo.setWidth(max(40, min(self.width() - geo.x(), geo.width() + delta.x())))   # stops at the edges
        geo.setHeight(max(ROW_H * MIN_H, min(vis_h - geo.y(), geo.height() + delta.y())))
        pane.resize(geo.size())
        cw = self.col_w()
        w = round((geo.width() + GAP) / (cw + GAP))
        h = round((geo.height() + GAP) / (ROW_H + GAP))
        target = self._clamp(QRect(pane.grid.x(), pane.grid.y(), w, h))
        self._preview(pane, target)

    def _preview(self, pane: Pane, target: QRect):
        d = self._drag
        self.ghost.setGeometry(self.to_px(target))
        self.ghost.show()
        self.ghost.stackUnder(pane)
        if target == d["target"] and d.get("pushed"):
            return
        base = {n: QRect(r) for n, r in d["base"].items()}
        tiles = {n: self.occupied(self.panes[n], r) for n, r in base.items()}
        tiles[pane.objectName()] = self.occupied(pane, target)
        new = push_down(tiles, pane.objectName(), self.rows(), self._fixed())
        if new is None:                                   # would shove something off: stop here
            self.ghost.setGeometry(self.to_px(d["target"]))
            return
        d["target"] = target
        for p in self.on_grid():                          # others slide out of the way (from where they were)
            if p is not pane:
                p.grid = QRect(base[p.objectName()])
        self._apply(new, skip=pane)
        d["pushed"] = True
        self.relayout(animate=True, skip=pane)

    def end_drag(self):
        d, self._drag = self._drag, None
        self.ghost.hide()
        if not d:
            return
        d["pane"].grid = QRect(d["target"])
        self.relayout(animate=True)
        self.layoutChanged.emit()

    # -- a popped-out pane dropped back on the grid -----------------------------------
    def _drop_cell(self, pane: Pane, gpos: QPoint) -> QRect | None:
        pos = self.mapFromGlobal(gpos)
        if not self.rect().contains(pos):
            return None
        c = self.to_cell(pos - QPoint(int(self.col_w()), ROW_H // 2))   # cursor is on its title, near the left
        return self._clamp(QRect(c.x(), c.y(), pane.grid.width(), pane.grid.height()))

    def preview_drop(self, pane: Pane, gpos: QPoint):
        r = self._drop_cell(pane, gpos)
        if r is None:
            self.ghost.hide()
        else:
            self.ghost.setGeometry(self.to_px(r)); self.ghost.show(); self.ghost.raise_()

    def drop_floating(self, pane: Pane, gpos: QPoint) -> bool:
        self.ghost.hide()
        r = self._drop_cell(pane, gpos)
        if r is None:
            return False                                  # dropped off the window: stays popped out
        pane.grid = r
        pane.setFloating(False)
        return True

    # -- saving ----------------------------------------------------------------------
    def to_dict(self) -> dict:
        out = {}
        for name, p in self.panes.items():
            g = p.grid
            item = {"r": [g.x(), g.y(), g.width(), g.height()], "min": p.minimized, "shown": p.shown}
            fg = p.geometry() if p.floating else p._float_geo
            if p.floating:
                item["float"] = [fg.x(), fg.y(), fg.width(), fg.height()]
            out[name] = item
        return out

    def from_dict(self, data: dict):
        for name, p in self.panes.items():
            item = data.get(name)
            if not item:
                continue
            if p.floating:
                p.setFloating(False)
            if p.minimized:
                p.minimized = False
                p.body.setVisible(True); p.grip.setVisible(True); p.bar.sync()
            x, y, w, h = item.get("r", [0, 0, 6, 6])
            p.grid = self._clamp(QRect(x, y, w, h), fit=False)   # as saved: the window may not be shown yet
            p.shown = bool(item.get("shown", True))
            p._view_action.blockSignals(True); p._view_action.setChecked(p.shown)
            p._view_action.blockSignals(False)
            p.setVisible(p.shown)
            if item.get("min"):
                p.minimized = True
                p.body.setVisible(False); p.grip.setVisible(False); p.bar.sync()
        new = [p for name, p in self.panes.items() if name not in data]
        for p in new:                                # a pane added since this layout was saved:
            if not p.floating:                       # rolled up, out of the way of what's there
                p.minimized = True
                p.body.setVisible(False); p.grip.setVisible(False); p.bar.sync()
        for name, p in self.panes.items():
            item = data.get(name) or {}
            if item.get("float") and p.shown:
                fx, fy, fw, fh = item["float"]
                p._float_geo = QRect(fx, fy, fw, fh)
                p.setFloating(True)
        self.relayout()
        for p in new:                                # into free space if there is any
            p.grid = self.find_free(p.grid.width(), 1, prefer=p.grid)
            self.place(p, p.grid)
