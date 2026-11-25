"""The one window."""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QMenu, QMessageBox, QProgressDialog, QPushButton, QScrollArea,
                               QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from .. import config
from .widgets import ElidedLabel, FlowLayout
from ..contests.engine import ContestEngine, load_rules
from ..core.cluster import (CLUSTER_KINDS, Home, describe_filter, detect_cluster_kind, filter_commands,
                            parse_spot, spot_command)
from .. import __version__, updater
from ..core.cty import CtyDat, USER_DATA_DIR, data_file, download_cty, download_scp
from ..core.db import Log
from ..core.models import QSO, band_from_khz, band_start_khz, mode_group, utc_now
from ..core.netsync import LogSync
from ..core import privileges
from ..core.rig import from_logger_mode, to_logger_mode
from ..export.adif import export_adif, import_adif, parse_adif
from ..export.cabrillo import export_cabrillo
from .cluster_pane import ClusterClient, SpotsPane, TelnetPane
from .dialogs import (ClusterButtonsDialog, ClusterDialog, EditQsoDialog, FKeyDialog, KeyerDialog, MacroDialog, NetworkDialog, NewLogDialog, RadioDialog,
                      WsjtxDialog,
                      StationDialog)
from .docks import GridCanvas, Pane
from .needed_pane import NeededPane
from .needed_spots_pane import NeededSpotsPane
from .bandmap_pane import BandmapPane
from .network_pane import NetNode, NetworkPane
from .band_pane import BandPane
from .rate_pane import RatePane
from .score_pane import ScorePane
from .rig_control import RigControl
from .broadcast import Broadcaster
from ..core import band_rules, geo
from ..core.callbook import HamQTH, location as callbook_location, looks_like_call
from .keyer import Keyer
from .wsjtx_listener import WsjtxListener

VOICE_MODES = ("SSB", "AM", "FM")

# Keys you can change in Config ▸ Keyboard shortcuts: name -> (what it does, default)
EDITABLE_SHORTCUTS = {
    "go_needed": ("Go to the newest needed spot (remembers your run frequency)", "Ctrl+G"),
    "swap_run": ("Back to the run frequency / back to the spot", "Ctrl+B"),
    "toggle_run": ("Toggle Run / S&P", "Ctrl+R"),
    "spot_higher": ("Next spot up the band (higher kHz)", "Ctrl+Down"),
    "spot_lower": ("Next spot down the band (lower kHz)", "Ctrl+Up"),
    "rotor_turn": ("Turn the beam to the station (short path)", "Alt+J"),
    "rotor_long": ("Turn the beam to the station (long path)", "Alt+L"),
    "rotor_stop": ("Stop the rotor", "Ctrl+Alt+J"),
}

FIXTURE_CTY = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "cty_sample.dat"
DISPLAY_SIZES = (70, 80, 90, 100, 110, 125, 150)   # View ▸ Display size, % (applied at start)
LAYOUT_VERSION = "grid2"  # bump when panes are added/renamed so old saved layouts are dropped

# Where each pane starts on the grid (48 columns wide; rows are 22 px): x, y, width, height
DEFAULT_GRID = {
    "Bands": (0, 0, 3, 28), "Entry": (3, 0, 22, 14), "Log": (3, 14, 10, 14),
    "Spots": (13, 14, 12, 9), "Telnet": (13, 23, 12, 5), "Bandmap": (25, 0, 7, 28),
    "Score": (32, 0, 16, 9),
    "Check Partial": (32, 9, 16, 5), "Rate": (32, 14, 16, 8), "Needed": (32, 22, 16, 6),
    "Network": (32, 28, 16, 6), "Needed Spots": (13, 28, 12, 8),
}
DEFAULT_MINIMIZED = ("Network", "Needed Spots")
FREQ_RE = re.compile(r"^\d{4,6}(\.\d)?$")
OP_RE = re.compile(r"^[A-Z0-9]{3,}(/[A-Z0-9]+)*$")

STYLE = """
QLabel#radio { font: bold 15pt; }
QLabel#score { font: bold 15pt; }
QLabel#banner { font: 12pt; padding: 3px; }
QLineEdit { font: 16pt "Menlo", "Consolas", monospace; padding: 2px; }
QPushButton { min-width: 78px; }
"""


class _FluidBox(QWidget):
    """A widget that says when it's resized (the Entry pane uses it to reflow)."""
    resized = Signal(int, int)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.resized.emit(ev.size().width(), ev.size().height())

    def minimumSizeHint(self):
        return QSize(160, 80)                    # reflow before the pane has to scroll


