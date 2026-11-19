"""Score pane, laid out like N1MM's and Win-Test's: a band-by-band table with a
column per kind of multiplier, the totals, the claimed score in large type, and
what one more multiplier is worth in QSOs."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

SHORT = {"zones": "ZN", "cq zones": "ZN", "itu zones": "ITU", "countries": "Cty", "dxcc": "Cty",
         "states": "St", "sections": "Sec", "prefixes": "WPX", "provinces": "Prv", "counties": "Cnty",
         "states/prov": "S/P", "st/prov": "S/P", "na dxcc": "NA", "calls": "Calls"}
MONO = "'Menlo', 'Consolas', 'DejaVu Sans Mono', monospace"


def short_label(label: str) -> str:
    return SHORT.get(label.lower(), label[:4])


def score_text(engine, s) -> tuple[str, str, str]:
    """(table, score line, mult-value line) as plain text; empty lines when not used."""
    mult_labels = list(dict.fromkeys(m.get("label", m["type"]) for m in engine.rules.get("mults", [])))
    per_band = {m.get("label", m["type"]) for m in engine.rules.get("mults", [])
                if m.get("scope", "per_band") == "per_band"}
    general = engine.is_general
    cols = ["Band", "QSOs"] + ([] if general else ["Pts"]) + [short_label(l) for l in mult_labels]
    widths = [6, 6] + ([] if general else [7]) + [max(5, len(short_label(l)) + 2) for l in mult_labels]

    def line(vals, bold=False):
        out = vals[0].ljust(widths[0]) + "".join(str(v).rjust(w) for v, w in zip(vals[1:], widths[1:]))
        return out

    rows = [line(cols)]
    for band, b in s.by_band.items():
        if not b["qsos"]:
            continue
        vals = [band.removesuffix("m") if band != "70cm" else band, b["qsos"]]
        if not general:
            vals.append(b["points"])
        vals += [b.get("by_mult", {}).get(l, 0) if l in per_band else "" for l in mult_labels]
        rows.append(line(vals))
    tot = ["Total", s.qsos] + ([] if general else [s.points]) + \
        [len(s.mult_sets.get(l, ())) for l in mult_labels]
    rows.append(line(tot))
    table = "\n".join(rows)
    if general:
        return table, f"QSOs {s.qsos:,}  ·  DXCC {s.mults}", ""
    score = f"Score: {s.total:,}"
    worth = f"1 Mult = {s.qsos / s.mults:.1f} Q's" if s.mults else ""
    return table, score, worth


class ScorePane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(2)
        self.contest_lbl = QLabel()
        self.table_lbl = QLabel()
        self.table_lbl.setTextFormat(Qt.RichText)
        self.table_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.score_lbl = QLabel()
        self.score_lbl.setStyleSheet(f"font: bold 15pt {MONO};")
        self.score_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.worth_lbl = QLabel()
        self.worth_lbl.setStyleSheet(f"font: 10pt {MONO};")
        self.extra_lbl = QLabel()
        self.extra_lbl.setStyleSheet("color: gray; font-size: 9pt;")
        for w in (self.contest_lbl, self.table_lbl, self.score_lbl, self.worth_lbl, self.extra_lbl):
            v.addWidget(w)
        v.addStretch(1)
        self.table = ""

    def update_score(self, engine, s) -> None:
        if engine is None:
            for w in (self.contest_lbl, self.table_lbl, self.score_lbl, self.worth_lbl, self.extra_lbl):
                w.setText("")
            return
        self.contest_lbl.setText(f"Contest: {engine.rules.get('id', '')}")
        table, score, worth = score_text(engine, s)
        self.table = table
        lines = table.split("\n")
        html = "<br>".join(f"<b>{escape(l)}</b>" if i in (0, len(lines) - 1) else escape(l)
                           for i, l in enumerate(lines))
        self.table_lbl.setText(f"<span style=\"font-family: {MONO}; font-size: 11pt; white-space: pre;\">"
                               f"{html.replace(' ', '&nbsp;')}</span>")
        self.score_lbl.setText(score)
        self.worth_lbl.setText(worth)
        extra = []
        if s.dupes:
            extra.append(f"{s.dupes} dupe{'s' if s.dupes != 1 else ''}")
        if s.invalid:
            extra.append(f"{s.invalid} not counted")
        self.extra_lbl.setText(" · ".join(extra))
