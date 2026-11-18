"""The one window."""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QMessageBox, QProgressDialog, QPushButton,
                               QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import config
from ..contests.engine import ContestEngine, load_rules
from ..core.cluster import (CLUSTER_KINDS, Home, describe_filter, detect_cluster_kind, filter_commands,
                            parse_spot, spot_command)
from .. import __version__, updater
from ..core.cty import CtyDat, USER_DATA_DIR, data_file, download_cty
from ..core.db import Log
from ..core.models import QSO, band_from_khz, utc_now
from ..core.netsync import LogSync
from ..export.adif import export_adif, import_adif, parse_adif
from ..export.cabrillo import export_cabrillo
from .cluster_pane import ClusterClient, SpotsPane, TelnetPane
from .dialogs import (ClusterDialog, EditQsoDialog, MacroDialog, NetworkDialog, NewLogDialog, WsjtxDialog,
                      StationDialog)
from .docks import Pane
from .needed_pane import NeededPane
from .network_pane import NetNode, NetworkPane
from .rate_pane import RatePane
from .wsjtx_listener import WsjtxListener

FIXTURE_CTY = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "cty_sample.dat"
DISPLAY_SIZES = (70, 80, 90, 100, 110, 125, 150)   # View ▸ Display size, % (applied at start)
LAYOUT_VERSION = "6"     # bump when panes are added/renamed so old saved layouts are dropped
FREQ_RE = re.compile(r"^\d{4,6}(\.\d)?$")
OP_RE = re.compile(r"^[A-Z0-9]{3,}(/[A-Z0-9]+)*$")

STYLE = """
QLabel#radio { font: bold 15pt; }
QLabel#score { font: bold 15pt; }
QLabel#banner { font: 12pt; padding: 3px; }
QLineEdit { font: 16pt "Menlo", "Consolas", monospace; padding: 2px; }
QPushButton { min-width: 78px; }
"""


