"""The one window."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDockWidget, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import config
from ..contests.engine import ContestEngine, load_rules
from ..core.cty import DATA_DIR, CtyDat
from ..core.db import Log
from ..core.models import QSO, band_from_khz, utc_now
from ..export.adif import export_adif, import_adif
from ..export.cabrillo import export_cabrillo
from .dialogs import EditQsoDialog, MacroDialog, NewLogDialog, StationDialog

FIXTURE_CTY = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "cty_sample.dat"
FREQ_RE = re.compile(r"^\d{4,6}(\.\d)?$")

STYLE = """
QLabel#radio { font: bold 15pt; }
QLabel#score { font: bold 15pt; }
QLabel#banner { font: 12pt; padding: 3px; }
QLineEdit { font: 16pt "Menlo", "Consolas", monospace; padding: 2px; }
QPushButton { min-width: 78px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("tttlog")
        self.resize(1100, 720)
        self.setStyleSheet(STYLE)
        self.settings = QSettings("N3TTT", "tttlog")
        self.station = config.load_station()
        self.macros = config.load_macros()
        self.cty_missing = not (DATA_DIR / "cty.dat").exists()
        self.cty = CtyDat(FIXTURE_CTY if self.cty_missing else None)
        self.log: Log | None = None
        self.engine: ContestEngine | None = None
        self.qsos: list[QSO] = []
        self.freq_khz = float(self.settings.value("freq_khz", 14200.0))
        self.mode = "SSB"
        self.run_mode = True
        self.scp = self._load_scp()

        self._build_ui()
        self._build_menus()
        self._build_shortcuts()
        self._refresh_radio()

        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        st = self.settings.value("window_state")
        if st:
            self.restoreState(st)

        self.clock = QTimer(self, interval=1000, timeout=self._tick)
        self.clock.start()

        last = self.settings.value("last_log")
        if last and Path(last).exists():
            self.open_log(Path(last))
        if self.cty_missing:
            self.banner("cty.dat missing: run  python scripts/update_cty.py  (using small test file)", "orange")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        w = QWidget()
        v = QVBoxLayout(w)

        top = QHBoxLayout()
        self.radio_lbl = QLabel(objectName="radio")
        self.clock_lbl = QLabel()
        self.score_lbl = QLabel("Score 0", objectName="score")
        top.addWidget(self.radio_lbl); top.addStretch(); top.addWidget(self.clock_lbl)
        top.addStretch(); top.addWidget(self.score_lbl)
        v.addLayout(top)

        ent = QGridLayout()
        self.call = QLineEdit(placeholderText="CALL  (or type freq + Enter)")
        self.rst = QLineEdit("59"); self.rst.setMaximumWidth(70)
        self.exch = QLineEdit(placeholderText="EXCH")
        self.sent_lbl = QLabel()
        for c, (lbl, wid) in enumerate([("Call", self.call), ("RST", self.rst), ("Rcvd", self.exch)]):
            ent.addWidget(QLabel(lbl), 0, c)
            ent.addWidget(wid, 1, c)
        ent.addWidget(self.sent_lbl, 1, 3)
        ent.setColumnStretch(0, 3); ent.setColumnStretch(2, 2)
        v.addLayout(ent)
        for e in (self.call, self.rst, self.exch):
            e.returnPressed.connect(self.on_enter)
        self.call.textEdited.connect(self._on_call_edited)
        self.exch.textEdited.connect(lambda t: self.exch.setText(t.upper()))
        self.call.installEventFilter(self)
        self.exch.installEventFilter(self)

        self.banner_lbl = QLabel(objectName="banner")
        v.addWidget(self.banner_lbl)

        fk = QGridLayout()
        self.fbuttons = []
        for i in range(12):
            b = QPushButton()
            b.clicked.connect(lambda _=False, n=i: self.fkey(n))
            b.setFocusPolicy(Qt.NoFocus)
            fk.addWidget(b, i // 6, i % 6)
            self.fbuttons.append(b)
        v.addLayout(fk)
        self.tx_lbl = QLabel()
        v.addWidget(self.tx_lbl)
        v.addStretch()
        self.setCentralWidget(w)

        # Log pane
        self.log_table = QTableWidget(0, 8)
        self.log_table.setHorizontalHeaderLabels(["Time", "Call", "kHz", "Band", "Snt", "Rcv", "Country", "Pts"])
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.doubleClicked.connect(self.edit_selected)
        self._dock("Log", self.log_table, Qt.BottomDockWidgetArea)

        # Score pane
        self.score_table = QTableWidget(0, 4)
        self.score_table.setHorizontalHeaderLabels(["Band", "QSOs", "Pts", "Mults"])
        self.score_table.verticalHeader().setVisible(False)
        self.score_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.score_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.score_table.verticalHeader().setDefaultSectionSize(22)
        self._dock("Score", self.score_table, Qt.RightDockWidgetArea)

        # Partials pane (SCP + log)
        self.partials = QListWidget()
        self.partials.itemClicked.connect(lambda it: (self.call.setText(it.text()),
                                                      self._on_call_edited(it.text())))
        self._dock("Check Partial", self.partials, Qt.RightDockWidgetArea)

    def _dock(self, title, widget, area):
        d = QDockWidget(title, self, objectName=f"dock_{title}")
        d.setWidget(widget)
        self.addDockWidget(area, d)
        setattr(self, f"dock_{title.replace(' ', '_').lower()}", d)
        return d

    def _build_menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        for text, slot, key in [("New contest log…", self.new_log, "Ctrl+N"),
                                ("Open log…", self.open_log_dialog, "Ctrl+O"),
                                (None, None, None),
                                ("Import ADIF…", self.import_adif, None),
                                ("Export ADIF…", self.export_adif, None),
                                ("Export Cabrillo…", self.export_cabrillo, None),
                                (None, None, None),
                                ("Quit", self.close, "Ctrl+Q")]:
            if text is None:
                f.addSeparator(); continue
            a = QAction(text, self, triggered=slot)
            if key:
                a.setShortcut(QKeySequence(key))
            f.addAction(a)
        op = mb.addMenu("&Operating")
        op.addAction(QAction("Toggle Run / S&&P", self, shortcut="Ctrl+R", triggered=self.toggle_run))
        op.addAction(QAction("Set frequency…", self, shortcut="Ctrl+F", triggered=self.ask_freq))
        op.addAction(QAction("Mode SSB", self, triggered=lambda: self.set_mode("SSB")))
        op.addAction(QAction("Mode CW", self, triggered=lambda: self.set_mode("CW")))
        op.addAction(QAction("Delete selected QSO", self, shortcut="Ctrl+D", triggered=self.delete_selected))
        cfg = mb.addMenu("&Config")
        cfg.addAction(QAction("Station profile…", self, triggered=self.edit_station))
        cfg.addAction(QAction("Function-key macros…", self, triggered=self.edit_macros))
        view = mb.addMenu("&View")
        for d in (self.dock_log, self.dock_score, self.dock_check_partial):
            view.addAction(d.toggleViewAction())

    def _build_shortcuts(self):
        for i in range(12):
            QShortcut(QKeySequence(f"F{i + 1}"), self, activated=lambda n=i: self.fkey(n),
                      context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("Escape"), self, activated=self.wipe)

    def eventFilter(self, obj, ev):
        # Space in call field jumps to exchange (N1MM style)
        if ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key_Space:
            if obj is self.call:
                self._prefill(); self.exch.setFocus(); self.exch.selectAll(); return True
            if obj is self.exch and not self.exch.text().strip():
                self.call.setFocus(); return True
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------ helpers
    def banner(self, text, color=""):
        self.banner_lbl.setText(text)
        self.banner_lbl.setStyleSheet(f"background:{color}; color:{'black' if color else ''};")

    def _tick(self):
        self.clock_lbl.setText(utc_now().strftime("%H:%M:%S Z  %Y-%m-%d"))

    def _refresh_radio(self):
        band = band_from_khz(self.freq_khz) or "?"
        self.radio_lbl.setText(f"{self.freq_khz:,.1f} kHz  {band}  {self.mode}  "
                               f"[{'RUN' if self.run_mode else 'S&P'}]")
        page = self.macros.get(self.mode, self.macros.get("SSB"))["RUN" if self.run_mode else "SP"]
        for i, b in enumerate(self.fbuttons):
            m = page[i] if i < len(page) else {"label": ""}
            b.setText(f"F{i + 1} {m.get('label', '')}")
        if self.engine:
            self.sent_lbl.setText(f"Sent: {self.engine.default_rst()} {self.engine.sent_exchange()}")
        self.settings.setValue("freq_khz", self.freq_khz)

    def _load_scp(self) -> list[str]:
        p = DATA_DIR / "MASTER.SCP"
        if not p.exists():
            return []
        return [l.strip() for l in p.read_text(errors="ignore").splitlines()
                if l.strip() and not l.startswith("#")]

    # --------------------------------------------------------- log files
    def new_log(self):
        dlg = NewLogDialog(self)
        if not dlg.exec():
            return
        cid, path = dlg.values()
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.station.call in ("", "N0CALL"):
            self.edit_station()
        log = Log(path)
        log.set_meta("contest_id", cid)
        log.close()
        self.open_log(path)

    def open_log_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open log", str(Path.home() / "Documents" / "tttlog"),
                                           "Log (*.db)")
        if p:
            self.open_log(Path(p))

    def open_log(self, path: Path):
        if self.log:
            self.log.close()
        self.log = Log(path)
        cid = self.log.get_meta("contest_id", "ARRL-DX-SSB")
        rules = load_rules(cid)
        self.engine = ContestEngine(rules, self.cty, self.station)
        self.mode = rules["modes"][0]
        self.rst.setText(self.engine.default_rst())
        self.exch.setPlaceholderText(" ".join(f.get("label", f["name"]).upper()
                                              for f in self.engine.rcvd_fields))
        self.qsos = self.engine.rescore(self.log.all())
        self.settings.setValue("last_log", str(path))
        self.setWindowTitle(f"tttlog — {rules['name']} — {path.name}")
        self._refresh_radio()
        self._refresh_log()
        self.call.setFocus()

    # ----------------------------------------------------------- entry
    def _on_call_edited(self, text):
        up = text.upper()
        if up != text:
            pos = self.call.cursorPosition()
            self.call.setText(up)
            self.call.setCursorPosition(pos)
        self._live_check(up.strip())

    def _live_check(self, call):
        self._update_partials(call)
        if not self.engine or len(call) < 3 or FREQ_RE.match(call):
            self.banner("")
            return
        band = band_from_khz(self.freq_khz)
        hit = self.cty.lookup(call)
        where = f"{hit[0].name}  CQ{hit[1]}  {hit[0].continent}" if hit else "unknown prefix"
        if self.engine.is_dupe(call, band, self.mode, self.qsos):
            self.banner(f"DUPE on {band} — {where}", "#ff6b6b")
            return
        probe = self.engine.annotate(QSO(call=call, freq_khz=self.freq_khz, mode=self.mode), self.qsos)
        if not self.engine.is_valid(probe):
            self.banner(f"Not valid in this contest — {where}", "#ffd166")
            return
        new = self.engine.is_new_mult(probe, self.qsos)
        if new:
            self.banner(f"NEW MULT ({', '.join(new)}) — {where}", "#7bd389")
        else:
            self.banner(where)

    def _update_partials(self, call):
        self.partials.clear()
        if len(call) < 2 or FREQ_RE.match(call):
            return
        logged = {q.call for q in self.qsos}
        hits = [c for c in sorted(logged) if call in c][:20]
        hits += [c for c in self.scp if call in c and c not in logged][:40]
        self.partials.addItems(hits)

    def _prefill(self):
        if self.engine and not self.exch.text().strip() and self.call.text().strip():
            self.exch.setText(self.engine.prefill(self.call.text().strip()))

    def on_enter(self):
        call = self.call.text().strip().upper()
        # QSY by typing a frequency in the call field
        if FREQ_RE.match(call):
            self.set_freq(float(call))
            self.call.clear()
            return
        if not self.engine:
            self.banner("No log open — File ▸ New contest log", "#ffd166")
            return
        # ESM-lite
        if not call:
            self.fkey(0)                                  # CQ / MyCall
            return
        if not self.exch.text().strip():
            self._prefill()
            self.fkey(1)                                  # send exchange
            self.exch.setFocus()
            return
        errs = self.engine.validate_rcvd(self.exch.text())
        if errs:
            self.banner("; ".join(errs), "#ffd166")
            self.exch.setFocus()
            return
        self.log_qso()

    def log_qso(self):
        q = QSO(call=self.call.text().strip().upper(), freq_khz=self.freq_khz, mode=self.mode,
                rst_sent=self.engine.default_rst(), rst_rcvd=self.rst.text().strip() or "59",
                exch_sent=self.engine.sent_exchange(), exch_rcvd=self.exch.text().strip().upper(),
                station_call=self.station.call, operator=self.station.operator or self.station.call,
                contest_id=self.engine.rules["id"])
        self.engine.annotate(q, self.qsos)
        if self.run_mode:
            self.fkey(2)                                  # TU
        self.log.add(q)
        self.qsos.append(q)
        self._refresh_log()
        self.wipe()
        self.banner(f"Logged {q.call}  {q.country}  +{q.points}" + ("  (DUPE)" if q.is_dupe else ""))

    def wipe(self):
        self.call.clear(); self.exch.clear()
        if self.engine:
            self.rst.setText(self.engine.default_rst())
        self.partials.clear()
        self.call.setFocus()

    # ---------------------------------------------------------- macros
    def fkey(self, n: int):
        page = self.macros.get(self.mode, self.macros["SSB"])["RUN" if self.run_mode else "SP"]
        if n >= len(page):
            return
        m = page[n]
        if "{CLEAR}" in m.get("text", ""):
            self.wipe(); self.tx_lbl.setText(""); return
        exch = self.engine.sent_exchange() if self.engine else ""
        txt = config.expand(m.get("text", ""), self.station, self.call.text().strip().upper(),
                            exch, self.engine.default_rst() if self.engine else "59")
        wav = m.get("wav", "")
        # Rig/voice keyer output arrives in milestone M1; for now show what would be sent.
        self.tx_lbl.setText(f"TX F{n + 1}: {txt}" + (f"   [{wav}]" if wav and self.mode == "SSB" else ""))

    # ---------------------------------------------------------- radio
    def set_freq(self, khz: float):
        if band_from_khz(khz) is None:
            self.banner(f"{khz} kHz is outside the ham bands", "#ffd166")
            return
        self.freq_khz = khz
        self._refresh_radio()
        self._live_check(self.call.text().strip().upper())

    def ask_freq(self):
        khz, ok = QInputDialog.getDouble(self, "Frequency", "kHz", self.freq_khz, 1800, 450000, 1)
        if ok:
            self.set_freq(khz)

    def set_mode(self, mode):
        self.mode = mode
        self._refresh_radio()

    def toggle_run(self):
        self.run_mode = not self.run_mode
        self._refresh_radio()

    # ---------------------------------------------------------- log pane
    def _refresh_log(self):
        t = self.log_table
        t.setRowCount(len(self.qsos))
        for r, q in enumerate(self.qsos):
            vals = [q.time_utc.strftime("%m-%d %H:%M"), q.call, f"{q.freq_khz:.1f}", q.band or "",
                    f"{q.rst_sent} {q.exch_sent}", f"{q.rst_rcvd} {q.exch_rcvd}", q.country,
                    "DUPE" if q.is_dupe else str(q.points)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, q.id)
                t.setItem(r, c, it)
        t.scrollToBottom()
        if self.engine:
            s = self.engine.score(self.qsos)
            self.score_lbl.setText(f"Q {s.qsos}  Pts {s.points}  Mult {s.mults}  =  {s.total:,}")
            st = self.score_table
            st.setRowCount(len(s.by_band) + 1)
            for r, (band, b) in enumerate(s.by_band.items()):
                for c, v in enumerate([band, b["qsos"], b["points"], b["mults"]]):
                    st.setItem(r, c, QTableWidgetItem(str(v)))
            for c, v in enumerate(["Total", s.qsos, s.points, s.mults]):
                it = QTableWidgetItem(str(v)); f = QFont(); f.setBold(True); it.setFont(f)
                st.setItem(len(s.by_band), c, it)

    def _selected_qso(self) -> QSO | None:
        rows = self.log_table.selectionModel().selectedRows()
        if not rows:
            return None
        qid = self.log_table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((q for q in self.qsos if q.id == qid), None)

    def edit_selected(self):
        q = self._selected_qso()
        if not q:
            return
        dlg = EditQsoDialog(q, self)
        if dlg.exec():
            try:
                dlg.apply()
            except ValueError as e:
                QMessageBox.warning(self, "Edit", str(e)); return
            self._rescore_and_persist(self.qsos, always={q.id})

    def _rescore_and_persist(self, qsos: list[QSO], always: set = frozenset()):
        """Rescore, then write back only QSOs whose scoring changed (keeps the journal small)."""
        before = {q.id: (q.points, q.is_dupe, q.country, q.cq_zone) for q in qsos}
        self.qsos = self.engine.rescore(qsos)
        for q in self.qsos:
            if q.id in always or before.get(q.id) != (q.points, q.is_dupe, q.country, q.cq_zone):
                self.log.update(q)
        self._refresh_log()

    def delete_selected(self):
        q = self._selected_qso()
        if q and QMessageBox.question(self, "Delete", f"Delete {q.call} at {q.time_utc:%H:%M}?") \
                == QMessageBox.Yes:
            self.log.delete(q.id)
            self._rescore_and_persist([x for x in self.qsos if x.id != q.id])

    # ---------------------------------------------------------- config
    def edit_station(self):
        dlg = StationDialog(self.station, self)
        if dlg.exec():
            self.station = dlg.station()
            config.save_station(self.station)
            if self.engine:
                self.engine = ContestEngine(self.engine.rules, self.cty, self.station)
                self.qsos = self.engine.rescore(self.qsos)
                self._refresh_log()
            self._refresh_radio()

    def edit_macros(self):
        dlg = MacroDialog(self.macros, self)
        if dlg.exec():
            self.macros = dlg.result_macros()
            config.save_macros(self.macros)
            self._refresh_radio()

    # ---------------------------------------------------------- import/export
    def _need_log(self) -> bool:
        if not self.engine:
            QMessageBox.information(self, "tttlog", "Open or create a log first.")
            return False
        return True

    def export_adif(self):
        if not self._need_log():
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export ADIF", str(self.log.path.with_suffix(".adi")),
                                           "ADIF (*.adi *.adif)")
        if p:
            n = export_adif(self.qsos, p)
            self.banner(f"Exported {n} QSOs to {p}")

    def export_cabrillo(self):
        if not self._need_log():
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export Cabrillo", str(self.log.path.with_suffix(".log")),
                                           "Cabrillo (*.log *.cbr)")
        if p:
            n = export_cabrillo(self.qsos, self.engine, p,
                                category={"MODE": self.engine.rules["modes"][0]})
            self.banner(f"Exported {n} QSOs to {p} — check the CATEGORY lines before submitting")

    def import_adif(self):
        if not self._need_log():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Import ADIF", str(Path.home()), "ADIF (*.adi *.adif)")
        if not p:
            return
        for q in import_adif(p):
            q.contest_id = self.engine.rules["id"]
            self.log.add(q)
        self._rescore_and_persist(self.log.all())

    # ---------------------------------------------------------- close
    def closeEvent(self, ev):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        if self.log:
            self.log.close()
        super().closeEvent(ev)
