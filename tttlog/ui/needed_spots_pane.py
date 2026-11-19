"""Needed Spots pane: spotted stations you still need, as a list you can filter.

Shows spots that are a new multiplier (MULT) or a new QSO (Q) for the open log,
from the spots that pass your spot filter. Filters: band (all, the band you're
on, or one band), what they're needed for (mults and Qs, mults only, Qs only),
and which kind of mult (countries, zones...). Double-click a row to go there.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .widgets import text_color_for

ALL_BANDS, MY_BAND = "All bands", "Band I'm on"
KINDS = {"both": "Mults and Qs", "mult": "Mults only", "q": "Qs only"}


def what_it_is(s) -> str:
    """'Japan, zone 25' (the mults a spot carries that we need), or 'new Q'."""
    if s.status != "MULT":
        return "new Q"
    out = []
    for lbl, key in s.keys:
        if lbl in s.mults:
            v = str(key[-1])
            out.append(f"zone {v}" if v.isdigit() else v)
    return ", ".join(dict.fromkeys(out)) or ", ".join(s.mults)


class NeededSpotsPane(QWidget):
    spotActivated = Signal(object)          # Spot

    COLS = ["Time", "kHz", "Call", "Band", "Mode", "Needed for", "Country"]

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.current_band: str | None = None
        self.privilege_check = None
        self._spots: list = []
        self._shown: list = []
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.band_box = QComboBox(); self.band_box.setFocusPolicy(Qt.NoFocus)
        self.band_box.addItems([ALL_BANDS, MY_BAND])
        self.band_box.setToolTip("Which band")
        self.kind_box = QComboBox(); self.kind_box.setFocusPolicy(Qt.NoFocus)
        for k, label in KINDS.items():
            self.kind_box.addItem(label, k)
        self.kind_box.setToolTip("Needed as a multiplier, as a new QSO, or both")
        self.mult_box = QComboBox(); self.mult_box.setFocusPolicy(Qt.NoFocus)
        self.mult_box.addItem("Any mult", "")
        self.mult_box.setToolTip("Which kind of multiplier (countries, zones...)")
        for w in (self.band_box, self.kind_box, self.mult_box):
            w.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            w.currentIndexChanged.connect(self.refresh)
            bar.addWidget(w)
        bar.addStretch()
        v.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(19)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setFocusPolicy(Qt.ClickFocus)
        self.table.doubleClicked.connect(self._activate)
        v.addWidget(self.table, 1)
        self._dirty = QTimer(self, singleShot=True, interval=300, timeout=self.refresh)

    # -- data in ----------------------------------------------------------
    def set_engine(self, engine):
        """The open log: its bands and its kinds of mult go in the filters."""
        cur_band, cur_mult = self.band_box.currentText(), self.mult_box.currentData()
        for box in (self.band_box, self.mult_box):
            box.blockSignals(True)
        while self.band_box.count() > 2:
            self.band_box.removeItem(2)
        while self.mult_box.count() > 1:
            self.mult_box.removeItem(1)
        if engine:
            for b in engine.rules.get("bands", []):
                self.band_box.addItem(b)
            for label in dict.fromkeys(m.get("label", m["type"]) for m in engine.rules.get("mults", [])):
                self.mult_box.addItem(label, label)
        self.band_box.setCurrentIndex(max(0, self.band_box.findText(cur_band)))
        self.mult_box.setCurrentIndex(max(0, self.mult_box.findData(cur_mult)))
        self.mult_box.setVisible(self.mult_box.count() > 2)       # only worth showing with 2+ kinds
        for box in (self.band_box, self.mult_box):
            box.blockSignals(False)
        self.refresh()

    def update_spots(self, spots: list, current_band: str | None):
        self._spots = spots
        self.current_band = current_band
        if not self._dirty.isActive():
            self._dirty.start()

    # -- view ---------------------------------------------------------------
    def visible(self) -> list:
        band = self.band_box.currentText()
        if band == MY_BAND:
            band = self.current_band or ""
        kind = self.kind_box.currentData()
        mult = self.mult_box.currentData()
        out = []
        for s in self._spots:
            if s.status not in ("MULT", "Q"):
                continue
            if band != ALL_BANDS and s.band != band:
                continue
            if kind == "mult" and s.status != "MULT" or kind == "q" and s.status != "Q":
                continue
            if mult and s.status == "MULT" and mult not in s.mults:
                continue
            if mult and s.status == "Q" and kind != "q":
                continue                                      # a mult kind picked: Qs aren't that kind
            out.append(s)
        return sorted(out, key=lambda s: (s.status != "MULT", -s.time_utc.timestamp()))

    def refresh(self):
        shown = self.visible()
        self._shown = shown
        t = self.table
        t.setRowCount(len(shown))
        for r, s in enumerate(shown):
            bg = self.colors["spot_mult" if s.status == "MULT" else "spot_q"]["color"]
            why = self.privilege_check(s) if self.privilege_check else ""
            vals = [s.time_utc.strftime("%H%M"), f"{s.freq_khz:.1f}", s.call, s.band or "", s.mode,
                    what_it_is(s), s.country]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                it.setBackground(QBrush(QColor(bg)))
                it.setForeground(QBrush(QColor(text_color_for(bg))))
                if why:
                    f = it.font(); f.setStrikeOut(True); it.setFont(f); it.setToolTip(why)
                t.setItem(r, c, it)
        n_mult = sum(1 for s in shown if s.status == "MULT")
        self.summary.setText(f"{n_mult} mults · {len(shown) - n_mult} new Qs"
                             + ("" if self.band_box.currentText() == ALL_BANDS else
                                f" on {self.current_band if self.band_box.currentText() == MY_BAND else self.band_box.currentText()}"))

    def _activate(self, index):
        if 0 <= index.row() < len(self._shown):
            self.spotActivated.emit(self._shown[index.row()])
