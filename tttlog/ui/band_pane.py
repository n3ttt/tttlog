"""Bands pane: one button per band in the open log's contest.

Clicking a band moves to it (back to where you last were on that band in
that kind of mode, else a usual spot for the mode). For now that changes
tttlog's frequency; with radio control it will tune the radio too, since
both go through MainWindow.set_freq.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QPushButton, QSizePolicy, QVBoxLayout, QWidget

STYLE = """
QPushButton { min-width: 0; padding: 2px 4px; font: bold 11pt; }
QPushButton:checked { background: #1f6feb; color: white; border: 1px solid #1158c7; border-radius: 3px; }
"""


class BandPane(QWidget):
    bandClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(3, 3, 3, 3)
        self._v.setSpacing(3)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def set_bands(self, bands: list[str]) -> None:
        if list(self.buttons) == list(bands):
            return
        for b in self.buttons.values():
            self._group.removeButton(b)
            b.deleteLater()
        self.buttons.clear()
        while self._v.count():
            self._v.takeAt(0)
        for band in bands:
            b = QPushButton(band.removesuffix("m") if band.endswith("m") and band != "70cm" else band)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)                  # keep typing in the call field
            b.setToolTip(f"Go to {band}")
            b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            b.setMinimumHeight(24)
            b.setMaximumHeight(44)
            b.clicked.connect(lambda _=False, x=band: self.bandClicked.emit(x))
            self._group.addButton(b)
            self._v.addWidget(b)
            self.buttons[band] = b
        self._v.addStretch(0)                         # buttons grow to 44 px tall, then stop

    def set_current(self, band: str | None) -> None:
        b = self.buttons.get(band or "")
        if b is not None:
            b.setChecked(True)
        else:                                             # off the contest's bands: none lit
            self._group.setExclusive(False)
            for x in self.buttons.values():
                x.setChecked(False)
            self._group.setExclusive(True)
