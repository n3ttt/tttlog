"""Rate pane: rolling rates up top, per-operator rates, hour-by-hour breakdown below.

The "Rates for" picker narrows the top figures and the hour table to one operator."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import rates
from ..core.models import QSO


class RatePane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Rates for"))
        self.op_pick = QComboBox()
        self.op_pick.addItem("All operators", "")
        self.op_pick.currentIndexChanged.connect(self._redraw)
        pick.addWidget(self.op_pick, 1)
        v.addLayout(pick)
        g = QGridLayout()
        big = QFont(); big.setPointSize(13); big.setBold(True)
        self.vals: dict[str, QLabel] = {}
        for c, (key, title) in enumerate([("last10", "Last 10"), ("last100", "Last 100"),
                                          ("last60", "Last 60 min"), ("last15", "Last 15 min"),
                                          ("best60", "Best 60")]):
            t = QLabel(title); t.setAlignment(Qt.AlignCenter)
            val = QLabel("0"); val.setAlignment(Qt.AlignCenter); val.setFont(big)
            g.addWidget(t, 0, c); g.addWidget(val, 1, c)
            self.vals[key] = val
        v.addLayout(g)

        self.ops = QTableWidget(0, 6)
        self.ops.setHorizontalHeaderLabels(["Op", "QSOs", "%", "Last 10", "Last 60 min", "Best 60"])
        self.ops.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ops.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ops.verticalHeader().setVisible(False)
        self.ops.verticalHeader().setDefaultSectionSize(20)
        self.ops.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ops.setMaximumHeight(110)
        self.ops.cellDoubleClicked.connect(lambda r, _c: self._pick_op(self.ops.item(r, 0).text()))
        self.ops.setToolTip("Double-click an operator to see just their rates")
        v.addWidget(self.ops)

        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        v.addWidget(self.table)
        self._bands: list[str] = []

        self._last = ([], None, None, "")

    def _pick_op(self, op: str) -> None:
        i = self.op_pick.findData(op)
        if i >= 0:
            self.op_pick.setCurrentIndex(i)

    def _redraw(self) -> None:
        if self._last[2] is not None:
            self.update_rates(*self._last)

    def update_rates(self, qsos: list[QSO], engine, now: datetime, me: str = "") -> None:
        self._last = (qsos, engine, now, me)
        ops = rates.operators(qsos)
        if me and me not in ops:
            ops.append(me)
        want = self.op_pick.currentData() or ""
        if [self.op_pick.itemData(i) for i in range(1, self.op_pick.count())] != ops:
            self.op_pick.blockSignals(True)
            self.op_pick.clear()
            self.op_pick.addItem("All operators", "")
            for op in ops:
                self.op_pick.addItem(op + ("  (you)" if op == me else ""), op)
            self.op_pick.setCurrentIndex(max(0, self.op_pick.findData(want)))
            self.op_pick.blockSignals(False)
        else:
            for i in range(1, self.op_pick.count()):     # "(you)" follows OPON
                op = self.op_pick.itemData(i)
                self.op_pick.setItemText(i, op + ("  (you)" if op == me else ""))

        bold = QFont(); bold.setBold(True)
        rows_op = rates.by_operator(qsos, now) if qsos else []
        self.ops.setRowCount(len(rows_op))
        for r, row in enumerate(rows_op):
            cells = [row.op, str(row.qsos), f"{row.share * 100:.0f}", f"{row.summary.last10:.0f}/hr",
                     str(row.summary.last60_count), str(row.summary.best60)]
            for c, val in enumerate(cells):
                it = QTableWidgetItem(val)
                it.setTextAlignment(Qt.AlignCenter)
                if row.op == me:
                    it.setFont(bold)
                self.ops.setItem(r, c, it)

        sel = self.op_pick.currentData() or ""
        only = (lambda q: rates.op_of(q) == sel) if sel else None
        s = rates.summary([q for q in qsos if only(q)] if only else qsos, now)
        self.vals["last10"].setText(f"{s.last10:.0f}/hr")
        self.vals["last100"].setText(f"{s.last100:.0f}/hr")
        self.vals["last60"].setText(str(s.last60_count))
        self.vals["last15"].setText(f"{s.last15_count}  ({s.last15_rate}/hr)")
        self.vals["best60"].setText(str(s.best60))

        bands = list(engine.rules["bands"]) if engine else sorted({q.band or "?" for q in qsos})
        if engine:
            rows = rates.hourly(qsos,
                                mult_keys=lambda q: engine.mult_values(q),
                                is_valid=engine.is_valid, only=only)
        else:
            rows = rates.hourly(qsos, only=only)
        if bands != self._bands:
            self._bands = bands
            hdr = ["Hour Z"] + [b.removesuffix("m") for b in bands] + ["QSOs", "Mults"]
            self.table.setColumnCount(len(hdr))
            self.table.setHorizontalHeaderLabels(hdr)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        rows = list(reversed(rows))                 # newest hour on top
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = ([row.hour.strftime("%d %H")] +
                     [str(row.by_band.get(b, "") or "") for b in bands] +
                     [str(row.qsos), str(row.mults or "")])
            for c, v in enumerate(cells):
                it = QTableWidgetItem(v)
                it.setTextAlignment(Qt.AlignCenter)
                if c == len(cells) - 2:
                    it.setFont(bold)
                self.table.setItem(r, c, it)
