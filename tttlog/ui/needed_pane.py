"""Needed window: every mult × band, colored by need and/or spotted.

Tick the states you want to see (each with its own color). Rows with nothing
in a ticked state are hidden, so "Needed & spotted" alone gives a short list
of mults you can go and work right now. Double-click a spotted cell to go to
the newest spot for it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import needed
from .widgets import StateToggle, text_color_for

MARK = {"needed_spotted": "●", "needed": "", "worked_spotted": "✓●", "worked": "✓"}


class NeededPane(QWidget):
    spotActivated = Signal(object)          # Spot
    colorsChanged = Signal()

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.engine = None
        self._qsos, self._spots = [], []
        self._rows: list[needed.NeedRow] = []
        self._cols: list[str] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)

        grid = QGridLayout()                    # 2 x 2 so the pane can stay narrow
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12); grid.setVerticalSpacing(0)
        self.toggles = {k: StateToggle(k, needed.STATE_LABELS[k], colors) for k in needed.STATES}
        for i, t in enumerate(self.toggles.values()):
            t.changed.connect(self._on_toggle)
            grid.addWidget(t, i // 2, i % 2, Qt.AlignLeft)
        grid.setColumnStretch(2, 1)
        v.addLayout(grid)

        bar2 = QHBoxLayout()
        self.mult_box = QComboBox()
        self.mult_box.setFocusPolicy(Qt.NoFocus)
        self.mult_box.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit(placeholderText="Search")
        self.search.setToolTip("Search prefix / country / zone")
        self.search.setStyleSheet("font: 11pt;")
        self.search.textChanged.connect(self.refresh)
        self.summary_lbl = QLabel()
        bar2.addWidget(self.mult_box); bar2.addWidget(self.search, 1); bar2.addWidget(self.summary_lbl)
        v.addLayout(bar2)

        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(19)
        self.table.cellDoubleClicked.connect(self._activate)
        self.table.setFocusPolicy(Qt.ClickFocus)
        v.addWidget(self.table, 1)
        self._dirty = QTimer(self, singleShot=True, interval=300, timeout=self.refresh)

    # -- data in ----------------------------------------------------------
    def set_engine(self, engine):
        self.engine = engine
        self.mult_box.blockSignals(True)
        self.mult_box.clear()
        if engine:
            for m in needed.mult_defs(engine):
                self.mult_box.addItem(m.get("label", m["type"]))
        self.mult_box.blockSignals(False)
        self.refresh()

    def update_data(self, qsos, spots):
        self._qsos, self._spots = qsos, spots
        self._dirty.start()

    def sync_colors(self):
        for t in self.toggles.values():
            t.sync()
        self.refresh()

    def _on_toggle(self):
        self.refresh()
        self.colorsChanged.emit()

    # -- view ---------------------------------------------------------------
    def refresh(self):
        t = self.table
        if not self.engine or self.mult_box.currentIndex() < 0:
            t.setRowCount(0); self.summary_lbl.setText("Open a log to see what's needed")
            return
        mdef = needed.mult_defs(self.engine)[self.mult_box.currentIndex()]
        cols, rows = needed.need_grid(self.engine, mdef, self._qsos, self._spots)
        all_counts = needed.counts(rows)
        shown_states = {k for k in needed.STATES if self.colors[k].get("show", True)}
        q = self.search.text().strip().upper()
        rows = [r for r in rows
                if any(st in shown_states for st in r.cells.values())
                and (not q or q in r.title.upper())]
        self._rows, self._cols = rows, cols

        hdr = ["Mult"] + [c.removesuffix("m") for c in cols]
        if t.columnCount() != len(hdr):
            t.setColumnCount(len(hdr))
        t.setHorizontalHeaderLabels(hdr)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(hdr)):
            t.horizontalHeader().setSectionResizeMode(c, QHeaderView.Fixed)
            t.setColumnWidth(c, 38)
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(row.title))
            for c, col in enumerate(cols, start=1):
                st = row.cells[col]
                it = QTableWidgetItem()
                it.setTextAlignment(Qt.AlignCenter)
                if st in shown_states:
                    bg = self.colors[st]["color"]
                    it.setText(MARK[st])
                    it.setBackground(QBrush(QColor(bg)))
                    it.setForeground(QBrush(QColor(text_color_for(bg))))
                    if row.spots.get(col):
                        s = row.spots[col][0]
                        it.setToolTip(f"{s.call} {s.freq_khz:.1f} spotted {s.time_utc:%H%MZ} by {s.spotter}"
                                      + (f"  (+{len(row.spots[col]) - 1} more)" if len(row.spots[col]) > 1 else ""))
                t.setItem(r, c, it)

        self.summary_lbl.setText(f"{all_counts['needed_spotted']} spotted now · "
                                 f"{all_counts['needed'] + all_counts['needed_spotted']:,} still needed · "
                                 f"{all_counts['worked'] + all_counts['worked_spotted']} worked")

    def _activate(self, r, c):
        if c == 0 or r >= len(self._rows):
            return
        spots = self._rows[r].spots.get(self._cols[c - 1])
        if spots:
            self.spotActivated.emit(spots[0])
