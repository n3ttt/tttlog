"""Panes that can be minimized, popped out, and closed.

Docked: the title bar has  _  (minimize: roll up to just the title bar),
⧉ (pop out into its own window) and × (close; bring back from View).
Popped out: the pane becomes a normal window with the system's own
minimize / zoom / close buttons, so it can go to the Dock/taskbar like any
other window. The ⇲ button (or double-clicking the title bar) docks it again.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QDockWidget, QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton, QWidget

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

    def set_minimized(self, on: bool):
        if self.isFloating():
            if on:
                self.showMinimized()
            return
        self.minimized = on
        self.widget().setVisible(not on)
        self.bar.sync()

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
        self.bar.sync()