class _Bridge(QObject):
    """Brings results from worker threads back to the GUI thread."""
    done = Signal(object, object)          # (callback, result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._bridge = _Bridge()
        self._bridge.done.connect(lambda cb, res: cb(res))
        self.setWindowTitle(f"tttlog {updater.display_version()}")
        self.resize(1100, 720)
        self.setStyleSheet(STYLE)
        self.settings = QSettings("N3TTT", "tttlog")
        self.station = config.load_station()
        self.macros = config.load_macros()
        self.cluster_cfg = config.load_cluster()
        self.colors = config.load_colors()
        self.net_cfg = config.load_network()
        self.wsjtx_cfg = config.load_wsjtx()
        self.n1mm_cfg = config.load_n1mm()
        self.callbook_cfg = config.load_callbook()
        self.callbook: HamQTH | None = None
        self._make_callbook()
        self._cb_pending: set[str] = set()
        self._cb_error = ""                        # last HamQTH problem (shown once)
        self._cb_timer = QTimer(self, singleShot=True, interval=500, timeout=self._lookup_call)
        self.rig_cfg = config.load_rig()
        self.keyer_cfg = config.load_keyer()
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
        self._update_partials("")                    # says so if there's no Super Check Partial file

        saved_op = self._op_layout(self.current_op)
        geo = saved_op["geometry"] if saved_op else self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        elif self.screen() is not None:              # first run: use most of the screen
            avail = self.screen().availableGeometry()
            self.resize(int(avail.width() * 0.92), int(avail.height() * 0.9))
        self._fit_to_screen()
        grid = saved_op["grid"] if saved_op else self._load_grid_setting("grid_layout")
        if grid:
            self.canvas.from_dict(grid)
        else:
            self.reset_layout()

        self._ticks = 0
        self.clock = QTimer(self, interval=1000, timeout=self._tick)
        self.clock.start()

        last = self.settings.value("last_log")
        if last and Path(last).exists():
            self.open_log(Path(last))
        from ..updater import running_under_rosetta
        if running_under_rosetta():
            self.banner("This is the Intel build of tttlog on an Apple Silicon Mac: install the "
                        "Apple Silicon one (tttlog-…-macos-arm64.dmg) — it's faster, and macOS will "
                        "stop running Intel apps", "orange")
        if self.cty_missing:
            self.banner("Country file missing or damaged: File ▸ Update country file  (using a small test file)", "orange")
        self._refresh_rates()
        if not (os.environ.get("TTTLOG_OFFLINE") or os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
            QTimer.singleShot(5000, self.auto_update_check)
        if self.cluster_cfg.get("auto_connect"):
            self.cluster_connect(True)
        self._seed_profiles()                         # operators' layouts / classes known here
        if self.net_cfg.get("enabled"):
            self.net.start(self.net_cfg)
        if self.wsjtx_cfg.get("enabled"):
            self.wsjtx.start(self.wsjtx_cfg)
        if self.rig_cfg.get("enabled"):
            self.rig.start(self.rig_cfg)
        self.keyer.configure(self.keyer_cfg)
        self.broadcast.configure(self.n1mm_cfg, self._radio_info)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        w = _FluidBox()                           # the Entry pane: its contents reflow to its size
        w.resized.connect(self._reflow_entry)
        self._entry_box = w
        v = QVBoxLayout(w)

        top = FlowLayout(hspacing=10)             # wraps onto a second line when narrow
        self.radio_lbl = QLabel(objectName="radio")
        self.clock_lbl = QLabel()
        self.score_lbl = QLabel("Score 0", objectName="score")
        for lbl in (self.radio_lbl, self.score_lbl):          # wrap when the pane is narrower
            lbl.setWordWrap(True)
        self.wsjtx_lbl = QLabel(visible=False)
        self.rig_lbl = QLabel(visible=False)
        self.rig_refresh_btn = QToolButton(text="⟳", visible=False)
        self.rig_refresh_btn.setFocusPolicy(Qt.NoFocus)
        self.rig_refresh_btn.setAutoRaise(True)
        self.rig_refresh_btn.setToolTip("Reconnect to the radio and read it again (Ctrl+Alt+R)")
        self.rig_refresh_btn.clicked.connect(lambda: (self.refresh_radio(), self.call.setFocus()))
        # Mode dropdown (shown when the log allows more than one mode, e.g. the General log)
        self.mode_box = QComboBox()
        self.mode_box.setFocusPolicy(Qt.NoFocus)             # typing stays in the entry line
        self.mode_box.setToolTip("Mode (also: type the mode in the call field + Enter)")
        self.mode_box.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.mode_box.textActivated.connect(self._on_mode_box)
        top.addWidget(self.mode_box)
        self.run_btn = QPushButton("RUN")
        self.run_btn.setCheckable(True)
        self.run_btn.setFocusPolicy(Qt.NoFocus)
        self.run_btn.setStyleSheet("QPushButton { font-weight: bold; min-width: 44px; padding: 2px 6px; }"
                                   "QPushButton:checked { background: #2da44e; color: white; }")
        self.run_btn.clicked.connect(lambda: (self.toggle_run(), self.call.setFocus()))
        top.addWidget(self.run_btn)
        top.addWidget(self.radio_lbl)
        self.beam_lbl = ElidedLabel()                 # one line; '…' when narrow, full text on hover
        self.beam_lbl.setProperty("baseTip", "Beam heading to the station in the entry line (Alt+J turns the rotor)")
        self.beam_lbl.setToolTip(self.beam_lbl.property("baseTip"))
        # room for a typical heading up front, so it appearing doesn't reflow the line
        self.beam_lbl.setMinimumWidth(min(220, self.beam_lbl.fontMetrics().horizontalAdvance("Beam 333° (LP 153°) · 10,926 km")))
        top.addWidget(self.beam_lbl)
        self.bandrule_lbl = QLabel()                  # multi-op: where the band-change rule stands
        self.bandrule_lbl.setStyleSheet("padding: 0 4px; border-radius: 3px;")
        top.addWidget(self.bandrule_lbl)
        top.addWidget(self.rig_lbl); top.addWidget(self.rig_refresh_btn); top.addWidget(self.wsjtx_lbl)
        top.addWidget(self.clock_lbl)
        top.addWidget(self.score_lbl)
        v.addLayout(top)

        ent = self._ent_grid = QGridLayout()
        self.call = QLineEdit(placeholderText="CALL or kHz")
        self.call.setToolTip("Type a call, or a frequency in kHz + Enter to QSY")
        self.rst = QLineEdit("59"); self.rst.setMaximumWidth(70)
        self.exch = QLineEdit(placeholderText="EXCH")
        self.sent_lbl = QLabel()
        self.rst_lbl = QLabel("RST")
        self.call_lbl, self.exch_lbl = QLabel("Call"), QLabel("Rcvd")
        self._entry_shape = None
        self._entry_pt = 16
        self._place_entry_fields("wide")
        v.addLayout(ent)
        for e in (self.call, self.rst, self.exch):
            e.returnPressed.connect(self.on_enter)
        self.call.textEdited.connect(self._on_call_edited)
        self.exch.textEdited.connect(lambda t: self.exch.setText(t.upper()))
        self.call.installEventFilter(self)
        self.exch.installEventFilter(self)

        self.banner_lbl = QLabel(objectName="banner")
        self.banner_lbl.setWordWrap(True)             # a narrow pane gets two lines, not a cut-off one
        v.addWidget(self.banner_lbl)

        fk = self._fk_grid = QGridLayout()
        self._fk_cols = 6
        self.fbuttons = []
        for i in range(12):
            b = QPushButton()
            b.clicked.connect(lambda _=False, n=i: self.fkey(n))
            b.setContextMenuPolicy(Qt.CustomContextMenu)                 # right-click: edit this key
            b.customContextMenuRequested.connect(lambda _pos, n=i: self._fkey_menu(n))
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet("min-width: 30px")           # labels elide on a narrow pane
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            fk.addWidget(b, i // 6, i % 6)
            self.fbuttons.append(b)
        v.addLayout(fk)
        self.tx_lbl = QLabel()
        v.addWidget(self.tx_lbl)
        # Needed mults as they're spotted, newest first (under the F-keys, where you're looking)
        self.alerts_lbl = QLabel()
        self.alerts_lbl.setStyleSheet("font-weight: bold;")
        v.addWidget(self.alerts_lbl)
        self.alerts = QListWidget()
        self.alerts.setFocusPolicy(Qt.NoFocus)
        self.alerts.setMinimumHeight(40)          # grows into whatever height the pane has spare
        self.alerts.setStyleSheet("QListWidget { font: 10pt 'Menlo', 'Consolas', monospace; }")
        self.alerts.itemClicked.connect(self._on_alert_clicked)
        v.addWidget(self.alerts, 1)
        self._alerted: dict[tuple, object] = {}    # (call, band) -> when we said so
        # Every pane, the entry line included, is a tile on a grid (see docks.py).
        v.setContentsMargins(8, 4, 8, 4)
        v.setSpacing(4)
        self.canvas = GridCanvas()
        # Autosave: every move, resize, roll-up, pop-out or close is saved a moment later
        self._layout_save = QTimer(self, singleShot=True, interval=1500, timeout=self._autosave_layout)
        self.canvas.layoutChanged.connect(self._layout_save.start)
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_scroll.setWidget(self.canvas)
        self.setCentralWidget(self.grid_scroll)
        # Bands: a narrow column of band buttons down the left edge
        self.band_pane = BandPane()
        self.band_pane.bandClicked.connect(self.go_to_band)
        self.band_pane.set_bands(["160m", "80m", "40m", "20m", "15m", "10m"])
        self._dock("Bands", self.band_pane)
        self._dock("Entry", w, closable=False)

        # Log pane
        self.log_table = QTableWidget(0, 9)
        self.log_table.setHorizontalHeaderLabels(["Time", "Call", "kHz", "Band", "Snt", "Rcv", "Country",
                                                  "Pts", "Stn"])
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.doubleClicked.connect(self.edit_selected)
        self._dock("Log", self.log_table)

        # Score pane
        self.score_pane = ScorePane()               # laid out like N1MM / Win-Test
        self._dock("Score", self.score_pane)

        # Partials pane (SCP + log)
        self.partials = QListWidget()
        self.partials.itemClicked.connect(lambda it: (it.flags() & Qt.ItemIsEnabled) and
                                          (self.call.setText(it.text()), self._on_call_edited(it.text())))
        self._dock("Check Partial", self.partials)

        # Rate pane
        self.rate_pane = RatePane()
        self._dock("Rate", self.rate_pane)

        # DX cluster: telnet client, Spots window (mults / Qs), Telnet window (raw text)
        self.cluster = ClusterClient(self)
        self.spots_pane = SpotsPane(self.colors)
        self.spots_pane.privilege_check = self._spot_privilege
        self.spots_pane.spots.max_age = timedelta(minutes=int(self.cluster_cfg.get("max_age_min", 30)))
        self.telnet_pane = TelnetPane()
        self.cluster.line.connect(self._on_cluster_line)
        self.cluster.state.connect(self._on_cluster_state)
        self.telnet_pane.connectRequested.connect(self.cluster_connect)
        self.telnet_pane.cmd.returnPressed.connect(self._cluster_cmd)
        self.telnet_pane.set_buttons(config.cluster_buttons(self.cluster_cfg),
                                     self.cluster_cfg.get("show_buttons", True))
        self.telnet_pane.buttonCommand.connect(self.cluster_button)
        self.telnet_pane.editButtonsRequested.connect(self.edit_cluster_buttons)
        self.telnet_pane.showButtonsChanged.connect(self._show_cluster_buttons)
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
        self._dock("Spots", self.spots_pane)
        self._dock("Telnet", self.telnet_pane)

        # Needed window: every mult x band, colored by need / spotted
        self.needed_pane = NeededPane(self.colors)
        self.needed_pane.spotActivated.connect(self.go_to_spot)
        self.needed_pane.colorsChanged.connect(self._save_colors)
        self._dock("Needed", self.needed_pane)

        # Needed Spots: spotted mults and unworked calls, filterable
        self.needed_spots_pane = NeededSpotsPane(self.colors)
        self.needed_spots_pane.privilege_check = self._spot_privilege
        self.needed_spots_pane.spotActivated.connect(lambda s: (self.go_to_spot(s), self.call.setFocus()))
        self._dock("Needed Spots", self.needed_spots_pane)

        # Bandmap: the band as a frequency scale with the spots on it
        self.bandmap = BandmapPane(self.colors)
        self.bandmap.privilege_check = self._spot_privilege
        self.bandmap.spotActivated.connect(lambda s: (self.go_to_spot(s), self.call.setFocus()))
        self._dock("Bandmap", self.bandmap)

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
        self.net.profileReceived.connect(self._on_profile_received)
        self.network_pane.talkSent.connect(self._send_talk)
        self._net_dirty = QTimer(self, singleShot=True, interval=300, timeout=self._on_net_log_changed)
        self._dock("Network", self.network_pane)

        # WSJT-X / JTDX / MSHV: log what they log
        self.wsjtx = WsjtxListener(self)
        self.wsjtx.adifLogged.connect(self._on_wsjtx_logged)
        self.wsjtx.stateChanged.connect(self._on_wsjtx_state)

        # Radio (CAT): follow the dial; tune it only if Config ▸ Radio allows
        self.rig = RigControl(self)
        self.rig.freqChanged.connect(self._on_rig_freq)
        self.rig.modeChanged.connect(self._on_rig_mode)
        self.rig.stateChanged.connect(self._on_rig_state)

        # N1MM-compatible UDP: RadioInfo + rotor commands (GH Everyware and friends)
        self.broadcast = Broadcaster(self)

        # Voice + CW keyer (transmits only when Config ▸ Voice & CW keyer allows it)
        self.keyer = Keyer(self.rig, self)
        self.keyer.stateChanged.connect(self._on_keyer_state)
        self.keyer.problem.connect(self._keyer_problem)
        self.keyer.notice.connect(lambda text: self.banner(text, "orange"))
        self.rig.refused.connect(self._rig_refused)
        self.keyer.recorded.connect(self._on_recorded)

    def _dock(self, title, widget, closable=True, scroll=True):
        d = Pane(title, widget, self.canvas, closable=closable, scroll=scroll)
        x, y, w, h = DEFAULT_GRID[title]
        self.canvas.add(d, QRect(x, y, w, h))
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
                                ("Update Super Check Partial (MASTER.SCP)", self.update_scp, None),
                                (None, None, None),
                                ("Quit", self.close, "Ctrl+Q")]:
            if text is None:
                f.addSeparator(); continue
            a = QAction(text, self, triggered=slot)
            if key:
                a.setShortcut(QKeySequence(key))
            f.addAction(a)
        op = mb.addMenu("&Operating")
        op.addAction(self._shortcut_action("toggle_run", "Toggle Run / S&&P", self.toggle_run))
        op.addAction(self._shortcut_action("swap_run", "Back to run frequency / back to the spot", self.swap_run))
        rot = op.addMenu("Rotor")
        rot.addAction(self._shortcut_action("rotor_turn", "Turn to the station (short path)", lambda: self.turn_rotor()))
        rot.addAction(self._shortcut_action("rotor_long", "Turn to the station (long path)",
                                            lambda: self.turn_rotor(long_path=True)))
        rot.addAction(self._shortcut_action("rotor_stop", "Stop the rotor", self.stop_rotor))
        op.addAction(QAction("Set frequency…", self, shortcut="Ctrl+F", triggered=self.ask_freq))
        op.addAction(QAction("Reconnect radio", self, shortcut="Ctrl+Alt+R", triggered=self.refresh_radio))
        op.addAction(QAction("Operator on (OPON)…", self, shortcut="Ctrl+Shift+O",
                             triggered=lambda: self.opon()))
        op.addAction(QAction("Operator's license class…", self, triggered=self.ask_license_class))
        op.addAction(QAction("Entry category (multi-op band rules)…", self, triggered=self.edit_category))
        self.mode_menu = op.addMenu("Mode")
        self._build_mode_menu(["SSB", "CW"])
        op.addAction(QAction("Delete selected QSO", self, shortcut="Ctrl+D", triggered=self.delete_selected))
        cfg = mb.addMenu("&Config")
        cfg.addAction(QAction("Station profile…", self, triggered=self.edit_station))
        cfg.addAction(QAction("Function-key macros…", self, triggered=self.edit_macros))
        cfg.addAction(QAction("DX cluster…", self, triggered=self.edit_cluster))
        cfg.addAction(QAction("Local network…", self, triggered=self.edit_network))
        cfg.addAction(QAction("WSJT-X…", self, triggered=self.edit_wsjtx))
        cfg.addAction(QAction("Radio…", self, triggered=self.edit_radio))
        cfg.addAction(QAction("Voice && CW keyer…", self, triggered=self.edit_keyer))
        cfg.addAction(QAction("Keyboard shortcuts…", self, triggered=self.edit_shortcuts))
        cfg.addAction(QAction("Rotor && N1MM broadcasts…", self, triggered=self.edit_n1mm))
        cfg.addAction(QAction("Callbook (HamQTH)…", self, triggered=self.edit_callbook))
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
        cl.addAction(self._shortcut_action("go_needed", "Go to the next needed spot (press again for the next)",
                                           self.go_to_next_needed))
        self.chase_band_act = QAction("Needed mults: only the band I'm on", self, checkable=True,
                                      checked=bool(self.cluster_cfg.get("chase_band_only")),
                                      toggled=self.set_chase_band_only)
        cl.addAction(self.chase_band_act)
        cl.addAction(self._shortcut_action("spot_higher", "Next spot up the band (higher kHz)",
                                           lambda: self.next_spot(+1)))
        cl.addAction(self._shortcut_action("spot_lower", "Next spot down the band (lower kHz)",
                                           lambda: self.next_spot(-1)))
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
        self.save_layout_act = QAction("Save layout for this operator", self, triggered=lambda: self.save_op_layout())
        view.addAction(self.save_layout_act)
        view.aboutToShow.connect(lambda: self.save_layout_act.setText(
            f"Save layout for {self.current_op} (OPON brings it back)"))
        view.addAction(QAction("Reset to the default layout", self, triggered=self.reset_layout))
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
        self.mode_box.blockSignals(True)
        self.mode_box.clear()
        self.mode_box.addItems(list(modes))
        self.mode_box.blockSignals(False)
        self.mode_box.setVisible(len(modes) > 1)
        self._sync_mode_box()

    def _sync_mode_box(self):
        if not hasattr(self, "mode_box"):
            return
        self.mode_box.blockSignals(True)
        if self.mode_box.findText(self.mode) < 0 and self.mode:
            self.mode_box.addItem(self.mode)                # e.g. a mode the radio switched to
        self.mode_box.setCurrentText(self.mode)
        self.mode_box.blockSignals(False)

    def _on_mode_box(self, mode: str):
        if mode and mode != self.mode:
            self.set_mode(mode)
        self.call.setFocus()

    def _build_shortcuts(self):
        for i in range(12):
            QShortcut(QKeySequence(f"F{i + 1}"), self, activated=lambda n=i: self.fkey(n),
                      context=Qt.ApplicationShortcut)
        for i in range(12):
            QShortcut(QKeySequence(f"Ctrl+Shift+F{i + 1}"), self, activated=lambda n=i: self.record_fkey(n),
                      context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("PgUp"), self, activated=lambda: self.change_wpm(+2), context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("PgDown"), self, activated=lambda: self.change_wpm(-2), context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("Escape"), self, activated=self.escape)
        # When the Entry pane is popped out it's a separate window, so it needs its
        # own Escape (enabled only then, or the two would clash).
        esc = QShortcut(QKeySequence("Escape"), self.dock_entry, activated=self.escape,
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
        if self._ticks % 5 == 0:
            self._refresh_band_rule(now)

    def _refresh_rates(self, now=None):
        self.rate_pane.update_rates(self.qsos, self.engine, now or utc_now(), me=self.current_op)

    def _refresh_radio(self):
        self._sync_mode_box()
        self._refresh_band_rule()
        if hasattr(self, "bandmap"):
            self.bandmap.set_radio(self.freq_khz, band_from_khz(self.freq_khz))
        if hasattr(self, "broadcast"):
            self.broadcast.send_radio()
        if hasattr(self, "run_btn"):
            self.run_btn.setChecked(self.run_mode)
            self.run_btn.setText("RUN" if self.run_mode else "S&&P")
            self.run_btn.setToolTip(f"Run or Search & Pounce ({self._key('toggle_run')})")
        self._refresh_alert_hint()
        band = band_from_khz(self.freq_khz) or "?"
        self.band_pane.set_current(band)
        self.radio_lbl.setText(f"{self.freq_khz:,.1f} kHz  {band}  {self.mode}  "
                               f"[{'RUN' if self.run_mode else 'S&P'}]  OP {self.current_op}")
        page = self.macros.get(self.mode, self.macros.get("SSB"))["RUN" if self.run_mode else "SP"]
        for i, b in enumerate(self.fbuttons):
            m = page[i] if i < len(page) else {"label": ""}
            b.setText(f"F{i + 1} {m.get('label', '')}")
            b.setToolTip(f"{b.text()}: {m.get('text', '')}\nRight-click to edit")
        if self.engine:
            self._refresh_sent()
        self.settings.setValue("freq_khz", self.freq_khz)
        self._push_net_status()
        if hasattr(self, "spots_pane") and self.spots_pane.current_band != band:
            self.spots_pane.current_band = band
            self.spots_pane.refresh()
            self._refresh_needed()
            self._filter_alerts()

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
        self.category = self.log.get_meta("category", "")      # multi-op entry category (MS, M2...)
        self.tx_role = self.log.get_meta("tx_role", "")        # what this computer is in it
        self.mode = rules["modes"][0]
        self._build_mode_menu(rules["modes"])
        self.band_pane.set_bands(list(rules["bands"]))
        self.bandmap.set_bands(list(rules["bands"]))
        self.rst.setText(self.engine.default_rst(self.mode))
        self.rst.setVisible(self.engine.uses_rst); self.rst_lbl.setVisible(self.engine.uses_rst)
        self.exch.setPlaceholderText(" ".join(f.get("label", f["name"]).upper()
                                              for f in self.engine.rcvd_fields))
        self.sync = LogSync(self.log, self.node_id, self.net_cfg["station_name"])
        self.net.set_log(self.sync, cid)
        self.qsos = self.engine.rescore(self.log.all())
        self.needed_pane.set_engine(self.engine)
        self.needed_spots_pane.set_engine(self.engine)
        self.settings.setValue("last_log", str(path))
        self.setWindowTitle(f"tttlog {updater.display_version()} — {rules['name']} — {path.name}")
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
        self._show_beam(call)
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

    def _refresh_sent(self):
        """'Sent: 599 5' or, with a serial, the number the next QSO gets."""
        if self.engine:
            rst = f"{self.engine.default_rst(self.mode)} " if self.engine.uses_rst else ""
            self.sent_lbl.setText(f"Sent: {rst}{self.engine.sent_exchange(self.qsos)}")

    def _update_partials(self, call):
        self.partials.clear()
        if not self.scp:                              # only the log's own calls to go on
            self.partials.setToolTip("No Super Check Partial file yet: File ▸ Update Super Check Partial")
            if len(call) < 2:
                from PySide6.QtWidgets import QListWidgetItem
                it = QListWidgetItem("No Super Check Partial file: File ▸ Update Super Check Partial")
                it.setFlags(Qt.NoItemFlags)
                self.partials.addItem(it)
                return
        else:
            self.partials.setToolTip("")
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
        errs = self.engine.validate_rcvd(self.exch.text(), call)
        if errs:
            self.banner("; ".join(errs), "#ffd166")
            self.exch.setFocus()
            return
        self.log_qso()

    def log_qso(self):
        q = QSO(call=self.call.text().strip().upper(), freq_khz=self.freq_khz, mode=self.mode,
                rst_sent=self.engine.default_rst(self.mode) if self.engine.uses_rst else "",
                rst_rcvd=(self.rst.text().strip() or self.engine.default_rst(self.mode)) if self.engine.uses_rst else "",
                exch_sent=self.engine.sent_exchange(self.qsos, for_log=True),
                exch_rcvd=self.exch.text().strip().upper(),
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
        exch = self.engine.sent_exchange(self.qsos) if self.engine else ""
        rst = self.engine.default_rst(self.mode) if self.engine else "59"
        zone = str(self.station.cq_zone)
        if self.mode == "CW":                                   # cut numbers: 599 -> 5NN
            from ..core.keyer import cut_numbers
            style = self.keyer_cfg.get("cut", "nt")
            rst = cut_numbers(rst, style, rst=True)
            if self.keyer_cfg.get("cut_exch"):
                exch, zone = cut_numbers(exch, style), cut_numbers(zone, style)
        txt = config.expand(m.get("text", ""), self.station, self.call.text().strip().upper(),
                            exch, rst, zone)
        wav = m.get("wav", "")
        why = self.privilege_problem()
        if why and (self.mode in VOICE_MODES or self.mode == "CW"):
            self.banner(f"Not sending: {why}", "#ff8080")
            return
        if self.mode in VOICE_MODES:
            path = self.wav_path(wav) if wav else None
            if path is None or not path.exists():
                self.tx_lbl.setText(f"F{n + 1}: {txt}")
                self.banner(f"F{n + 1} has no recording yet: press Ctrl+Shift+F{n + 1} to record it", "#ffd166")
                return
            if self.keyer.send_voice(path):
                self.tx_lbl.setText(f"TX F{n + 1}: {txt}   [{wav}]")
        elif self.mode == "CW":
            if self.keyer.send_cw(txt):
                self.tx_lbl.setText(f"TX F{n + 1} ({self.keyer.wpm} wpm): {txt}")
        else:
            self.tx_lbl.setText(f"F{n + 1}: {txt}")

    # ---------------------------------------------------------- keyer
    def wav_path(self, name: str) -> Path:
        from ..core.keyer import wav_dir
        return wav_dir(config.CONFIG_DIR, self.station.call) / name

    def escape(self):
        """Esc: stop recording, else stop sending; only an idle Esc wipes the entry line."""
        if self.keyer.recorder.active:
            self.keyer.stop_recording()
        elif self.keyer.stop():
            self.tx_lbl.setText("Stopped")
        else:
            self.wipe()

    def record_fkey(self, n: int):
        """Ctrl+Shift+Fn: record (or stop recording) the voice message for Fn."""
        if self.keyer.recorder.active:
            self.keyer.stop_recording(); return
        from ..core.keyer import safe_wav_name
        page_name = "RUN" if self.run_mode else "SP"
        page = self.macros.get("SSB", {}).get(page_name, [])
        if n >= len(page):
            return
        m = page[n]
        if m.get("text", "").strip() in ("{CLEAR}", "{SPOT}"):
            self.banner(f"F{n + 1} is an action key ({m['text']}), not a message", "#ffd166"); return
        if not m.get("wav"):
            m["wav"] = safe_wav_name(f"{page_name.lower()}_f{n + 1}")
            config.save_macros(self.macros)
        if self.keyer.record(self.wav_path(m["wav"])):
            self.banner(f"Recording F{n + 1} ({m.get('label', '')}): speak, then press Ctrl+Shift+F{n + 1} or Esc",
                        "#ff8080")

    def _on_recorded(self, path: str):
        from ..core.keyer import wav_seconds
        self.banner(f"Saved {Path(path).name} ({wav_seconds(Path(path)):.1f} s)")

    def _on_keyer_state(self, state: str):
        if state:
            if not self.tx_lbl.text().startswith("TX F"):        # keep "TX F1: CQ…" while it's sent
                self.tx_lbl.setText(state)
        else:
            if self.tx_lbl.text().startswith(("TX", "●", "Playing")):
                self.tx_lbl.setText("")                         # finished sending
        if not self.keyer.recorder.active and self.banner_lbl.text().startswith("Recording"):
            self.banner("")

    def change_wpm(self, delta: int):
        wpm = self.keyer.set_wpm(self.keyer.wpm + delta)
        self.keyer_cfg["wpm"] = wpm
        config.save_keyer(self.keyer_cfg)
        self.tx_lbl.setText(f"CW speed {wpm} wpm")

    # -- Entry pane: contents reflow to the pane's size --------------------------
    def _place_entry_fields(self, shape: str):
        """wide: Call | RST | Rcvd | sent, one row.   medium: Call on its own row,
        RST | Rcvd | sent under it.   narrow: Call / RST | Rcvd / sent, stacked."""
        if shape == self._entry_shape:
            return
        self._entry_shape = shape
        g = self._ent_grid
        for wdg in (self.call_lbl, self.call, self.rst_lbl, self.rst, self.exch_lbl, self.exch, self.sent_lbl):
            g.removeWidget(wdg)
        for c in range(4):
            g.setColumnStretch(c, 0)
        if shape == "wide":
            for c, (lbl, wid) in enumerate([(self.call_lbl, self.call), (self.rst_lbl, self.rst),
                                            (self.exch_lbl, self.exch)]):
                g.addWidget(lbl, 0, c); g.addWidget(wid, 1, c)
            g.addWidget(self.sent_lbl, 1, 3)
            g.setColumnStretch(0, 3); g.setColumnStretch(2, 2)
        elif shape == "medium":
            g.addWidget(self.call_lbl, 0, 0, 1, 3); g.addWidget(self.call, 1, 0, 1, 3)
            g.addWidget(self.rst_lbl, 2, 0); g.addWidget(self.rst, 3, 0)
            g.addWidget(self.exch_lbl, 2, 1); g.addWidget(self.exch, 3, 1)
            g.addWidget(self.sent_lbl, 3, 2)
            g.setColumnStretch(1, 1)
        else:
            g.addWidget(self.call_lbl, 0, 0, 1, 2); g.addWidget(self.call, 1, 0, 1, 2)
            g.addWidget(self.rst_lbl, 2, 0); g.addWidget(self.exch_lbl, 2, 1)
            g.addWidget(self.rst, 3, 0); g.addWidget(self.exch, 3, 1)
            g.addWidget(self.sent_lbl, 4, 0, 1, 2)
            g.setColumnStretch(1, 1)

    def _place_fkeys(self, cols: int):
        if cols == self._fk_cols:
            return
        self._fk_cols = cols
        for b in self.fbuttons:
            self._fk_grid.removeWidget(b)
        for i, b in enumerate(self.fbuttons):
            self._fk_grid.addWidget(b, i // cols, i % cols)

    def _reflow_entry(self, width: int, height: int):
        """Called whenever the Entry pane changes size."""
        self._place_entry_fields("wide" if width >= 540 else "medium" if width >= 330 else "narrow")
        self._place_fkeys(6 if width >= 540 else 4 if width >= 380 else 3 if width >= 250 else 2)
        # Entry text: 16 pt normally, bigger on a big pane (never smaller: a narrow pane
        # stacks the boxes instead). Steps of 2 pt, so it doesn't flicker while dragging.
        pt = int(max(16, min(28, 16 * min(width / 620, height / 300))) // 2 * 2)
        if pt != getattr(self, "_entry_pt", 16):
            self._entry_pt = pt
            for e in (self.call, self.rst, self.exch):
                e.setStyleSheet(f"QLineEdit {{ font-size: {pt}pt; }}")
            self.rst.setMaximumWidth(int(70 * pt / 16))

    def _keyer_problem(self, why: str):
        self._last_keyer_problem = why
        self.banner(why, "#ffd166")

    def _rig_refused(self, what: str):
        if what == "cw":
            self.keyer.stop()
            self.banner("The radio refused the CW: put it in CW mode (with BK-IN on)", "#ffd166")

    def edit_keyer(self):
        self.keyer_cfg["wpm"] = self.keyer.wpm
        dlg = KeyerDialog(self.keyer_cfg, self.keyer, self.macros,
                          self.wav_path("x").parent, self)
        if dlg.exec():
            self.keyer_cfg = dlg.values()
            config.save_keyer(self.keyer_cfg)
        self.keyer.configure(self.keyer_cfg)
        # a "can't transmit because..." banner from before is stale now: re-check it
        last = getattr(self, "_last_keyer_problem", "")
        if last and self.banner_lbl.text() == last and self.keyer.why_not(cw=self.mode == "CW") != last:
            self.banner("")
            self._last_keyer_problem = ""

    # ---------------------------------------------------------- radio
    def set_freq(self, khz: float, from_rig: bool = False):
        if not from_rig:
            if band_from_khz(khz) is None:
                self.banner(f"{khz} kHz is outside the ham bands", "#ffd166")
                return
            if self.rig.is_connected() and not self.rig.control:
                # follow-only: the radio's dial is the truth, so don't log a frequency it isn't on
                self.banner("Tune the radio (tttlog follows it). To let tttlog tune it: "
                            "Config ▸ Radio ▸ Let tttlog tune the radio", "#ffd166")
                return
            self.rig.set_freq(khz)
        self.freq_khz = khz
        self.settings.setValue("freq_khz", khz)
        self.settings.setValue(f"band_freq/{band_from_khz(khz)}/{mode_group(self.mode)}", khz)
        self._refresh_radio()
        self._live_check(self.call.text().strip().upper())
        self._check_privileges()

    def go_to_band(self, band: str):
        """Band button: back to where you last were on that band in this kind of
        mode, else a usual spot. (With radio control this will tune the radio.)"""
        saved = self.settings.value(f"band_freq/{band}/{mode_group(self.mode)}")
        try:
            khz = float(saved) if saved is not None else None
        except (TypeError, ValueError):
            khz = None
        if khz is None or band_from_khz(khz) != band:
            khz = band_start_khz(band, self.mode)
        if khz is not None and self.license_class:
            fixed = privileges.inside(self.license_class, band, self.mode, khz)
            if fixed is None:
                self.banner(f"{self.license_class} class has no {self.mode} privileges on {band}", "#ff8080")
                self.call.setFocus()
                return
            khz = fixed
        if khz is not None:
            self.set_freq(khz)
        self.call.setFocus()

    def ask_freq(self):
        khz, ok = QInputDialog.getDouble(self, "Frequency", "kHz", self.freq_khz, 1800, 450000, 1)
        if ok:
            self.set_freq(khz)

    def set_mode(self, mode, from_rig: bool = False):
        old = self.engine.default_rst(self.mode) if self.engine else "59"
        if not from_rig:
            self.rig.set_mode(from_logger_mode(mode, self.freq_khz))
        self.mode = mode
        if self.engine and self.rst.text().strip() in ("", old):   # 59 <-> 599 unless typed
            self.rst.setText(self.engine.default_rst(mode))
        self._refresh_radio()
        self._check_privileges()
        if self.license_class:
            self._restrike_spots()

    def toggle_run(self):
        if self.run_mode:                            # leaving the run frequency: remember it
            self.run_memory = {"freq": self.freq_khz, "mode": self.mode}
        self.run_mode = not self.run_mode
        if self.run_mode:
            self.run_memory = {"freq": self.freq_khz, "mode": self.mode}
        self._refresh_radio()

    # ---------------------------------------------------------- editable shortcuts
    def _key(self, name: str) -> str:
        """The key for an editable shortcut, as shown to the user (e.g. Ctrl+G, ⌘G on a Mac)."""
        seq = str(self.settings.value(f"shortcuts/{name}", EDITABLE_SHORTCUTS[name][1]) or "")
        return QKeySequence(seq).toString(QKeySequence.NativeText) or "(no key)"

    def _shortcut_action(self, name: str, text: str, slot) -> QAction:
        if not hasattr(self, "shortcut_actions"):
            self.shortcut_actions = {}
        a = QAction(text, self, triggered=slot)
        a.setShortcut(QKeySequence(str(self.settings.value(f"shortcuts/{name}", EDITABLE_SHORTCUTS[name][1]) or "")))
        a.setShortcutContext(Qt.ApplicationShortcut)            # works from popped-out panes too
        self.shortcut_actions[name] = a
        return a

    def set_shortcut(self, name: str, seq: str):
        self.settings.setValue(f"shortcuts/{name}", seq)
        self.shortcut_actions[name].setShortcut(QKeySequence(seq))
        self._refresh_alert_hint()

    def edit_shortcuts(self):
        from .dialogs import ShortcutsDialog
        cur = {n: str(self.settings.value(f"shortcuts/{n}", d) or "") for n, (_t, d) in EDITABLE_SHORTCUTS.items()}
        taken = {a.shortcut().toString(): a.text().replace("&&", "&") for a in self.findChildren(QAction)
                 if not a.shortcut().isEmpty() and a not in self.shortcut_actions.values()}
        dlg = ShortcutsDialog(EDITABLE_SHORTCUTS, cur, taken, self)
        if dlg.exec():
            for n, seq in dlg.values().items():
                self.set_shortcut(n, seq)

    # ---------------------------------------------------------- needed-mult messages
    def _maybe_alert(self, s):
        """A spot that's a new multiplier for us: say so under the Log (once per call and band
        every 10 minutes), unless the spot filter hides it or we can't transmit there."""
        if s.status != "MULT" or s.band is None:
            return
        from ..core.cluster import spot_passes
        if not spot_passes(s, self.spots_pane.spot_filter, self.spots_pane.home) or self._spot_privilege(s):
            return
        key = (s.call, s.band)
        if self.cluster_cfg.get("chase_band_only") and s.band != band_from_khz(self.freq_khz):
            return
        last = self._alerted.get(key)
        if last is not None and (s.time_utc - last).total_seconds() < 600:
            return
        self._alerted[key] = s.time_utc
        from PySide6.QtWidgets import QListWidgetItem
        what = []
        for lbl, key in s.keys:                      # e.g. ("Countries", ("20m", "Japan")) -> "Japan"
            if lbl in s.mults:
                v = str(key[-1])
                what.append(f"zone {v}" if v.isdigit() else v)
        it = QListWidgetItem(f"{s.time_utc:%H%M}Z  {s.call:<10} {s.freq_khz:>9.1f}  {s.band:<4} "
                             f"{', '.join(dict.fromkeys(what)) or ', '.join(s.mults)}")
        it.setData(Qt.UserRole, s)
        it.setToolTip(f"Click (or {self._key('go_needed')}) to go there; {self._key('swap_run')} brings you back "
                      f"to your run frequency")
        self.alerts.insertItem(0, it)
        while self.alerts.count() > 30:
            self.alerts.takeItem(self.alerts.count() - 1)
        self._refresh_alert_hint()

    def _filter_alerts(self):
        """With 'only the band I'm on', hide messages for other bands (they come back)."""
        if not hasattr(self, "alerts"):
            return
        band_only = bool(self.cluster_cfg.get("chase_band_only"))
        band = band_from_khz(self.freq_khz)
        for i in range(self.alerts.count()):
            it = self.alerts.item(i)
            sp = it.data(Qt.UserRole)
            it.setHidden(band_only and sp is not None and sp.band != band)

    def _on_alert_clicked(self, item):
        s = item.data(Qt.UserRole)
        if s is not None:
            self.go_to_spot(s)
            self.call.setFocus()

    def _refresh_alert_hint(self):
        if hasattr(self, "alerts_lbl"):
            n = self.alerts.count()
            self.alerts_lbl.setText(f"Needed mults spotted ({n}) · {self._key('go_needed')} go · "
                                    f"{self._key('swap_run')} back to run" if n else
                                    f"Needed mults spotted show here · {self._key('go_needed')} go · "
                                    f"{self._key('swap_run')} back to run")

    # ---------------------------------------------------------- multi-op band-change rules
    def _band_limits(self) -> dict:
        return band_rules.limits(self.engine.rules if self.engine else {}, getattr(self, "category", ""))

    def _my_qsos(self) -> list:
        """This transmitter's QSOs: the ones logged on this computer."""
        me = self.net_cfg.get("station_name", "") or ""
        return [q for q in self.qsos if (q.station_name or "") == me]

    def _category_name(self) -> str:
        cat = getattr(self, "category", "")
        short = {"MS": "M/S", "M2": "M/2", "MM": "M/M"}.get(cat, "")
        role = {"run": "run", "mult": "mult station", "tx1": "TX1", "tx2": "TX2"}.get(getattr(self, "tx_role", ""), "")
        return f"{short} {role}".strip()

    def _refresh_band_rule(self, now=None):
        """The status line: this transmitter's band, and when it may change (red if the
        radio is on another band and a QSO there would break the rule)."""
        if not hasattr(self, "bandrule_lbl"):
            return
        lim = self._band_limits() if self.engine else {}
        if not lim:
            self.bandrule_lbl.setText(""); self.bandrule_lbl.setStyleSheet("")
            return
        radio = band_from_khz(self.freq_khz)
        chk = band_rules.check(lim, self._my_qsos(), radio, now or utc_now())
        text = f"{self._category_name()}: {chk.status or 'no QSOs yet'}"
        if not chk.ok:
            text = f"{self._category_name()}: {chk.why} — go back to {chk.current}"
            style = "background:#ff6b6b; color:black;"
        elif "free to change" in chk.status:
            style = "background:#ffd166; color:black;"
        else:
            style = ""
        self.bandrule_lbl.setText(text)
        self.bandrule_lbl.setStyleSheet("padding: 0 4px; border-radius: 3px;" + style)
        self.bandrule_lbl.setToolTip(f"{band_rules.CATEGORIES.get(self.category, '')}: "
                                     f"{band_rules.describe(lim)} (Operating ▸ Entry category)")

    def _approve_band_change(self, s) -> bool:
        """Multi-Single / Multi-Two: a spot on a band other than this transmitter's asks
        before going, saying whether the contest's band-change rule allows it now."""
        cat = getattr(self, "category", "")
        if cat not in ("MS", "M2") or not self.engine or s.band is None:
            return True
        lim = self._band_limits()
        mine = self._my_qsos()
        chk = band_rules.check(lim, mine, s.band, utc_now())
        current = chk.current or band_from_khz(self.freq_khz)
        mult_only = cat == "MS" and self.tx_role == "mult" and s.status != "MULT"
        if (current is None or s.band == current) and not mult_only:
            return True                                    # not a band change
        lines = [f"{s.call} is on {s.band}; this station is on {current}."]
        if not lim:
            lines.append(f"tttlog has no band-change rule for {self._category_name()} in "
                         f"{self.engine.rules['name']}: check the contest's rules.")
        elif not chk.ok:
            lines.append(f"NOT ALLOWED NOW: {chk.why}.")
        elif chk.current:
            lines.append(f"Allowed ({band_rules.describe(lim)}): {chk.status}. "
                         f"A QSO there counts as a band change.")
        if mult_only:
            lines.append("This is the multiplier station: it may only work new multipliers, and this spot isn't one.")
        lines.append(f"Go to {s.band}?")
        ok = chk.ok and not mult_only
        ans = QMessageBox.question(self, "Band change", "\n\n".join(lines),
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.Yes if ok else QMessageBox.No)
        return ans == QMessageBox.Yes

    def edit_category(self):
        if not self._need_log():
            return
        from .dialogs import CategoryDialog
        dlg = CategoryDialog(self.category, self.tx_role, self.engine.rules, self)
        if dlg.exec():
            self.category, self.tx_role = dlg.values()
            self.log.set_meta("category", self.category)
            self.log.set_meta("tx_role", self.tx_role)
            self._refresh_band_rule()

    # ---------------------------------------------------------- beam heading / rotor
    def _my_latlon(self) -> tuple[float, float] | None:
        ll = geo.grid_to_latlon(self.station.grid)
        if ll:
            return ll
        hit = self.cty.lookup(self.station.call) if self.station.call not in ("", "N0CALL") else None
        return (hit[0].lat, hit[0].lon) if hit else None

    def beam_to(self, call: str) -> tuple[float, float, str] | None:
        """(short-path heading, km, aimed at) to a call, or None.
        Aims at the station's grid square from HamQTH when it's known (looked up
        in the background), otherwise at the centre of its country."""
        me = self._my_latlon()
        hit = self.cty.lookup(call) if call and len(call) >= 2 else None
        if not me or not hit:
            return None
        there, what = (hit[0].lat, hit[0].lon), f"{hit[0].name} centre"
        if self.callbook:
            loc = callbook_location(self.callbook.cached(call))
            if loc:
                there, what = loc[0], f"{loc[1]} (HamQTH)"
        return geo.bearing(me, there), geo.distance_km(me, there), what

    def _show_beam(self, call: str):
        b = self.beam_to(call) if call and not FREQ_RE.match(call) else None
        if not b:
            self.beam_lbl.setText("")
            return
        sp, km, what = b
        self.beam_lbl.setText(f"Beam {sp:.0f}° (LP {geo.long_path(sp):.0f}°) · {km:,.0f} km · {what}")
        if self.callbook and looks_like_call(call) and self.callbook.cached(call) is None:
            self._cb_timer.start()                 # look it up once typing pauses

    # -- HamQTH callbook ------------------------------------------------------
    def _make_callbook(self):
        c = self.callbook_cfg
        self.callbook = (HamQTH(c["user"], c["password"], USER_DATA_DIR / "hamqth_cache.json")
                         if c.get("enabled") and c.get("user") and c.get("password") else None)

    def _lookup_call(self):
        call = self.call.text().strip().upper()
        cb = self.callbook
        if not cb or not looks_like_call(call) or cb.cached(call) is not None or call in self._cb_pending:
            return
        self._cb_pending.add(call)

        def done(res):
            self._cb_pending.discard(call)
            if isinstance(res, Exception):
                msg = str(res)
                if msg != self._cb_error:          # say it once, not on every call
                    self._cb_error = msg
                    self.banner(f"HamQTH lookup: {msg} (Config ▸ Callbook). Using country centres.", "#ffd166")
                return
            self._cb_error = ""
            if self.call.text().strip().upper() == call:
                self._show_beam(call)
        self._bg(lambda: cb.lookup(call), done)

    def edit_callbook(self):
        from .dialogs import CallbookDialog
        dlg = CallbookDialog(self.callbook_cfg, self)
        if dlg.exec():
            self.callbook_cfg = dlg.values()
            config.save_callbook(self.callbook_cfg)
            self._make_callbook()
            self._cb_error = ""
            self._show_beam(self.call.text().strip().upper())

    def _rotor_call(self) -> str:
        return self.call.text().strip().upper() or (self.qsos[-1].call if self.qsos else "")

    def turn_rotor(self, long_path: bool = False):
        call = self._rotor_call()
        b = self.beam_to(call)
        if not b:
            self.banner("Type a call first (or set your grid in Config ▸ Station profile)", "#ffd166")
            return
        az = geo.long_path(b[0]) if long_path else b[0]
        if not self.broadcast.turn(az, self.freq_khz):
            self.banner("Rotor control is off: Config ▸ Rotor & N1MM broadcasts", "#ffd166")
            return
        self.banner(f"Turning the beam to {az:.0f}° ({'long' if long_path else 'short'} path to {call}) · "
                    f"{self._key('rotor_stop')} stops")

    def stop_rotor(self):
        if self.broadcast.stop(self.freq_khz):
            self.banner("Rotor stopped")

    def _radio_info(self) -> dict:
        return {"station": self.net_cfg.get("station_name", "") or self.station.call, "mycall": self.station.call,
                "op": self.current_op, "khz": self.freq_khz, "mode": self.mode, "running": self.run_mode,
                "transmitting": bool(getattr(self, "keyer", None) and self.keyer.keyed)}

    def edit_n1mm(self):
        from .dialogs import N1mmDialog
        dlg = N1mmDialog(self.n1mm_cfg, self)
        if dlg.exec():
            self.n1mm_cfg = dlg.values()
            config.save_n1mm(self.n1mm_cfg)
            self.broadcast.configure(self.n1mm_cfg, self._radio_info)

    def swap_run(self):
        """Back to the run frequency (and Run); pressed again, back to the spot you left."""
        if not self.run_mode:
            if not getattr(self, "run_memory", None):
                self.banner("No run frequency remembered yet: it's kept when you leave Run "
                            "(jump to a spot, or toggle to S&P)", "#ffd166")
                return
            self.sp_memory = {"freq": self.freq_khz, "mode": self.mode, "call": self.call.text()}
            rm = self.run_memory
            if rm["mode"] != self.mode:
                self.set_mode(rm["mode"])
            self.set_freq(rm["freq"])
            self.run_mode = True
            self.wipe()
            self._refresh_radio()
            self.banner(f"Back on your run frequency {rm['freq']:,.1f} · {self._key('swap_run')} returns to "
                        f"{self.sp_memory['call'] or 'the spot'}")
        else:
            sp = getattr(self, "sp_memory", None)
            if not sp:
                self.banner("No spot to go back to", "#ffd166")
                return
            self.run_memory = {"freq": self.freq_khz, "mode": self.mode}
            if sp["mode"] != self.mode:
                self.set_mode(sp["mode"])
            self.set_freq(sp["freq"])
            self.run_mode = False
            self.wipe()
            if sp.get("call"):
                self.call.setText(sp["call"]); self._on_call_edited(sp["call"])
            self._refresh_radio()
            self.banner(f"Back to {sp.get('call') or 'the spot'} · {self._key('swap_run')} returns to your run "
                        f"frequency {self.run_memory['freq']:,.1f}")

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
            self.score_pane.update_score(self.engine, s)
        self._refresh_rates()
        self._refresh_sent()                         # the next serial number
        self.spots_pane.reevaluate(self.engine, self.qsos)
        self._refresh_needed()
        self._refresh_band_rule()
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
        prev = self.current_op
        if op != prev:
            self.save_op_layout(prev, quiet=True)      # the outgoing operator keeps their layout
        self.settings.setValue("current_op", op)
        layout_note = ""
        if op != prev and self.load_op_layout(op):
            layout_note = f" · {op}'s window layout"
        self._refresh_radio()
        self._push_net_status()
        self._refresh_rates()
        msg = f"Operator is now {op}{layout_note}"
        if self.station.license_class and self.settings.value(f"op_class/{op}") is None \
                and op not in (self.station.call, self.station.operator):
            msg += (f" · band limits use the station's {self.license_class} class until you set "
                    f"{op}'s: Operating ▸ Operator's license class")
        why = self.privilege_problem()
        if why:
            self.banner(f"⚠ {why} · {msg}", "#ff8080")
            self._priv_warned = True
        else:
            self._check_privileges()
            self.banner(msg)
        self._restrike_spots()
        self.call.setFocus()
        return True

    # ---------------------------------------------------------- license privileges
    @property
    def license_class(self) -> str:
        """The current operator's US license class ('' = no band limits)."""
        own = self.settings.value(f"op_class/{self.current_op}")
        if own is not None:
            return privileges.normalize(str(own))
        return privileges.normalize(self.station.license_class)

    def privilege_problem(self, khz: float | None = None, mode: str | None = None) -> str:
        return privileges.check(self.license_class, self.freq_khz if khz is None else khz,
                                self.mode if mode is None else mode)

    def _check_privileges(self):
        why = self.privilege_problem()
        if why:
            self.banner(f"⚠ {why}", "#ff8080")
            self._priv_warned = True
        elif getattr(self, "_priv_warned", False):
            self._priv_warned = False
            if self.banner_lbl.text().startswith(("⚠", "Not sending")):
                self.banner("")

    def _restrike_spots(self):
        """Spots struck through depend on the license class (and the mode): redraw them."""
        if hasattr(self, "spots_pane"):
            self.spots_pane.refresh()

    def _spot_privilege(self, s) -> str:
        if not self.license_class:
            return ""
        mode = s.mode if s.mode else self.mode
        return privileges.check(self.license_class, s.freq_khz, mode)

    def ask_license_class(self):
        op = self.current_op
        items = ["None (no band limits)"] + privileges.CLASSES
        cur = self.license_class
        text, ok = QInputDialog.getItem(self, "License class", f"{op}'s US license class:", items,
                                        items.index(cur) if cur in items else 0, False)
        if ok:
            self.set_license_class(op, "" if text.startswith("None") else text)

    def set_license_class(self, op: str, cls: str):
        self.settings.setValue(f"op_class/{op.upper()}", privileges.normalize(cls))
        self._profile_changed(op.upper())
        self.banner(f"{op}: {privileges.normalize(cls) or 'no'} band limits")
        self._check_privileges()
        self._restrike_spots()

    def edit_station(self):
        dlg = StationDialog(self.station, self)
        if dlg.exec():
            self.station = dlg.station()
            config.save_station(self.station)
            if self.engine:
                self.engine = ContestEngine(self.engine.rules, self.cty, self.station)
                self.needed_pane.set_engine(self.engine)
                self.needed_spots_pane.set_engine(self.engine)
                self.qsos = self.engine.rescore(self.qsos)
                self._refresh_log()
            self._refresh_radio()
            self.spots_pane.set_filter(self.spots_pane.spot_filter, self._home())
            self._check_privileges()
            self._restrike_spots()

    def _macro_page(self) -> tuple[str, str, list]:
        mode = self.mode if self.mode in self.macros else "SSB"
        page = "RUN" if self.run_mode else "SP"
        return mode, page, self.macros[mode][page]

    def _fkey_menu(self, n: int):
        from PySide6.QtGui import QCursor
        mode, page, rows = self._macro_page()
        label = rows[n].get("label", "") if n < len(rows) else ""
        m = QMenu(self)
        m.addAction(f"Edit F{n + 1} {label}…".replace("  ", " "), lambda: self.edit_fkey(n))
        if self.mode in VOICE_MODES and mode == "SSB":
            m.addAction(f"Record F{n + 1}'s voice message (Ctrl+Shift+F{n + 1})", lambda: self.record_fkey(n))
            path = self.wav_path(rows[n]["wav"]) if n < len(rows) and rows[n].get("wav") else None
            if path is not None and path.exists():
                m.addAction(f"Play F{n + 1} here (not transmitting)", lambda: self.keyer.preview(path))
        m.addSeparator()
        m.addAction("Edit all function keys…", self.edit_macros)
        m.exec(QCursor.pos())

    def edit_fkey(self, n: int):
        """Edit one F-key of the page in use (mode + Run/S&P)."""
        mode, page, rows = self._macro_page()
        while len(rows) <= n:
            rows.append({"key": f"F{len(rows) + 1}", "label": "", "text": "", "wav": ""})
        dlg = FKeyDialog(f"F{n + 1}", page, mode, rows[n], voice=(mode == "SSB"), parent=self)
        r = dlg.exec()
        if r:
            rows[n] = dlg.macro(rows[n])
            config.save_macros(self.macros)
            self._refresh_radio()
            if r == FKeyDialog.RECORD:
                self.record_fkey(n)

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
                                category={"MODE": self.engine.rules["modes"][0],
                                          **band_rules.CABRILLO.get(self.category, {})})
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
            self._maybe_alert(s)

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
            self.telnet_pane.remember(cmd)
            self._cluster_command(cmd)
        self.telnet_pane.cmd.clear()

    # -- cluster command buttons (N1MM style) -----------------------------------
    def cluster_button(self, command: str) -> bool:
        call = self.call.text().strip().upper() or (self.qsos[-1].call if self.qsos else "")
        if "{CALL}" in command and not call:
            self.banner("Type a call first (that button uses {CALL})", "#ffd166")
            return False
        sent = False
        for part in config.expand_cluster_command(command, self.station.call, call, self.freq_khz):
            if part.upper() == "{CONN}":
                self.telnet_pane.append_console("> (reconnecting)")
                self.cluster_connect(False)
                self.cluster_connect(True)
                sent = True
            else:
                sent = self._cluster_command(part) or sent
        return sent

    def edit_cluster_buttons(self):
        dlg = ClusterButtonsDialog(config.cluster_buttons(self.cluster_cfg), self)
        if dlg.exec():
            self.cluster_cfg["buttons"] = dlg.buttons()
            config.save_cluster(self.cluster_cfg)
            self.telnet_pane.set_buttons(config.cluster_buttons(self.cluster_cfg),
                                         self.cluster_cfg.get("show_buttons", True))

    def _show_cluster_buttons(self, show: bool):
        self.cluster_cfg["show_buttons"] = bool(show)
        config.save_cluster(self.cluster_cfg)
        self.telnet_pane.button_box.setVisible(bool(show))

    def go_to_spot(self, s) -> bool:
        """QSY to a spot and put the call in the entry line (S&P). Multi-op: a spot that
        would be a band change asks first (False if you say no)."""
        if not self._approve_band_change(s):
            self.call.setFocus()
            return False
        if self.run_mode:                            # keep the run frequency to come back to
            self.run_memory = {"freq": self.freq_khz, "mode": self.mode}
            self.sp_memory = None
        if self.engine and s.mode in self.engine.rules.get("modes", []) and s.mode != self.mode:
            self.set_mode(s.mode)
        self.run_mode = False
        self.set_freq(s.freq_khz)
        self.wipe()
        self.call.setText(s.call)
        self._on_call_edited(s.call)
        return True

    def chase_list(self) -> list:
        """Needed spots in jump order: mults (newest first), then new Qs if there are no
        mults. Only the band you're on when that's set; never ones you can't transmit on."""
        band_only = bool(self.cluster_cfg.get("chase_band_only")) or self.spots_pane.band_box.currentIndex() == 1
        band = band_from_khz(self.freq_khz)
        spots = [s for s in self.spots_pane.filtered_spots()
                 if not (band_only and s.band != band) and not self._spot_privilege(s)]
        mults = [s for s in spots if s.status == "MULT"]
        return mults or [s for s in spots if s.status == "Q"]

    def go_to_next_needed(self):
        """Ctrl+G: the newest needed spot; pressed again while still on it, the next one
        (wrapping around), so you can step through them all."""
        spots = self.chase_list()
        if not spots:
            where = " on this band" if self.cluster_cfg.get("chase_band_only") else ""
            self.banner(f"No needed spots{where} in the current filter")
            return
        keys = [(s.call, s.band) for s in spots]
        last = getattr(self, "_chase_last", None)        # (call, band, kHz) we jumped to last
        i = 0
        if last and (last[0], last[1]) in keys and abs(self.freq_khz - last[2]) < 0.05:
            i = (keys.index((last[0], last[1])) + 1) % len(keys)
        s = spots[i]
        self._chase_last = (s.call, s.band, s.freq_khz)
        self.go_to_spot(s)
        if len(spots) > 1:
            self.banner(f"{i + 1} of {len(spots)}: {s.call} {s.freq_khz:,.1f} · {self._key('go_needed')} next · "
                        f"{self._key('swap_run')} back to run")

    def next_spot(self, direction: int):
        """S&P down the band: go to the nearest needed spot above (+1) or below (-1) the
        radio on this band. Dupes and spots outside your privileges are skipped."""
        band = band_from_khz(self.freq_khz)
        here = self.freq_khz
        spots = sorted((s for s in self.spots_pane.filtered_spots()
                        if s.band == band and s.status in ("MULT", "Q") and not self._spot_privilege(s)),
                       key=lambda s: s.freq_khz)
        if direction > 0:
            pick = next((s for s in spots if s.freq_khz > here + 0.05), None)
        else:
            pick = next((s for s in reversed(spots) if s.freq_khz < here - 0.05), None)
        if pick is None:
            self.banner(f"No more needed spots {'above' if direction > 0 else 'below'} {here:,.1f} on {band}")
            return
        self.go_to_spot(pick)

    def set_chase_band_only(self, on: bool):
        self.cluster_cfg["chase_band_only"] = bool(on)
        config.save_cluster(self.cluster_cfg)
        if self.chase_band_act.isChecked() != bool(on):
            self.chase_band_act.blockSignals(True); self.chase_band_act.setChecked(bool(on))
            self.chase_band_act.blockSignals(False)
        self._filter_alerts()
        self.banner("Needed mults: only the band you're on" if on else "Needed mults: all bands")

    def _focus_spot_search(self):
        if not self.dock_spots.shown:
            self.dock_spots.set_shown(True)
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
        spots = self.spots_pane.filtered_spots()
        self.needed_pane.update_data(self.qsos, spots)
        if hasattr(self, "needed_spots_pane"):
            self.needed_spots_pane.update_spots(spots, band_from_khz(self.freq_khz))
        if hasattr(self, "bandmap"):
            self.bandmap.update_spots(spots)

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

    # ---------------------------------------------------------- radio (CAT)
    def edit_radio(self):
        dlg = RadioDialog(self.rig_cfg, self.rig.state if self.rig_cfg.get("enabled") else "", self)
        if not dlg.exec():
            return
        self.rig_cfg = dlg.values()
        config.save_rig(self.rig_cfg)
        if self.rig_cfg["enabled"]:
            self.rig.start(self.rig_cfg)
        else:
            self.rig.stop()
        self._refresh_radio()

    def _on_rig_freq(self, khz: float):
        if abs(khz - self.freq_khz) >= 0.001:
            self.set_freq(khz, from_rig=True)

    def _on_rig_mode(self, radio_mode: str):
        modes = self.engine.rules["modes"] if self.engine else []
        m = to_logger_mode(radio_mode, self.mode, modes)
        if m and m != self.mode:
            self.set_mode(m, from_rig=True)

    def refresh_radio(self):
        """Drop the radio connection and open it again, then read frequency and mode
        (after the radio was switched off, its USB unplugged, or it stopped answering)."""
        if not self.rig_cfg.get("enabled"):
            self.banner("The radio isn't set up: Config ▸ Radio", "#ffd166")
            return
        self.rig.stop()
        self.rig.start(self.rig_cfg)
        self.banner("Reconnecting to the radio…")

    def _on_rig_state(self, text: str):
        self.rig_lbl.setVisible(text != "off")
        self.rig_refresh_btn.setVisible(text != "off")
        ok = text.startswith("connected to")
        self.rig_lbl.setText(("● " if ok else "○ ") + "Radio" + ("" if self.rig.control or not ok else " (follow)"))
        self.rig_lbl.setStyleSheet(f"color: {'#2a9d4b' if ok else '#c77d00'}; font-weight: bold;")
        self.rig_lbl.setToolTip(f"Radio: {text}  (Config ▸ Radio)")

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
                q.exch_sent = self.engine.sent_exchange(self.qsos, for_log=True)
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
    def update_scp(self):
        self.banner("Downloading the latest Super Check Partial file…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            download_scp()
            self.scp = self._load_scp()
        except Exception as e:                       # network down, an error page, ...
            QApplication.restoreOverrideCursor()
            self.banner(f"Couldn't update Super Check Partial: {e}", "#ffd166")
            return
        QApplication.restoreOverrideCursor()
        self._update_partials(self.call.text().strip().upper())
        self.banner(f"Super Check Partial updated ({len(self.scp):,} calls)")

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
            self.needed_spots_pane.set_engine(self.engine)
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
        """Quiet check; only speaks up if there's something new. Running from a git
        clone: every start (and then daily), since new code lands often. Otherwise daily."""
        every = 3600 if updater.install_kind() == "git" else 86400
        if time.time() - float(self.settings.value("last_update_check", 0) or 0) < every:
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
            new = rel.changes > 0 if rel.changes >= 0 else updater.is_newer(rel.version)
            if not new:
                if not quiet:
                    QMessageBox.information(self, "Check for updates",
                                            f"You're up to date: tttlog {updater.display_version()}.")
                return
            box = QMessageBox(self)
            box.setWindowTitle("Update available")
            if rel.changes > 0:
                box.setText(f"<b>{rel.changes} new change{'s' if rel.changes != 1 else ''}</b> on GitHub. "
                            f"Update now and restart tttlog?")
            else:
                box.setText(f"<b>tttlog {rel.version}</b> is available. You have {updater.display_version()}.")
            notes = rel.notes.strip()
            box.setInformativeText(notes[:900] + ("…" if len(notes) > 900 else ""))
            go = box.addButton("Update now", QMessageBox.AcceptRole)
            box.addButton("Later", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is go:
                self.install_update(rel)
        self._bg(updater.fetch_git_changes if updater.install_kind() == "git" else updater.fetch_latest, done)

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
                self.banner("Update installed: restarting")
                updater.restart_from_source()            # you said Update now: go straight on
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
        return list(self.canvas.panes.values())

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

    # -- layouts (grid positions), per operator ----------------------------------------
    def _load_grid_setting(self, key: str) -> dict | None:
        import json
        if str(self.settings.value(f"{key}_version", "")) != LAYOUT_VERSION:
            return None
        try:
            v = json.loads(str(self.settings.value(key, "") or ""))
        except ValueError:
            return None
        return v if isinstance(v, dict) and v else None

    def _save_grid_setting(self, key: str):
        import json
        self.settings.setValue(key, json.dumps(self.canvas.to_dict()))
        self.settings.setValue(f"{key}_version", LAYOUT_VERSION)

    def _op_layout(self, op: str) -> dict | None:
        grid = self._load_grid_setting(f"layouts/{op.upper()}/grid")
        if not grid:
            return None
        return {"grid": grid, "geometry": self.settings.value(f"layouts/{op.upper()}/geometry")}

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "_layout_save") and self.isVisible():
            self._layout_save.start()

    def moveEvent(self, ev):
        super().moveEvent(ev)
        if hasattr(self, "_layout_save") and self.isVisible():
            self._layout_save.start()

    def _autosave_layout(self):
        """The layout as it is now, for next time and for the operator at this station."""
        self.settings.setValue("geometry", self.saveGeometry())
        self._save_grid_setting("grid_layout")
        self.save_op_layout(quiet=True)

    def save_op_layout(self, op: str | None = None, quiet: bool = False):
        """Remember the layout for an operator (View ▸ Save layout; also on OPON and on close)."""
        op = (op or self.current_op).upper()
        self._save_grid_setting(f"layouts/{op}/grid")
        self.settings.setValue(f"layouts/{op}/geometry", self.saveGeometry())
        self._profile_changed(op)
        if not quiet:
            self.banner(f"Layout saved for {op}: OPON {op} brings it back")

    # -- operator profiles travel between networked stations ---------------------------
    def _profile_data(self, op: str) -> dict:
        """What follows an operator to another station: pane layout and license class
        (not window size or position: every computer's screen is different)."""
        import json
        op = op.upper()
        d = {}
        grid = self._load_grid_setting(f"layouts/{op}/grid")
        if grid:
            d["grid"], d["v"] = grid, LAYOUT_VERSION
        cls = self.settings.value(f"op_class/{op}")
        if cls is not None:
            d["class"] = str(cls)
        return d

    def _profile_changed(self, op: str):
        import time as _t
        at = _t.time()
        self.settings.setValue(f"layouts/{op}/at", at)
        if self.net.running:
            self.net.publish_profile(op, self._profile_data(op), at)
        else:
            self.net.profiles[op] = (at, self._profile_data(op))

    def _seed_profiles(self):
        """Give the network node every operator profile saved on this computer."""
        self.settings.beginGroup("layouts")
        ops = [g for g in self.settings.childGroups()]
        self.settings.endGroup()
        self.settings.beginGroup("op_class")
        ops += [k for k in self.settings.childKeys()]
        self.settings.endGroup()
        for op in dict.fromkeys(o.upper() for o in ops):
            try:
                at = float(self.settings.value(f"layouts/{op}/at", 0) or 0)
            except (TypeError, ValueError):
                at = 0.0
            data = self._profile_data(op)
            if data:
                self.net.profiles[op] = (at, data)

    def _on_profile_received(self, op: str, data: dict, at: float):
        """Another station saved this operator's profile: keep it for their next OPON here."""
        import json
        try:
            mine = float(self.settings.value(f"layouts/{op}/at", 0) or 0)
        except (TypeError, ValueError):
            mine = 0.0
        if at <= mine:
            return
        if isinstance(data.get("grid"), dict) and data.get("v") == LAYOUT_VERSION:   # same grid as ours
            self.settings.setValue(f"layouts/{op}/grid", json.dumps(data["grid"]))
            self.settings.setValue(f"layouts/{op}/grid_version", LAYOUT_VERSION)
        if "class" in data:
            self.settings.setValue(f"op_class/{op}", privileges.normalize(str(data["class"])))
        self.settings.setValue(f"layouts/{op}/at", at)

    def load_op_layout(self, op: str) -> bool:
        lay = self._op_layout(op)
        if not lay:
            return False
        self.canvas.from_dict(lay["grid"])           # panes only: the window stays where it is
        return True

    def reset_layout(self):
        """Back to tttlog's default arrangement (an operator's saved layout is kept
        until they save again or OPON away)."""
        self.canvas.from_dict({f"dock_{name}": {"r": list(r), "min": name in DEFAULT_MINIMIZED, "shown": True}
                               for name, r in DEFAULT_GRID.items()})

    def minimize_all_panes(self):
        for d in self.panes:
            if d.shown:
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
        self._save_grid_setting("grid_layout")
        self.save_op_layout(quiet=True)
        for d in self.panes:                        # popped-out panes are their own windows
            if d.isFloating():
                d.hide()
        self.cluster.disconnect_from()
        self.net.stop()
        self.wsjtx.stop()
        self.keyer.shutdown()
        self.rig.stop()
        if self.log:
            self.log.close()
        super().closeEvent(ev)
