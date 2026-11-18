"""Panes that can be minimized, popped out, and closed.

Docked: the title bar has  _  (minimize: roll up to just the title bar),
⧉ (pop out into its own window) and × (close; bring back from View).
Popped out: the pane becomes a normal window with the system's own
minimize / zoom / close buttons, so it can go to the Dock/taskbar like any
other window. The ⇲ button (or double-clicking the title bar) docks it again.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QDockWidget, QFrame, QHBoxLayout, QLabel, QMainWindow, QScrollArea,
                               QSizePolicy, QToolButton, QWidget)

QWIDGETSIZE_MAX = (1 << 24) - 1


def _docked(mw) -> list:
    """Panes docked in the main window (not popped out), one per tab group: a tab
    hidden behind another reports a stale size, and resizing it would resize the
    whole group."""
    out = []
    for d in mw.findChildren(QDockWidget):
        if not d.isVisible() or d.isFloating():
            continue
        if mw.tabifiedDockWidgets(d) and d.visibleRegion().isEmpty():
            continue                                  # a tab that isn't the one showing
        out.append(d)
    return out

FLOAT_FLAGS = (Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint |
               Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint |
               Qt.WindowCloseButtonHint)


class PaneTitleBar(QWidget):
    def __init__(self, dock: "Pane"):
        super().__init__(dock)
        self.dock = dock
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 1, 2, 1)
        h.setSpacing(2)
        self.title = QLabel(dock.windowTitle())
        self.title.setMinimumWidth(0)                # a narrow pane clips its title, not the other panes
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        f = self.title.font(); f.setBold(True); self.title.setFont(f)
        h.addWidget(self.title, 1)
        self.min_btn = self._btn("–", "Minimize (roll up to the title bar)", dock.toggle_minimized)
        self.float_btn = self._btn("⧉", "Pop out into its own window", dock.toggle_floating)
        self.close_btn = self._btn("×", "Close (reopen from the View menu)", dock.close)
        for b in (self.min_btn, self.float_btn, self.close_btn):
            h.addWidget(b)
        self.close_btn.setVisible(dock.closable)

    def _btn(self, text, tip, slot):
        b = QToolButton(self)
        b.setText(text); b.setToolTip(tip); b.setAutoRaise(True)
        b.setFocusPolicy(Qt.NoFocus)
        b.setFixedSize(QSize(20, 18))
        b.clicked.connect(slot)
        return b

    def sync(self):
        floating = self.dock.isFloating()
        self.float_btn.setText("⇲" if floating else "⧉")
        self.float_btn.setToolTip("Dock back into the main window" if floating
                                  else "Pop out into its own window")
        # popped-out panes use the system minimize button instead
        self.min_btn.setVisible(not floating)
        self.min_btn.setText("+" if self.dock.minimized else "–")
        self.min_btn.setToolTip("Restore" if self.dock.minimized else "Minimize (roll up to the title bar)")

    def mouseDoubleClickEvent(self, ev):
        self.dock.toggle_floating()


# Smallest a pane may be squeezed to. Below what its contents need, it
# scrolls instead of forcing the whole window to be bigger than a small screen.
PANE_MIN = QSize(120, 48)


def _shrinkable(widget: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidget(widget)
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.NoFrame)
    sc.setMinimumSize(PANE_MIN)
    sc.setSizePolicy(widget.sizePolicy())
    return sc


class Pane(QDockWidget):
    def __init__(self, title: str, widget: QWidget, parent=None, closable: bool = True,
                 scroll: bool = True):
        super().__init__(title, parent, objectName=f"dock_{title}")
        self.content = widget
        self.setWidget(_shrinkable(widget) if scroll else widget)
        self.closable = closable
        if not closable:
            self.setFeatures(self.features() & ~QDockWidget.DockWidgetClosable)
        self.minimized = False
        self.bar = PaneTitleBar(self)  # needs self.closable
        self.setTitleBarWidget(self.bar)
        self.topLevelChanged.connect(self._on_top_level)
        self.bar.sync()

    # -- minimize (docked) -------------------------------------------------
    def toggle_minimized(self):
        self.set_minimized(not self.minimized)

    def set_minimized(self, on: bool, restore_heights: dict | None = None):
        """restore_heights: {pane objectName: height} to give back on restore (a saved
        layout's), instead of the heights at the moment of minimizing."""
        if self.isFloating():
            if on:
                self.showMinimized()
            return
        if on == self.minimized:
            return
        mw = self.parentWidget() if isinstance(self.parentWidget(), QMainWindow) else None
        # Rolling up must not move the other panes: keep every column's width
        # (only this pane's height goes to its neighbour), and give it back its
        # own height when it's restored.
        widths = {d: d.width() for d in _docked(mw)} if mw else {}
        if on:
            # heights of everything as it was, to put back on restore
            self._heights_before_min = {d: d.height() for d in _docked(mw)} if mw else {}
            if restore_heights and mw:
                by_name = {d.objectName(): d for d in _docked(mw)}
                self._heights_before_min = {by_name[n]: h for n, h in restore_heights.items() if n in by_name}
            self.setFixedWidth(self.width())          # its column keeps its width
        self.minimized = on
        self.widget().setVisible(not on)
        if not on:
            self.setMinimumWidth(0); self.setMaximumWidth(QWIDGETSIZE_MAX)
        self.bar.sync()
        if mw:
            self._settle_gen = getattr(self, "_settle_gen", 0) + 1
            gen = self._settle_gen
            QTimer.singleShot(0, lambda: self._settle(mw, widths, on, gen))

    def restore_heights(self) -> dict:
        """What restoring this (minimized) pane would give back, by pane name (saved with layouts)."""
        return {d.objectName(): h for d, h in getattr(self, "_heights_before_min", {}).items()}

    def unroll_now(self):
        """Un-minimize without resizing anything (a whole layout is about to be restored)."""
        if self.minimized:
            self.minimized = False
            self.widget().setVisible(True)
            self.setMinimumWidth(0); self.setMaximumWidth(QWIDGETSIZE_MAX)
            self._settle_gen = getattr(self, "_settle_gen", 0) + 1     # drop a pending re-layout
            self.bar.sync()

    def _settle(self, mw, widths: dict, minimized: bool, gen: int | None = None):
        if gen is not None and gen != getattr(self, "_settle_gen", 0):
            return
        alive = [d for d in widths if d in _docked(mw)]
        if alive:
            mw.resizeDocks(alive, [widths[d] for d in alive], Qt.Horizontal)
        heights = getattr(self, "_heights_before_min", {})
        if not minimized and heights and not self.isFloating():
            mine = self.geometry()
            back = [d for d in heights if d in _docked(mw) and not getattr(d, "minimized", False)
                    and d.geometry().left() < mine.right() and mine.left() < d.geometry().right()]  # my column
            mw.resizeDocks(back, [heights[d] for d in back], Qt.Vertical)

    # -- pop out / dock back ---------------------------------------------------
    def toggle_floating(self):
        if self.minimized:
            self.set_minimized(False)
        self.setFloating(not self.isFloating())

    def _on_top_level(self, floating: bool):
        if floating:
            # A real window: system minimize/zoom/close, shows in the Dock/taskbar.
            geo = self.geometry()
            self.setWindowFlags(FLOAT_FLAGS if self.closable
                                else FLOAT_FLAGS & ~Qt.WindowCloseButtonHint)
            self.setGeometry(geo)
            self.show()
        if self.minimized:
            self.minimized = False
            self.widget().setVisible(True)
            self.setMinimumWidth(0); self.setMaximumWidth(QWIDGETSIZE_MAX)
        self.bar.sync()
