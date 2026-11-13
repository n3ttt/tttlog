"""Rate pane: rolling rates up top, hour-by-hour breakdown below."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import rates
from ..core.models import QSO


class RatePane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
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

        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        v.addWidget(self.table)
        self._bands: list[str] = []

    def update_rates(self, qsos: list[QSO], engine, now: datetime) -> None:
        s = rates.summary(qsos, now)
        self.vals["last10"].setText(f"{s.last10:.0f}/hr")
        self.vals["last100"].setText(f"{s.last100:.0f}/hr")
        self.vals["last60"].setText(str(s.last60_count))
        self.vals["last15"].setText(f"{s.last15_count}  ({s.last15_rate}/hr)")
        self.vals["best60"].setText(str(s.best60))

        bands = list(engine.rules["bands"]) if engine else sorted({q.band or "?" for q in qsos})
        if engine:
            rows = rates.hourly(qsos,
                                mult_keys=lambda q: engine.mult_values(q),
                                is_valid=engine.is_valid)
        else:
            rows = rates.hourly(qsos)
        if bands != self._bands:
            self._bands = bands
            hdr = ["Hour Z"] + [b.removesuffix("m") for b in bands] + ["QSOs", "Mults"]
            self.table.setColumnCount(len(hdr))
            self.table.setHorizontalHeaderLabels(hdr)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        rows = list(reversed(rows))                 # newest hour on top
        bold = QFont(); bold.setBold(True)
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
