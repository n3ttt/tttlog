"""Bandmap: the band drawn as a frequency scale with the spots at their frequencies,
coloured like the Spots pane (mult / Q / dupe), and a marker where the radio is.
Click a spot to go there; Ctrl+Down / Ctrl+Up (main window) step to the next spot
up or down the band, for S&P. The mouse wheel or + / − zoom."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)

from ..core.models import BANDS_KHZ
from .widgets import text_color_for

STATUS_KEY = {"MULT": "spot_mult", "Q": "spot_q", "DUPE": "spot_dupe", "INVALID": "spot_dupe"}
MY_BAND = "Band I'm on"
ZOOMS = [2.0, 4.0, 8.0, 15.0, 30.0, 60.0]    # px per kHz
SCALE_W = 44                                 # px for the frequency scale on the left
ROW_H = 16                                   # px per spot label


def band_edges(band: str) -> tuple[float, float] | None:
    return next(((lo, hi) for name, lo, hi in BANDS_KHZ if name == band), None)


def tick_step(px_per_khz: float) -> tuple[float, float]:
    """(minor, labelled) kHz between ticks, so labels sit ~40+ px apart."""
    for minor, major in ((0.5, 1), (1, 5), (2, 10), (5, 25), (10, 50), (25, 100), (50, 250)):
        if major * px_per_khz >= 40:
            return minor, major
    return 50, 250


def layout_labels(ys: list[float], top: float, height: int = ROW_H) -> list[float]:
    """Label positions: each at its spot's y if it fits, else pushed down below the one
    above (so close spots don't overlap). ys must be sorted ascending."""
    out, nxt = [], top
    for y in ys:
        place = max(y - height / 2, nxt)
        out.append(place)
        nxt = place + height
    return out


class BandmapCanvas(QWidget):
    spotClicked = Signal(object)

    def __init__(self, pane: "BandmapPane"):
        super().__init__(pane)
        self.pane = pane
        self.setMouseTracking(True)
        self._hits: list[tuple[QRect, object]] = []

    def y_for(self, khz: float) -> float:
        lo, _hi = self.pane.edges
        return 8 + (khz - lo) * self.pane.ppk

    def khz_at(self, y: float) -> float:
        lo, _hi = self.pane.edges
        return lo + (y - 8) / self.pane.ppk

    def full_height(self) -> int:
        lo, hi = self.pane.edges
        return int((hi - lo) * self.pane.ppk) + 16 + ROW_H

    def paintEvent(self, _ev):
        p = QPainter(self)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        lo, hi = self.pane.edges
        ppk = self.pane.ppk
        minor, major = tick_step(ppk)
        f = QFont(self.font()); f.setPointSizeF(max(8.0, f.pointSizeF() - 1)); p.setFont(f)
        fm = QFontMetrics(f)
        fg = pal.text().color()
        dim = QColor(fg); dim.setAlpha(110)
        # scale
        k = lo - (lo % minor)
        while k <= hi + 1e-6:
            if k >= lo:
                y = self.y_for(k)
                is_major = abs((k / major) - round(k / major)) < 1e-6
                p.setPen(QPen(fg if is_major else dim))
                p.drawLine(SCALE_W - (10 if is_major else 5), int(y), SCALE_W, int(y))
                if is_major:
                    txt = f"{k:.0f}" if major >= 1 else f"{k:.1f}"
                    p.drawText(QRect(0, int(y) - 8, SCALE_W - 11, 16), Qt.AlignRight | Qt.AlignVCenter, txt[-4:] if len(txt) > 5 else txt)
            k += minor
        p.setPen(QPen(dim))
        p.drawLine(SCALE_W, 0, SCALE_W, self.height())
        # the radio (under the spots, so a spot on it stays readable)
        if self.pane.radio_khz is not None and lo <= self.pane.radio_khz <= hi:
            y = int(self.y_for(self.pane.radio_khz))
            p.setPen(QPen(QColor("#d1242f"), 2))
            p.drawLine(0, y, self.width(), y)
            p.setBrush(QColor("#d1242f"))
            p.drawPolygon([QPoint(SCALE_W - 8, y - 5), QPoint(SCALE_W, y), QPoint(SCALE_W - 8, y + 5)])
        # spots
        self._hits = []
        spots = sorted(self.pane.visible_spots(), key=lambda s: s.freq_khz)
        ys = [self.y_for(s.freq_khz) for s in spots]
        label_x = SCALE_W + 12
        for s, y, ly in zip(spots, ys, layout_labels(ys, 0)):
            bg = QColor(self.pane.colors[STATUS_KEY.get(s.status, "spot_dupe")]["color"])
            text = f"{s.freq_khz:.1f}  {s.call}"            # mult / Q / dupe shows in its colour
            w = min(self.width() - label_x - 4, fm.horizontalAdvance(text) + 10)
            r = QRect(label_x, int(ly), max(40, w), ROW_H - 2)
            p.setPen(QPen(dim))
            p.drawLine(SCALE_W, int(y), label_x, r.center().y())          # leader to its frequency
            p.fillRect(r, bg)
            p.setPen(QPen(QColor(text_color_for(bg.name()))))
            if self.pane.privilege_check and self.pane.privilege_check(s):
                ff = QFont(f); ff.setStrikeOut(True); p.setFont(ff)
            else:
                p.setFont(f)
            p.drawText(r.adjusted(5, 0, -2, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
            self._hits.append((r, s))
        p.setFont(f)

    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        for r, s in self._hits:
            if r.contains(pos):
                self.spotClicked.emit(s)
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        hit = next((s for r, s in self._hits if r.contains(pos)), None)
        self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
        self.setToolTip(f"{hit.call} {hit.freq_khz:.1f} · {hit.status or 'spot'} · {hit.comment}"
                        f"\nspotted by {hit.spotter} at {hit.time_utc:%H%MZ}" if hit else
                        f"{self.khz_at(pos.y()):.1f} kHz")

    def wheelEvent(self, ev):
        if ev.modifiers() & (Qt.ControlModifier | Qt.MetaModifier) or not self.pane.scroll.verticalScrollBar().isVisible():
            self.pane.zoom(1 if ev.angleDelta().y() > 0 else -1, anchor_y=ev.position().y())
            ev.accept()
            return
        super().wheelEvent(ev)


class BandmapPane(QWidget):
    spotActivated = Signal(object)

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.privilege_check = None
        self.spots: list = []
        self.current_band: str | None = None
        self.radio_khz: float | None = None
        self.ppk = ZOOMS[2]
        self._follow = True
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2); v.setSpacing(2)
        bar = QHBoxLayout()
        self.band_box = QComboBox(); self.band_box.setFocusPolicy(Qt.NoFocus)
        self.band_box.addItem(MY_BAND)
        self.band_box.currentIndexChanged.connect(self._band_changed)
        self.dupes = QCheckBox("Dupes"); self.dupes.setFocusPolicy(Qt.NoFocus)
        self.dupes.setToolTip("Show spots you've already worked")
        self.dupes.toggled.connect(self.refresh)
        self.out_btn = QToolButton(text="−"); self.in_btn = QToolButton(text="+")
        for b, d, tip in ((self.out_btn, -1, "Zoom out"), (self.in_btn, 1, "Zoom in")):
            b.setFocusPolicy(Qt.NoFocus); b.setToolTip(tip + " (or Ctrl + mouse wheel)")
            b.clicked.connect(lambda _=False, d=d: self.zoom(d))
        bar.addWidget(self.band_box); bar.addWidget(self.dupes); bar.addStretch()
        bar.addWidget(self.out_btn); bar.addWidget(self.in_btn)
        v.addLayout(bar)
        self.summary = QLabel(); self.summary.setStyleSheet("font-size: 9pt;")
        v.addWidget(self.summary)
        self.canvas = BandmapCanvas(self)
        self.canvas.spotClicked.connect(self.spotActivated)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().sliderPressed.connect(lambda: setattr(self, "_follow", False))
        v.addWidget(self.scroll, 1)
        self._dirty = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)
        self._resize_canvas()

    # -- data in ----------------------------------------------------------------
    def set_bands(self, bands: list[str]):
        cur = self.band_box.currentText()
        self.band_box.blockSignals(True)
        while self.band_box.count() > 1:
            self.band_box.removeItem(1)
        self.band_box.addItems(bands)
        self.band_box.setCurrentIndex(max(0, self.band_box.findText(cur)))
        self.band_box.blockSignals(False)
        self.refresh()

    def update_spots(self, spots: list):
        self.spots = spots
        if not self._dirty.isActive():
            self._dirty.start()

    def set_radio(self, khz: float, band: str | None):
        moved = khz != self.radio_khz
        band_changed = band != self.current_band
        self.radio_khz, self.current_band = khz, band
        if band_changed and self.band_box.currentIndex() == 0:
            self._follow = True
            self.refresh()
        else:
            self.canvas.update()
        if moved and self._follow:
            self.center_on(khz)

    # -- view ---------------------------------------------------------------------
    @property
    def band(self) -> str | None:
        return self.current_band if self.band_box.currentIndex() == 0 else self.band_box.currentText()

    @property
    def edges(self) -> tuple[float, float]:
        return band_edges(self.band or "") or (14000.0, 14350.0)

    def visible_spots(self) -> list:
        b = self.band
        show_dupes = self.dupes.isChecked()
        return [s for s in self.spots if s.band == b and (show_dupes or s.status in ("MULT", "Q"))]

    def _band_changed(self):
        self._follow = True
        self.refresh()
        if self.radio_khz is not None and band_edges(self.band or "") and \
                self.edges[0] <= self.radio_khz <= self.edges[1]:
            self.center_on(self.radio_khz)
        else:
            self.scroll.verticalScrollBar().setValue(0)

    def _resize_canvas(self):
        self.canvas.resize(max(120, self.scroll.viewport().width()), self.canvas.full_height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._resize_canvas()

    def refresh(self):
        self._resize_canvas()
        vs = self.visible_spots()
        n_mult = sum(1 for s in vs if s.status == "MULT")
        self.summary.setText(f"{self.band or '—'} · {n_mult} mults · {sum(1 for s in vs if s.status == 'Q')} Qs"
                             + (f" · {len(vs) - n_mult - sum(1 for s in vs if s.status == 'Q')} dupes"
                                if self.dupes.isChecked() else ""))
        self.canvas.update()

    def center_on(self, khz: float):
        y = self.canvas.y_for(khz)
        sb = self.scroll.verticalScrollBar()
        sb.setValue(int(y - self.scroll.viewport().height() / 2))

    def zoom(self, step: int, anchor_y: float | None = None):
        i = min(range(len(ZOOMS)), key=lambda j: abs(ZOOMS[j] - self.ppk))
        j = max(0, min(len(ZOOMS) - 1, i + step))
        if j == i:
            return
        khz = self.canvas.khz_at(anchor_y) if anchor_y is not None else \
            (self.radio_khz if self.radio_khz is not None else sum(self.edges) / 2)
        self.ppk = ZOOMS[j]
        self.refresh()
        self.center_on(khz)