class _Bridge(QObject):
    """Brings results from worker threads back to the GUI thread."""
    done = Signal(object, object)          # (callback, result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._bridge = _Bridge()
        self._bridge.done.connect(lambda cb, res: cb(res))
        self.setWindowTitle(f"tttlog {__version__}")
        self.resize(1100, 720)
        self.setStyleSheet(STYLE)
        self.settings = QSettings("N3TTT", "tttlog")
        self.station = config.load_station()
        self.macros = config.load_macros()
        self.cluster_cfg = config.load_cluster()
        self.colors = config.load_colors()
        self.net_cfg = config.load_network()
        self.wsjtx_cfg = config.load_wsjtx()
        self.node_id = config.node_id()
        self.sync: LogSync | None = None
        self.cty_missing = not data_file("cty.dat").exists()
        self.cty = CtyDat(FIXTURE_CTY if self.cty_missing else None)
        if not self.cty_missing and len(self.cty.entities()) < 100:   # damaged / not a cty.dat
            self.cty_missing = True
            self.cty = CtyDat(FIXTURE_CTY)
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
        elif self.screen() is not None:              # first run: use most of the screen
            avail = self.screen().availableGeometry()
            self.resize(int(avail.width() * 0.92), int(avail.height() * 0.9))
        self._fit_to_screen()
        st = self.settings.value("window_state")
        if str(self.settings.value("layout_version", "")) != LAYOUT_VERSION:
            st = None                                # panes changed: start from the default layout
        if st:
            self.restoreState(st)
        else:
            # Qt leaves a stray tab bar if two tab groups are made before the window
            # is first shown, so build the default tabs right after it appears.
            QTimer.singleShot(0, self._default_tabs)
        for d in self.panes:                       # popped-out panes get real window buttons
            if d.isFloating():
                d._on_top_level(True)

        self._ticks = 0
        self.clock = QTimer(self, interval=1000, timeout=self._tick)
        self.clock.start()

        last = self.settings.value("last_log")
        if last and Path(last).exists():
            self.open_log(Path(last))
        if self.cty_missing:
            self.banner("Country file missing or damaged: File ▸ Update country file  (using a small test file)", "orange")
        self._refresh_rates()
        if not (os.environ.get("TTTLOG_OFFLINE") or os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
            QTimer.singleShot(5000, self.auto_update_check)
        if self.cluster_cfg.get("auto_connect"):
            self.cluster_connect(True)
        if self.net_cfg.get("enabled"):
            self.net.start(self.net_cfg)
        if self.wsjtx_cfg.get("enabled"):
            self.wsjtx.start(self.wsjtx_cfg)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        w = QWidget()
        v = QVBoxLayout(w)

        top = QHBoxLayout()
        self.radio_lbl = QLabel(objectName="radio")
        self.clock_lbl = QLabel()
        self.score_lbl = QLabel("Score 0", objectName="score")
        for lbl in (self.radio_lbl, self.score_lbl):          # wrap rather than widen the window
            lbl.setWordWrap(True)
        self.wsjtx_lbl = QLabel(visible=False)
        top.addWidget(self.radio_lbl); top.addStretch(); top.addWidget(self.wsjtx_lbl)
        top.addWidget(self.clock_lbl)
        top.addStretch(); top.addWidget(self.score_lbl)
        v.addLayout(top)

        ent = QGridLayout()
        self.call = QLineEdit(placeholderText="CALL or kHz")
        self.call.setToolTip("Type a call, or a frequency in kHz + Enter to QSY")
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
            b.setStyleSheet("min-width: 30px")           # labels elide on a narrow pane
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            fk.addWidget(b, i // 6, i % 6)
            self.fbuttons.append(b)
        v.addLayout(fk)
        self.tx_lbl = QLabel()
        v.addWidget(self.tx_lbl)
        # The entry line is a pane too, sized to its contents. There is no central
        # widget: the window is two pane columns (left: Entry over Log + Spots,
        # right: Score / Check Partial / Rate). Don't use setCorner() here: with
        # no central widget it makes Qt widen the right column by a splitter
        # width on every re-layout (each keystroke), squeezing the other panes.
        v.setContentsMargins(8, 4, 8, 4)
        v.setSpacing(4)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setDockNestingEnabled(True)
        self._dock("Entry", w, Qt.LeftDockWidgetArea, closable=False, scroll=False)   # sized to its contents

        # Log pane
        self.log_table = QTableWidget(0, 9)
        self.log_table.setHorizontalHeaderLabels(["Time", "Call", "kHz", "Band", "Snt", "Rcv", "Country",
                                                  "Pts", "Stn"])
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.doubleClicked.connect(self.edit_selected)
        self._dock("Log", self.log_table, Qt.LeftDockWidgetArea)
        self.splitDockWidget(self.dock_entry, self.dock_log, Qt.Vertical)

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

        # Rate pane
        self.rate_pane = RatePane()
        self._dock("Rate", self.rate_pane, Qt.RightDockWidgetArea)

        # DX cluster: telnet client, Spots window (mults / Qs), Telnet window (raw text)
        self.cluster = ClusterClient(self)
        self.spots_pane = SpotsPane(self.colors)
        self.spots_pane.spots.max_age = timedelta(minutes=int(self.cluster_cfg.get("max_age_min", 30)))
        self.telnet_pane = TelnetPane()
        self.cluster.line.connect(self._on_cluster_line)
        self.cluster.state.connect(self._on_cluster_state)
        self.telnet_pane.connectRequested.connect(self.cluster_connect)
        self.telnet_pane.cmd.returnPressed.connect(self._cluster_cmd)
        self.spots_pane.spotActivated.connect(self.go_to_spot)
        self.spots_pane.colorsChanged.connect(self._save_colors)
        self.spots_pane.spotLastRequested.connect(self.spot_last_qso)
        self.spots_pane.auto_send_filter = bool(self.cluster_cfg.get("auto_send_filter"))
        self.spots_pane.set_filter(self.cluster_cfg.get("spot_filter"), self._home())
        self.spots_pane.filterChanged.connect(self._on_spot_filter_changed)
        self.spots_pane.filterSendRequested.connect(self.send_filter_to_cluster)
        self.cluster_kind = ""                      # detected from the login banner
        self._cl_out: list[str] = []               # cluster text waiting to go to networked stations
        self._cl_flush = QTimer(self, singleShot=True, interval=300, timeout=self._flush_cluster_share)
        self._spotted: set[tuple] = set()          # (call, band) we've spotted this session
        self._dock("Spots", self.spots_pane, Qt.LeftDockWidgetArea)
        self.splitDockWidget(self.dock_log, self.dock_spots, Qt.Horizontal)
        self._dock("Telnet", self.telnet_pane, Qt.LeftDockWidgetArea)
        self.splitDockWidget(self.dock_spots, self.dock_telnet, Qt.Horizontal)   # tabbed after show

        # Needed window: every mult x band, colored by need / spotted
        self.needed_pane = NeededPane(self.colors)
        self.needed_pane.spotActivated.connect(self.go_to_spot)
        self.needed_pane.colorsChanged.connect(self._save_colors)
        self._dock("Needed", self.needed_pane, Qt.RightDockWidgetArea)

        # Local network: share the log with other tttlog stations
        self.net = NetNode(self.node_id, self)
        self.network_pane = NetworkPane()
        self.net.logChanged.connect(lambda: self._net_dirty.isActive() or self._net_dirty.start())
        self.net.peersChanged.connect(self._refresh_network_pane)
        self.net.stateChanged.connect(lambda _t: self._refresh_network_pane())
        self.net.talkReceived.connect(self._on_talk)
        self.net.contestWarning.connect(self._on_contest_warning)
        self.net.clusterLines.connect(self._on_shared_cluster_lines)
        self.net.clusterCommand.connect(self._on_network_cluster_command)
        self.network_pane.talkSent.connect(self._send_talk)
        self._net_dirty = QTimer(self, singleShot=True, interval=300, timeout=self._on_net_log_changed)
        self._dock("Network", self.network_pane, Qt.RightDockWidgetArea)

        # WSJT-X / JTDX / MSHV: log what they log
        self.wsjtx = WsjtxListener(self)
        self.wsjtx.adifLogged.connect(self._on_wsjtx_logged)
        self.wsjtx.stateChanged.connect(self._on_wsjtx_state)

    def _dock(self, title, widget, area, closable=True, scroll=True):
        d = Pane(title, widget, self, closable=closable, scroll=scroll)
        self.addDockWidget(area, d)
        setattr(self, f"dock_{title.replace(' ', '_').lower()}", d)
        return d

    def _build_menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        for text, slot, key in [("New log (contest or general)…", self.new_log, "Ctrl+N"),
                                ("Open log…", self.open_log_dialog, "Ctrl+O"),
                                (None, None, None),
                                ("Import ADIF…", self.import_adif, None),
                                ("Export ADIF…", self.export_adif, None),
                                ("Export Cabrillo…", self.export_cabrillo, None),
                                (None, None, None),
                                ("Update country file (cty.dat)", self.update_cty, None),
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
        op.addAction(QAction("Operator on (OPON)…", self, shortcut="Ctrl+Shift+O",
                             triggered=lambda: self.opon()))
        self.mode_menu = op.addMenu("Mode")
        self._build_mode_menu(["SSB", "CW"])
        op.addAction(QAction("Delete selected QSO", self, shortcut="Ctrl+D", triggered=self.delete_selected))
        cfg = mb.addMenu("&Config")
        cfg.addAction(QAction("Station profile…", self, triggered=self.edit_station))
        cfg.addAction(QAction("Function-key macros…", self, triggered=self.edit_macros))
        cfg.addAction(QAction("DX cluster…", self, triggered=self.edit_cluster))
        cfg.addAction(QAction("Local network…", self, triggered=self.edit_network))
        cfg.addAction(QAction("WSJT-X…", self, triggered=self.edit_wsjtx))
        cl = mb.addMenu("C&luster")
        cl.addAction(QAction("Connect / disconnect", self, shortcut="Ctrl+K",
                             triggered=lambda: self.cluster_connect(not self.cluster._want)))
        cl.addAction(QAction("Show needed (mults + Qs)", self, shortcut="Ctrl+Shift+N",
                             triggered=lambda: self.spots_pane.show_only("spot_mult", "spot_q")))
        cl.addAction(QAction("Show mults only", self, shortcut="Ctrl+Shift+M",
                             triggered=lambda: self.spots_pane.show_only("spot_mult")))
        cl.addAction(QAction("Show all spots", self, shortcut="Ctrl+Shift+A",
                             triggered=lambda: self.spots_pane.show_only("spot_mult", "spot_q", "spot_dupe")))
        cl.addAction(QAction("Spot last QSO", self, shortcut="Ctrl+Shift+S",
                             triggered=self.spot_last_qso))
        self.auto_spot_action = QAction("Auto-spot S&&P QSOs", self, checkable=True,
                                        checked=bool(self.cluster_cfg.get("auto_spot_sp")),
                                        toggled=self._set_auto_spot)
        cl.addAction(self.auto_spot_action)
        cl.addSeparator()
        cl.addAction(QAction("Go to newest needed spot", self, shortcut="Ctrl+G",
                             triggered=self.go_to_next_needed))
        cl.addAction(QAction("Search spots", self, shortcut="Ctrl+Shift+F",
                             triggered=self._focus_spot_search))
        cl.addSeparator()
        cl.addAction(QAction("Spotters: anywhere → my zone → my continent", self, shortcut="Ctrl+Shift+J",
                             triggered=self.spots_pane.cycle_spotters))
        cl.addAction(QAction("Skimmers: all → none → only", self, shortcut="Ctrl+Shift+K",
                             triggered=self.spots_pane.cycle_skimmer))
        cl.addAction(QAction("Send spot filter to the cluster", self, shortcut="Ctrl+Shift+L",
                             triggered=self.send_filter_to_cluster))
        cl.addAction(QAction("Show the cluster's filter (sh/filter)", self,
                             triggered=lambda: self._cluster_command("sh/filter")))
        view = mb.addMenu("&View")
        for d in self.panes:
            view.addAction(d.toggleViewAction())
        view.addSeparator()
        view.addAction(QAction("Minimize all panes", self, shortcut="Ctrl+Shift+H",
                               triggered=self.minimize_all_panes))
        view.addAction(QAction("Restore all panes", self, shortcut="Ctrl+Shift+R",
                               triggered=self.restore_all_panes))
        view.addAction(QAction("Dock all pop-out windows", self, triggered=self.dock_all_panes))
        view.addSeparator()
        self.scale_menu = view.addMenu("Display size")
        cur = int(self.settings.value("ui_scale", 100) or 100)
        for pct in DISPLAY_SIZES:
            a = QAction(f"{pct}%" + ("  (normal)" if pct == 100 else ""), self, checkable=True,
                        checked=pct == cur, triggered=lambda _=False, p=pct: self.set_display_size(p))
            a.setData(pct)
            self.scale_menu.addAction(a)
        hlp = mb.addMenu("&Help")
        hlp.addAction(QAction("Check for updates…", self, triggered=lambda: self.check_updates(quiet=False)))
        hlp.addAction(QAction("tttlog on GitHub", self, triggered=lambda: QDesktopServices.openUrl(
            QUrl(f"https://github.com/{updater.REPO}"))))
        hlp.addAction(QAction("About tttlog…", self, triggered=self.show_about))

    def _build_mode_menu(self, modes):
        self.mode_menu.clear()
        for m in modes:
            self.mode_menu.addAction(QAction(m, self, triggered=lambda _=False, m=m: self.set_mode(m)))

    def _build_shortcuts(self):
        for i in range(12):
            QShortcut(QKeySequence(f"F{i + 1}"), self, activated=lambda n=i: self.fkey(n),
                      context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("Escape"), self, activated=self.wipe)
        # When the Entry pane is popped out it's a separate window, so it needs its
        # own Escape (enabled only then, or the two would clash).
        esc = QShortcut(QKeySequence("Escape"), self.dock_entry, activated=self.wipe,
                        context=Qt.WidgetWithChildrenShortcut)
        esc.setEnabled(False)
        self.dock_entry.topLevelChanged.connect(esc.setEnabled)

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
        now = utc_now()
        self.clock_lbl.setText(now.strftime("%H:%M:%S Z  %Y-%m-%d"))
        self._ticks += 1
        if self._ticks % 15 == 0:                 # rolling rates + spot ageing
            self._refresh_rates(now)
            if self.spots_pane.prune(now):
                self._refresh_needed()

    def _refresh_rates(self, now=None):
        self.rate_pane.update_rates(self.qsos, self.engine, now or utc_now(), me=self.current_op)

    def _refresh_radio(self):
        band = band_from_khz(self.freq_khz) or "?"
        self.radio_lbl.setText(f"{self.freq_khz:,.1f} kHz  {band}  {self.mode}  "
                               f"[{'RUN' if self.run_mode else 'S&P'}]  OP {self.current_op}")
        page = self.macros.get(self.mode, self.macros.get("SSB"))["RUN" if self.run_mode else "SP"]
        for i, b in enumerate(self.fbuttons):
            m = page[i] if i < len(page) else {"label": ""}
            b.setText(f"F{i + 1} {m.get('label', '')}"); b.setToolTip(b.text())
        if self.engine:
            self.sent_lbl.setText(f"Sent: {self.engine.default_rst(self.mode)} {self.engine.sent_exchange()}")
        self.settings.setValue("freq_khz", self.freq_khz)
        self._push_net_status()
        if hasattr(self, "spots_pane") and self.spots_pane.current_band != band:
            self.spots_pane.current_band = band
            self.spots_pane.refresh()

    def _load_scp(self) -> list[str]:
        p = data_file("MASTER.SCP")
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
        self._build_mode_menu(rules["modes"])
        self.rst.setText(self.engine.default_rst(self.mode))
        self.exch.setPlaceholderText(" ".join(f.get("label", f["name"]).upper()
                                              for f in self.engine.rcvd_fields))
        general = self.engine.is_general
        for c in (2, 3):                              # no points or band mults in a general log
            self.score_table.setColumnHidden(c, general)
        self.sync = LogSync(self.log, self.node_id, self.net_cfg["station_name"])
        self.net.set_log(self.sync, cid)
        self.qsos = self.engine.rescore(self.log.all())
        self.needed_pane.set_engine(self.engine)
        self.settings.setValue("last_log", str(path))
        self.setWindowTitle(f"tttlog {__version__} — {rules['name']} — {path.name}")
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
        if self.engine.is_general:
            self._general_check(call, hit, where)
            return
        if self.engine.is_dupe(call, band, self.mode, self.qsos):
            by = next((q.station_name for q in reversed(self.qsos) if q.call == call and q.band == band
                       and q.station_name and q.station_name != self.net_cfg["station_name"]), "")
            self.banner(f"DUPE on {band}" + (f" (worked by {by})" if by else "") + f" — {where}", "#ff6b6b")
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

    def _general_check(self, call, hit, where):
        """General log: no dupes; say if it's a new country or worked before."""
        before = self.engine.worked_before(call, self.qsos)
        probe = self.engine.annotate(QSO(call=call, freq_khz=self.freq_khz, mode=self.mode), self.qsos)
        new = self.engine.is_new_mult(probe, self.qsos) if hit else []
        if before:
            last = before[0]
            self.banner(f"Worked {len(before)}× — last {last.time_utc:%Y-%m-%d} {last.band or ''} "
                        f"{last.mode} {last.exch_rcvd}".rstrip() + f" — {where}", "#bde0fe")
        elif new:
            self.banner(f"NEW ONE ({', '.join(new)}) — {where}", "#7bd389")
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
        if call == "OPON" or call.startswith("OPON "):     # OPON [call] + Enter: change operator
            self.call.clear()
            self.opon(call[5:].strip())
            return
        modes = self.engine.rules["modes"] if self.engine else ["SSB", "CW"]
        if call in modes:                                 # type CW / SSB / FT8 + Enter to change mode
            self.set_mode(call)
            self.call.clear()
            return
        if not self.engine:
            self.banner("No log open — File ▸ New log", "#ffd166")
            return
        # ESM-lite
        if not call:
            self.fkey(0)                                  # CQ / MyCall
            return
        if not self.exch.text().strip() and self.engine.exchange_required():
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
                rst_sent=self.engine.default_rst(self.mode),
                rst_rcvd=self.rst.text().strip() or self.engine.default_rst(self.mode),
                exch_sent=self.engine.sent_exchange(), exch_rcvd=self.exch.text().strip().upper(),
                station_call=self.station.call, operator=self.current_op,
                contest_id=self.engine.rules["id"])
        self.engine.annotate(q, self.qsos)
        if self.run_mode:
            self.fkey(2)                                  # TU
        self.net.publish(self.sync.local_put(q))
        self.qsos.append(q)
        self._refresh_log()
        self.wipe()
        if self.engine.is_general:
            self.banner(f"Logged {q.call}  {q.country}  {q.band} {q.mode}")
        else:
            self.banner(f"Logged {q.call}  {q.country}  +{q.points}" + ("  (DUPE)" if q.is_dupe else ""))
        if (not self.run_mode and not q.is_dupe and self.cluster_cfg.get("auto_spot_sp")
                and self._cluster_ready() and (q.call, q.band) not in self._spotted):
            self.spot_qso(q, auto=True)

    def wipe(self):
        self.call.clear(); self.exch.clear()
        if self.engine:
            self.rst.setText(self.engine.default_rst(self.mode))
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
        if "{SPOT}" in m.get("text", ""):
            if self.spot_last_qso():
                self.tx_lbl.setText(f"F{n + 1}: spotted last QSO to the cluster")
            return
        exch = self.engine.sent_exchange() if self.engine else ""
        txt = config.expand(m.get("text", ""), self.station, self.call.text().strip().upper(),
                            exch, self.engine.default_rst(self.mode) if self.engine else "59")
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
        old = self.engine.default_rst(self.mode) if self.engine else "59"
        self.mode = mode
        if self.engine and self.rst.text().strip() in ("", old):   # 59 <-> 599 unless typed
            self.rst.setText(self.engine.default_rst(mode))
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
                    "DUPE" if q.is_dupe else str(q.points), q.station_name]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, q.id)
                t.setItem(r, c, it)
        t.scrollToBottom()
        if self.engine:
            s = self.engine.score(self.qsos)
            if self.engine.is_general:
                self.score_lbl.setText(f"QSOs {s.qsos}  ·  DXCC {s.mults}")
            else:
                self.score_lbl.setText(f"Q {s.qsos}  Pts {s.points}  Mult {s.mults}  =  {s.total:,}")
            st = self.score_table
            st.setRowCount(len(s.by_band) + 1)
            for r, (band, b) in enumerate(s.by_band.items()):
                for c, v in enumerate([band, b["qsos"], b["points"], b["mults"]]):
                    st.setItem(r, c, QTableWidgetItem(str(v)))
            for c, v in enumerate(["Total", s.qsos, s.points, s.mults]):
                it = QTableWidgetItem(str(v)); f = QFont(); f.setBold(True); it.setFont(f)
                st.setItem(len(s.by_band), c, it)
        self._refresh_rates()
        self.spots_pane.reevaluate(self.engine, self.qsos)
        self._refresh_needed()
        self._push_net_status()

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
            self.net.publish(self.sync.local_put(q))
            self._rescore_and_persist(self.qsos)

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
            self.net.publish(self.sync.local_delete(q))
            self._rescore_and_persist([x for x in self.qsos if x.id != q.id])

    # ---------------------------------------------------------- config
    @property
    def current_op(self) -> str:
        """Who is operating this computer right now (OPON), else the station's operator."""
        return (str(self.settings.value("current_op", "") or "")
                or self.station.operator or self.station.call)

    def opon(self, op: str = "") -> bool:
        """Set the operator logged on new QSOs from this computer (type OPON in the call field)."""
        if not op:
            op, ok = QInputDialog.getText(self, "Operator on", "Operator callsign:", text=self.current_op)
            if not ok:
                return False
        op = op.strip().upper()
        if not OP_RE.match(op):
            self.banner(f"OPON: '{op}' doesn't look like a callsign", "#ffd166")
            return False
        self.settings.setValue("current_op", op)
        self._refresh_radio()
        self._push_net_status()
        self._refresh_rates()
        self.banner(f"Operator is now {op}")
        self.call.setFocus()
        return True

    def edit_station(self):
        dlg = StationDialog(self.station, self)
        if dlg.exec():
            self.station = dlg.station()
            config.save_station(self.station)
            if self.engine:
                self.engine = ContestEngine(self.engine.rules, self.cty, self.station)
                self.needed_pane.set_engine(self.engine)
                self.qsos = self.engine.rescore(self.qsos)
                self._refresh_log()
            self._refresh_radio()
            self.spots_pane.set_filter(self.spots_pane.spot_filter, self._home())

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
        if self.engine.is_general:
            QMessageBox.information(self, "Export Cabrillo",
                                    "Cabrillo is for contest logs. Use File ▸ Export ADIF for a general log.")
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
        with self.sync.bulk():
            for q in import_adif(p, general=self.engine.is_general):
                q.contest_id = self.engine.rules["id"]
                self.net.publish(self.sync.local_put(q))
        self._rescore_and_persist(self.log.all())

    # ---------------------------------------------------------- DX cluster
    def cluster_connect(self, on: bool):
        if not on:
            self.cluster.disconnect_from()
            return
        cfg = self.cluster_cfg
        login = cfg.get("login") or self.station.call
        if not cfg.get("host") or login in ("", "N0CALL"):
            self.banner("Set your call (Config ▸ Station profile) and cluster host (Config ▸ DX cluster)",
                        "#ffd166")
            return
        self.cluster.connect_to(cfg["host"], cfg.get("port", 7373), login, cfg.get("init_commands"))

    def _on_cluster_state(self, text: str):
        self.telnet_pane.set_connected(self.cluster._want, text)
        # tell networked stations whether they can use our connection
        QTimer.singleShot(0, lambda: self.net.set_cluster_up(
            self.cluster.is_connected() and bool(self.cluster_cfg.get("share_cluster", True))))
        if not self.cluster._want:
            QTimer.singleShot(0, self._show_cluster_source)

    def _on_cluster_line(self, text: str):
        """A line from our own cluster connection."""
        if not self.cluster_kind:
            self.cluster_kind = detect_cluster_kind(text)
        self._take_cluster_text(text)
        if self.net.running and self.cluster_cfg.get("share_cluster", True):
            self._cl_out.append(text)
            if not self._cl_flush.isActive():
                self._cl_flush.start()

    def _take_cluster_text(self, text: str):
        self.telnet_pane.append_console(text)
        s = parse_spot(text, utc_now())
        if s:
            self.spots_pane.add_spot(s, self.engine, self.qsos)
            self._refresh_needed()

    # -- shared cluster connection over the local network --------------------
    def _flush_cluster_share(self):
        lines, self._cl_out = self._cl_out[:200], self._cl_out[200:]
        self.net.publish_cluster(lines)
        if self._cl_out:
            self._cl_flush.start()

    def _using_network_cluster(self) -> dict | None:
        """The networked station whose cluster we're using, if we are."""
        if self.cluster.is_connected() or self.cluster._want or not self.cluster_cfg.get("use_network_cluster", True):
            return None
        return self.net.cluster_source() if self.net.running else None

    def _on_shared_cluster_lines(self, src: str, lines: list):
        if not self._using_network_cluster():
            return
        if not self.cluster_kind:
            self.cluster_kind = next((k for k in map(detect_cluster_kind, lines) if k), "")
        for text in lines:
            self._take_cluster_text(text)

    def _on_network_cluster_command(self, who: str, text: str):
        if self.cluster.is_connected() and self.cluster_cfg.get("share_cluster", True):
            self.cluster.send(text)
            self.telnet_pane.append_console(f"> {text}   (from {who})")

    def _show_cluster_source(self):
        if self.cluster._want:
            return
        src = self._using_network_cluster()
        self.telnet_pane.set_connected(False, f"Using {src['name']}'s cluster connection (local network)"
                                       if src else "Not connected")

    def _cluster_ready(self) -> bool:
        return self.cluster.is_connected() or self._using_network_cluster() is not None

    def _cluster_command(self, cmd: str) -> bool:
        """Send to the cluster: our own connection, or a networked station's."""
        if self.cluster.is_connected():
            self.cluster.send(cmd)
            self.telnet_pane.append_console(f"> {cmd}")
            return True
        src = self._using_network_cluster()
        if src and self.net.send_cluster_command(cmd):
            self.telnet_pane.append_console(f"> {cmd}   (via {src['name']})")
            return True
        self.banner("Not connected to the DX cluster (Ctrl+K), and no networked station is sharing one",
                    "#ffd166")
        return False

    # -- spot filter ---------------------------------------------------------
    def _home(self) -> Home:
        hit = self.cty.lookup(self.station.call) if self.station.call not in ("", "N0CALL") else None
        return Home(zone=self.station.cq_zone, cont=hit[0].continent if hit else "",
                    country=hit[0].name if hit else "", prefix=hit[0].prefix if hit else "")

    def _on_spot_filter_changed(self):
        self.cluster_cfg["spot_filter"] = dict(self.spots_pane.spot_filter)
        self.cluster_cfg["auto_send_filter"] = self.spots_pane.auto_send_filter
        config.save_cluster(self.cluster_cfg)
        self._refresh_needed()
        desc = describe_filter(self.spots_pane.spot_filter, self.spots_pane.home)
        self.banner(f"Spot filter: {desc or 'showing all spotters and skimmers'}")

    def send_filter_to_cluster(self):
        kind = self.cluster_cfg.get("cluster_type", "auto")
        kind = self.cluster_kind if kind == "auto" else kind
        if not self._cluster_ready():
            self.banner("Not connected to the DX cluster (Ctrl+K), and no networked station is sharing one",
                        "#ffd166")
            return
        cmds, notes = filter_commands(kind, self.spots_pane.spot_filter, self.spots_pane.home)
        for i, c in enumerate(cmds):              # spaced out: some nodes drop commands sent together
            QTimer.singleShot(700 * i, lambda c=c: self._cluster_command(c))
        name = CLUSTER_KINDS.get(kind, "")
        msg = (f"Sent filter to {name}: " + " · ".join(cmds)) if cmds else "Filter kept here only"
        self.banner(msg + ("  —  " + "; ".join(notes) if notes else ""), "#ffd166" if notes else "")

    def spot_qso(self, q: QSO, auto: bool = False) -> bool:
        """Send call + frequency of q to the cluster."""
        if not self._cluster_ready():
            self.banner("Not connected to the DX cluster (Ctrl+K to connect)", "#ffd166")
            return False
        try:
            cmd = spot_command(q.call, q.freq_khz)
        except ValueError as e:
            self.banner(f"Can't spot: {e}", "#ffd166")
            return False
        if not self._cluster_command(cmd):
            return False
        self._spotted.add((q.call, q.band))
        keep = self.banner_lbl.text() + "  ·  " if auto else ""
        self.banner(f"{keep}Spotted {q.call} on {q.freq_khz:.1f}" + (" (auto)" if auto else ""))
        return True

    def spot_last_qso(self) -> bool:
        if not self.qsos:
            self.banner("No QSOs logged yet", "#ffd166")
            return False
        last = max(self.qsos, key=lambda x: (x.time_utc, x.id or 0))
        return self.spot_qso(last)

    def _set_auto_spot(self, on: bool):
        self.cluster_cfg["auto_spot_sp"] = bool(on)
        config.save_cluster(self.cluster_cfg)

    def _cluster_cmd(self):
        cmd = self.telnet_pane.cmd.text().strip()
        if cmd:
            self._cluster_command(cmd)
        self.telnet_pane.cmd.clear()

    def go_to_spot(self, s):
        """QSY to a spot and put the call in the entry line (S&P)."""
        if self.engine and s.mode in self.engine.rules.get("modes", []) and s.mode != self.mode:
            self.mode = s.mode
        self.run_mode = False
        self.set_freq(s.freq_khz)
        self.wipe()
        self.call.setText(s.call)
        self._on_call_edited(s.call)

    def go_to_next_needed(self):
        """Jump to the newest mult spot, or the newest needed Q if no mults."""
        spots = [s for s in self.spots_pane.spots.spots()
                 if not (self.spots_pane.band_box.currentIndex() == 1
                         and s.band != self.spots_pane.current_band)]
        pick = next((s for s in spots if s.status == "MULT"), None) or \
            next((s for s in spots if s.status == "Q"), None)
        if pick:
            self.go_to_spot(pick)
        else:
            self.banner("No needed spots in the current filter")

    def _focus_spot_search(self):
        self.dock_spots.show(); self.dock_spots.raise_()
        self.dock_spots.set_minimized(False)
        self.spots_pane.search.setFocus(); self.spots_pane.search.selectAll()

    def edit_cluster(self):
        dlg = ClusterDialog(self.cluster_cfg, self.station.call, self)
        if dlg.exec():
            self.cluster_cfg = dlg.values()
            config.save_cluster(self.cluster_cfg)
            self.auto_spot_action.setChecked(bool(self.cluster_cfg.get("auto_spot_sp")))
            self.spots_pane.spots.max_age = timedelta(minutes=int(self.cluster_cfg["max_age_min"]))
            if self.cluster._want:                  # reconnect with the new settings
                self.cluster_connect(True)

    def _refresh_needed(self):
        self.needed_pane.update_data(self.qsos, self.spots_pane.filtered_spots())

    def _save_colors(self):
        config.save_colors(self.colors)

    # ---------------------------------------------------------- local network
    def edit_network(self):
        dlg = NetworkDialog(self.net_cfg, self.net.port, self)
        if not dlg.exec():
            return
        self.net_cfg = dlg.values()
        config.save_network(self.net_cfg)
        if self.sync:
            self.sync.station_name = self.net_cfg["station_name"]
        if self.net_cfg["enabled"]:
            self.net.start(self.net_cfg)
            self._push_net_status()
        else:
            self.net.stop()
        self._refresh_network_pane()

    # ---------------------------------------------------------- WSJT-X
    def edit_wsjtx(self):
        dlg = WsjtxDialog(self.wsjtx_cfg, self.wsjtx.state if self.wsjtx.is_listening() else "", self)
        if not dlg.exec():
            return
        self.wsjtx_cfg = dlg.values()
        config.save_wsjtx(self.wsjtx_cfg)
        if self.wsjtx_cfg["enabled"]:
            self.wsjtx.start(self.wsjtx_cfg)
        else:
            self.wsjtx.stop()

    def _on_wsjtx_state(self, text: str):
        on = text != "off"
        self.wsjtx_lbl.setVisible(on)
        ok = text.startswith("connected")
        self.wsjtx_lbl.setText(("● " if ok else "○ ") + "WSJT-X")
        self.wsjtx_lbl.setStyleSheet(f"color: {'#2a9d4b' if ok else '#c77d00'}; font-weight: bold;")
        self.wsjtx_lbl.setToolTip(f"WSJT-X: {text}  (Config ▸ WSJT-X)")

    def _on_wsjtx_logged(self, adif: str, peer: str):
        """WSJT-X logged a QSO: put it in this log (and share it)."""
        qsos = parse_adif(adif, general=bool(self.engine and self.engine.is_general))
        if not qsos:
            return
        if not self.engine or not self.sync:
            self.banner(f"{peer} logged {qsos[0].call}, but no log is open here — File ▸ Open log", "#ffd166")
            return
        for q in qsos:
            if self._already_logged(q):
                self.banner(f"{peer}: {q.call} on {q.band} {q.mode} is already in the log")
                continue
            if not q.freq_khz:
                q.freq_khz = self.freq_khz
            q.contest_id = self.engine.rules["id"]
            q.station_call = q.station_call or self.station.call
            q.operator = q.operator or self.current_op
            q.rst_sent = q.rst_sent or self.engine.default_rst(q.mode)
            q.rst_rcvd = q.rst_rcvd or self.engine.default_rst(q.mode)
            if not self.engine.is_general and not q.exch_sent:
                q.exch_sent = self.engine.sent_exchange()
            self.engine.annotate(q, self.qsos)
            self.net.publish(self.sync.local_put(q))
            self.qsos.append(q)
            warn = "" if q.mode in self.engine.rules["modes"] else f"  ({q.mode} isn't a mode in this contest)"
            self._refresh_log()
            self.banner(f"From {peer}: logged {q.call}  {q.country}  {q.band} {q.mode}"
                        + ("  (DUPE)" if q.is_dupe else "") + warn, "#ffd166" if warn else "")

    def _already_logged(self, q: QSO) -> bool:
        """WSJT-X can send the same QSO again (re-log, restart): skip near-identical ones."""
        return any(x.call == q.call and x.band == q.band and x.mode == q.mode
                   and abs((x.time_utc - q.time_utc).total_seconds()) < 120 for x in self.qsos)

    def _on_net_log_changed(self):
        """QSOs came in from other stations: rescore everything and redraw."""
        if not self.log:
            return
        self._rescore_and_persist(self.log.all())
        call = self.call.text().strip().upper()
        if call:
            self._live_check(call)                    # someone else may have just worked it

    def _push_net_status(self):
        if not hasattr(self, "net"):
            return
        me = self.net_cfg.get("station_name", "")
        self.net.set_status({"op": self.current_op,
                             "band": band_from_khz(self.freq_khz), "freq": self.freq_khz,
                             "mode": self.mode, "run": self.run_mode,
                             "qsos": sum(1 for q in self.qsos if q.station_name == me)})
        self._refresh_network_pane()

    def _refresh_network_pane(self):
        me = {"name": self.net_cfg.get("station_name", ""), "status": dict(self.net.status), "direct": True}
        peers = [{**p, "warn": self.net.mismatch(p) if p.get("contest") or p.get("direct") else ""}
                 for p in self.net.peers.values()] if self.net.running else []
        self._show_cluster_source()
        self.network_pane.refresh(me, peers,
                                  self.net.summary() if self.net.running
                                  else "Network off — Config ▸ Local network")

    def _send_talk(self, text: str):
        if not self.net.running:
            self.banner("Network is off — Config ▸ Local network", "#ffd166")
            return
        self.net.talk(text)
        self.network_pane.add_talk(self.net_cfg["station_name"], text)

    def _on_contest_warning(self, text: str):
        self.network_pane.add_talk("network", "⚠ " + text)
        self.banner("⚠ " + text, "orange")

    def _on_talk(self, who: str, text: str):
        self.network_pane.add_talk(who, text)
        self.banner(f"{who}: {text}", "#bde0fe")

    # ---------------------------------------------------------- data files / about
    def update_cty(self):
        self.banner("Downloading the latest country file…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            path = download_cty()
            self.cty = CtyDat(path)
            self.cty_missing = False
        except Exception as e:                       # network down, bad file, ...
            QApplication.restoreOverrideCursor()
            self.banner(f"Couldn't update the country file: {e}", "#ffd166")
            return
        QApplication.restoreOverrideCursor()
        if self.engine:
            self.engine = ContestEngine(self.engine.rules, self.cty, self.station)
            self.needed_pane.set_engine(self.engine)
            self.qsos = self.engine.rescore(self.qsos)
            self._refresh_log()
        self.spots_pane.spots._spotter_cache.clear()
        self.spots_pane.set_filter(self.spots_pane.spot_filter, self._home())
        self.banner(f"Country file updated ({len(self.cty.entities())} entities)")

    def show_about(self):
        import platform
        logs = self.log.path.parent if self.log else Path.home() / "Documents" / "tttlog"
        QMessageBox.about(self, "About tttlog", (
            f"<b>tttlog {updater.version_string()}</b> (alpha)<br>"
            f"Amateur radio contest logger<br><br>"
            f"Logs: {logs}<br>"
            f"Settings: {config.CONFIG_DIR}<br>"
            f"Country file: {data_file('cty.dat')}<br><br>"
            f"{platform.system()} {platform.release()} · Python {platform.python_version()}<br>"
            f"Please include this information in bug reports."))

    # ---------------------------------------------------------- updates
    def _bg(self, fn, callback):
        """Run fn() off the GUI thread; callback(result or exception) runs on the GUI thread."""
        def work():
            try:
                res = fn()
            except Exception as e:                   # noqa: BLE001
                res = e
            self._bridge.done.emit(callback, res)
        threading.Thread(target=work, daemon=True).start()

    def auto_update_check(self):
        """Quiet check at most once a day; only speaks up if there's something new."""
        if time.time() - float(self.settings.value("last_update_check", 0) or 0) < 86400:
            return
        self.settings.setValue("last_update_check", time.time())
        self.check_updates(quiet=True)

    def check_updates(self, quiet: bool):
        def done(rel):
            if isinstance(rel, Exception) or rel is None:
                if not quiet:
                    QMessageBox.warning(self, "Check for updates",
                                        f"Couldn't reach GitHub: {rel or 'no releases yet'}")
                return
            if not updater.is_newer(rel.version):
                if not quiet:
                    QMessageBox.information(self, "Check for updates",
                                            f"You're up to date: tttlog {__version__}.")
                return
            box = QMessageBox(self)
            box.setWindowTitle("Update available")
            box.setText(f"<b>tttlog {rel.version}</b> is available. You have {__version__}.")
            notes = rel.notes.strip()
            box.setInformativeText(notes[:900] + ("…" if len(notes) > 900 else ""))
            go = box.addButton("Update now", QMessageBox.AcceptRole)
            box.addButton("Later", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is go:
                self.install_update(rel)
        self._bg(updater.fetch_latest, done)

    def install_update(self, rel):
        kind = updater.install_kind()
        if kind == "git":
            self.banner("Updating from GitHub (git pull)…", "orange")

            def pulled(res):
                if isinstance(res, Exception):
                    out = getattr(res, "output", "") or str(res)
                    self.banner("")
                    QMessageBox.warning(self, "Update failed", out[-1500:])
                    return
                self.banner("Update installed")
                if QMessageBox.question(self, "Updated", "Update installed. Restart tttlog now?") \
                        == QMessageBox.Yes:
                    updater.restart_from_source()
                    self.close()
            self._bg(updater.update_git_checkout, pulled)
            return
        if not rel.asset_url:                    # no build for this computer: open the page
            QDesktopServices.openUrl(QUrl(rel.url))
            return
        dest = Path.home() / "Downloads"
        dest.mkdir(exist_ok=True)
        dest = dest / rel.asset_name
        prog = QProgressDialog(f"Downloading tttlog {rel.version}…", None, 0, 100, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()

        def progress(n, total):
            self._bridge.done.emit(lambda _: prog.setValue(int(n * 100 / total)), None)

        def downloaded(res):
            prog.close()
            if isinstance(res, Exception):
                QMessageBox.warning(self, "Update failed", str(res))
                return
            if kind == "mac-app":
                updater.stage_mac_update(res)
                QMessageBox.information(self, "Update", "tttlog will close, update itself, and reopen.")
                self.close()
                QApplication.quit()
            else:
                updater.reveal(res)
                QMessageBox.information(self, "Update downloaded",
                                        f"Saved {res.name} to Downloads. Replace your current copy with it.")
        self._bg(lambda: updater.download(rel.asset_url, dest, progress), downloaded)

    # ---------------------------------------------------------- panes
    @property
    def panes(self) -> list[Pane]:
        return [w for w in self.findChildren(Pane)]

    def _default_tabs(self):
        self.tabifyDockWidget(self.dock_spots, self.dock_telnet)
        self.tabifyDockWidget(self.dock_rate, self.dock_needed)
        self.tabifyDockWidget(self.dock_needed, self.dock_network)
        self.dock_spots.raise_()
        self.dock_rate.raise_()
        QTimer.singleShot(50, self._default_sizes)    # once the tabs have been laid out

    def _default_sizes(self):
        right = [self.dock_score, self.dock_check_partial, self.dock_rate]
        # Set the column split from the left side (resizing the right column is
        # ignored), in real pixels: small ratios like [2, 3] reset the column width.
        left = self.width() * 62 // 100
        self.resizeDocks([self.dock_log, self.dock_spots], [left * 2 // 5, left * 3 // 5], Qt.Horizontal)
        self.resizeDocks([self.dock_entry], [left], Qt.Horizontal)
        h = self.height()                               # small screens: shrink Score/Partial first
        self.resizeDocks(right, [min(215, h * 28 // 100), min(120, h * 16 // 100),
                                 max(150, h - min(215, h * 28 // 100) - min(120, h * 16 // 100) - 40)],
                         Qt.Vertical)
        self.resizeDocks([self.dock_entry], [self.dock_entry.content.sizeHint().height() + 24], Qt.Vertical)

    def _fit_to_screen(self):
        """Keep the window on a screen it fits: a layout saved on a big monitor
        (or a bigger display size) mustn't open off the edge of a small one."""
        scr = self.screen()
        if scr is None or self.isMaximized() or self.isFullScreen():
            return
        avail = scr.availableGeometry()
        # leave room for the title bar, which isn't part of geometry() before show()
        w = min(self.width(), avail.width())
        h = min(self.height(), avail.height() - 32)
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
        x = min(max(self.x(), avail.left()), avail.right() - w + 1)
        y = min(max(self.y(), avail.top()), avail.bottom() - h - 31)
        if (x, y) != (self.x(), self.y()):
            self.move(x, max(y, avail.top()))

    def set_display_size(self, pct: int):
        self.settings.setValue("ui_scale", pct)
        for a in self.scale_menu.actions():
            a.setChecked(a.data() == pct)
        QMessageBox.information(self, "Display size",
                                f"Display size set to {pct}%. Quit and restart tttlog to apply it.")

    def minimize_all_panes(self):
        for d in self.panes:
            if d.isVisible():
                d.set_minimized(True)

    def restore_all_panes(self):
        for d in self.panes:
            if d.isFloating() and d.isMinimized():
                d.showNormal()
            d.set_minimized(False)

    def dock_all_panes(self):
        for d in self.panes:
            if d.isFloating():
                d.setFloating(False)

    # ---------------------------------------------------------- close
    def closeEvent(self, ev):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("layout_version", LAYOUT_VERSION)
        self.cluster.disconnect_from()
        self.net.stop()
        self.wsjtx.stop()
        if self.log:
            self.log.close()
        super().closeEvent(ev)
