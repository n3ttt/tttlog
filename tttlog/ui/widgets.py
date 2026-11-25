"""Small shared widgets."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QColorDialog, QHBoxLayout, QLabel, QLayout, QToolButton, QWidget


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


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto the next line when the
    width runs out (like words in a paragraph). Used for the Entry pane's top
    line, so a narrow pane gets two short lines instead of a squashed one."""

    def __init__(self, parent=None, hspacing: int = 8, vspacing: int = 2):
        super().__init__(parent)
        self._items: list = []
        self._h, self._v = hspacing, vspacing
        # Each item keeps room for the widest it has been, so a label that fills in
        # as you type (the beam heading) doesn't wrap the line and move what's below.
        self._peak: dict[int, QSize] = {}
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            if not it.isEmpty():
                size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            wdg = it.widget()
            if it.isEmpty() or (isinstance(wdg, QLabel) and not wdg.text() and not wdg.minimumWidth()):
                continue      # hidden widgets and empty labels take no room (unless they reserve it)
            hint = it.sizeHint()
            if isinstance(wdg, QLabel) and wdg.wordWrap() and wdg.text():
                # a wrap-able label asks to be narrow; on one line it's this wide
                m = wdg.contentsMargins()
                one = wdg.fontMetrics().size(Qt.TextSingleLine, wdg.text())
                hint = QSize(one.width() + m.left() + m.right() + 2 * wdg.margin() + 2,
                             one.height() + m.top() + m.bottom() + 2 * wdg.margin())
            peak = self._peak.get(id(it), QSize()).expandedTo(hint)
            self._peak[id(it)] = peak
            w = min(peak.width(), r.width())
            h = peak.height()
            if w < peak.width() and it.hasHeightForWidth():     # too wide for a line: word-wrap it
                h = max(hint.height(), it.heightForWidth(w))
            if x > r.x() and x + w > r.right() + 1:
                x, y, line_h = r.x(), y + line_h + self._v, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x += w + self._h
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()


class ElidedLabel(QLabel):
    """One line, always: text that doesn't fit ends in '…' (full text in the tooltip).
    Keeps its height fixed, so it never pushes what's below it down."""

    def setText(self, text: str):
        super().setText(text)
        self.setToolTip(text if text else self.property("baseTip") or "")

    def minimumSizeHint(self):
        return QSize(min(super().minimumSizeHint().width(), 40), super().minimumSizeHint().height())

    def paintEvent(self, ev):
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        r = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, r.width())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(r, int(self.alignment() | Qt.AlignVCenter), text)
