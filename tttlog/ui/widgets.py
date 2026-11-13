"""Small shared widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QColorDialog, QHBoxLayout, QToolButton, QWidget


def text_color_for(bg: str) -> str:
    """Black or white text, whichever reads better on bg."""
    c = QColor(bg)
    return "black" if (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) > 140 else "white"


class StateToggle(QWidget):
    """[x] Label  [■]  — checkbox to show/hide a state, swatch to pick its color.

    Reads and writes one entry of the shared colors dict ({"color", "show"}).
    """

    changed = Signal()

    def __init__(self, key: str, label: str, colors: dict, parent=None):
        super().__init__(parent)
        self.key, self.colors = key, colors
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 6, 0)
        h.setSpacing(3)
        self.box = QCheckBox(label.replace("&", "&&"))      # "&" would become a shortcut marker
        self.box.setFocusPolicy(Qt.NoFocus)
        self.box.toggled.connect(self._on_toggle)
        self.swatch = QToolButton()
        self.swatch.setFixedSize(18, 16)
        self.swatch.setFocusPolicy(Qt.NoFocus)
        self.swatch.setToolTip(f"Color for “{label}” (click to change)")
        self.label = label
        self.swatch.clicked.connect(self._pick)
        h.addWidget(self.box); h.addWidget(self.swatch)
        self.sync()

    def sync(self):
        e = self.colors[self.key]
        self.box.blockSignals(True)
        self.box.setChecked(bool(e.get("show", True)))
        self.box.blockSignals(False)
        self.swatch.setStyleSheet(f"background:{e['color']}; border:1px solid #666; border-radius:2px;")

    def _on_toggle(self, on):
        self.colors[self.key]["show"] = on
        self.changed.emit()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.colors[self.key]["color"]), self,
                                  f"Color for {self.label}")
        if c.isValid():
            self.set_color(c.name())

    def set_color(self, name: str):
        self.colors[self.key]["color"] = name
        self.sync()
        self.changed.emit()
