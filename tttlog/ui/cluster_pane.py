"""DX cluster: telnet client, the Telnet window (raw text), and the Spots window.

The Telnet window can be hidden; the connection keeps running and the Spots
window keeps filling. The Spots window shows only what you pick: mults, Qs,
and/or dupes, each in its own color.
"""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.cluster import LOGIN_RE, Spot, SpotList, split_telnet
from .widgets import StateToggle, text_color_for

RECONNECT_MS = 30_000

# spot status -> colors-dict key
STATUS_KEY = {"MULT": "spot_mult", "Q": "spot_q", "DUPE": "spot_dupe", "INVALID": "spot_dupe"}


class ClusterClient(QObject):
    """Line-oriented telnet client on a QTcpSocket (never blocks the UI)."""

    line = Signal(str)
    state = Signal(str)           # human-readable connection state

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sock = QTcpSocket(self)
        self.sock.readyRead.connect(self._read)
        self.sock.connected.connect(self._on_connected)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.errorOccurred.connect(self._on_error)
        self._buf = b""
        self._raw_tail = b""          # unfinished telnet sequence carried to the next read
        self._redialing = False       # our own abort() while reconnecting: don't schedule a retry
        self._want = False            # user wants to be connected (drives auto-reconnect)
        self._logged_in = False
        self.host, self.port, self.login, self.init_commands = "", 0, "", []
        self._retry = QTimer(self, singleShot=True, interval=RECONNECT_MS, timeout=self._dial)

    # -- control --------------------------------------------------------
    def connect_to(self, host: str, port: int, login: str, init_commands: list[str] | None = None):
        self.host, self.port, self.login = host, int(port), login.upper()
        self.init_commands = list(init_commands or [])
        self._want = True
        self._dial()

    def disconnect_from(self):
        self._want = False
        self._retry.stop()
        self.sock.abort()
        self.state.emit("Disconnected")

    def is_connected(self) -> bool:
        return self.sock.state() == QAbstractSocket.ConnectedState

    def send(self, text: str):
        if self.is_connected():
            self.sock.write((text + "\r\n").encode("latin-1", "replace"))

    # -- socket events ----------------------------------------------------
    def _dial(self):
        if not self._want:
            return
        self._retry.stop()
        self._buf, self._raw_tail, self._logged_in = b"", b"", False
        self._redialing = True
        try:
            self.sock.abort()
        finally:
            self._redialing = False
        self.state.emit(f"Connecting to {self.host}:{self.port}…")
        self.sock.connectToHost(self.host, self.port)

    def _on_connected(self):
        self._retry.stop()
        self.state.emit(f"Connected to {self.host}")

    def _on_disconnected(self):
        if self._want and not self._redialing:
            self.state.emit(f"Lost connection, retrying in {RECONNECT_MS // 1000}s")
            self._retry.start()

    def _on_error(self, _err):
        if self._want and not self._redialing:
            self.state.emit(f"{self.sock.errorString()}, retrying in {RECONNECT_MS // 1000}s")
            self._retry.start()

    def _read(self):
        clean, self._raw_tail = split_telnet(self._raw_tail + bytes(self.sock.readAll()))
        if len(self._raw_tail) > 4096:           # unterminated subnegotiation: give up on it
            self._raw_tail = b""
        self._buf += clean
        *lines, self._buf = self._buf.replace(b"\r", b"").split(b"\n")
        for raw in lines:
            text = raw.decode("latin-1").rstrip()
            self.line.emit(text)
            self._maybe_login(text)
        # Login prompts usually arrive without a newline. Once answered, flush the
        # prompt so it isn't glued to the front of the next line (the first spot).
        if self._buf and self._maybe_login(self._buf.decode("latin-1")):
            self.line.emit(self._buf.decode("latin-1").rstrip())
            self._buf = b""

    def _maybe_login(self, text: str) -> bool:
        if self._logged_in or not self.login or not LOGIN_RE.search(text.strip()):
            return False
        self._logged_in = True
        self.send(self.login)
        self.state.emit(f"Logged in to {self.host} as {self.login}")
        for i, cmd in enumerate(self.init_commands):
            QTimer.singleShot(1000 * (i + 1), lambda c=cmd: self.send(c))
        return True


class TelnetPane(QWidget):
    """Connection controls + raw cluster text + command line. Safe to hide."""

    connectRequested = Signal(bool)          # True = connect, False = disconnect

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.conn_btn = QPushButton("Connect")
        self.conn_btn.setFocusPolicy(Qt.NoFocus)
        self.conn_btn.clicked.connect(lambda: self.connectRequested.emit(self.conn_btn.text() == "Connect"))
        self.status_lbl = QLabel("Not connected")
        bar.addWidget(self.conn_btn); bar.addWidget(self.status_lbl, 1)
        v.addLayout(bar)
        self.console = QPlainTextEdit(readOnly=True)
        self.console.setMaximumBlockCount(1000)
        self.console.setStyleSheet('font: 10pt "Menlo", "Consolas", monospace;')
        self.cmd = QLineEdit(placeholderText="Cluster command (e.g. sh/dx 30), Enter to send")
        self.cmd.setStyleSheet("font: 11pt;")
        v.addWidget(self.console, 1)
        v.addWidget(self.cmd)

    def set_connected(self, connected: bool, text: str):
        self.status_lbl.setText(text)
        self.conn_btn.setText("Disconnect" if connected else "Connect")

    def append_console(self, text: str):
        self.console.appendPlainText(text)


class SpotsPane(QWidget):
    """Spots you can work, filtered to the kinds you tick (mults / Qs / dupes)."""

    spotActivated = Signal(object)          # Spot; later this will also tune the radio
    colorsChanged = Signal()

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.spots = SpotList()
        self.current_band: str | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        self.toggles = {
            "spot_mult": StateToggle("spot_mult", "Mults", colors),
            "spot_q": StateToggle("spot_q", "Qs", colors),
            "spot_dupe": StateToggle("spot_dupe", "Dupes / can't work", colors),
        }
        for t in self.toggles.values():
            t.changed.connect(self._on_toggle)
            bar.addWidget(t)
        bar.addStretch()
        self.band_box = QComboBox(); self.band_box.addItems(["All bands", "Current band"])
        self.band_box.setFocusPolicy(Qt.NoFocus)
        self.band_box.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.band_box)
        v.addLayout(bar)

        bar2 = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search call / country / comment")
        self.search.setStyleSheet("font: 11pt;")
        self.search.textChanged.connect(self.refresh)
        self.summary_lbl = QLabel()
        bar2.addWidget(self.search, 1); bar2.addWidget(self.summary_lbl)
        v.addLayout(bar2)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Time", "kHz", "Call", "Country", "Need", "Spotter", "Comment"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._activate_row)
        self.table.setFocusPolicy(Qt.ClickFocus)
        v.addWidget(self.table, 1)

        self._shown: list[Spot] = []
        self.refreshes = 0
        self._dirty = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)

    def _on_toggle(self):
        self.refresh()
        self.colorsChanged.emit()

    def _schedule_refresh(self):
        # Throttle, don't debounce: restarting the timer on every spot would
        # starve the table during a busy cluster.
        if not self._dirty.isActive():
            self._dirty.start()

    def sync_colors(self):
        for t in self.toggles.values():
            t.sync()
        self.refresh()

    # -- quick filters (menu shortcuts) ------------------------------------
    def show_only(self, *keys: str):
        for k, t in self.toggles.items():
            self.colors[k]["show"] = k in keys
            t.sync()
        self._on_toggle()

    # -- data in ----------------------------------------------------------
    def add_spot(self, s: Spot, engine, log):
        self.spots.add(s)
        if engine:
            self.spots.evaluate(engine, log, only=[s])
        self._schedule_refresh()

    def reevaluate(self, engine, log):
        if engine:
            self.spots.evaluate(engine, log)
        self._schedule_refresh()

    def prune(self, now: datetime) -> bool:
        before = len(self.spots)
        self.spots.prune(now)
        if len(self.spots) != before:
            self._schedule_refresh()
            return True
        return False

    # -- view ---------------------------------------------------------------
    def visible_spots(self) -> list[Spot]:
        band_only = self.band_box.currentIndex() == 1
        q = self.search.text().strip().upper()
        out = []
        for s in self.spots.spots():
            key = STATUS_KEY.get(s.status, "spot_dupe")
            if not self.colors[key].get("show", True):
                continue
            if band_only and self.current_band and s.band != self.current_band:
                continue
            if q and q not in s.call and q not in s.country.upper() and q not in s.comment.upper():
                continue
            out.append(s)
        return out

    def refresh(self):
        self.refreshes += 1
        shown = self.visible_spots()
        self._shown = shown
        t = self.table
        t.setRowCount(len(shown))
        for r, s in enumerate(shown):
            need = ", ".join(s.mults) if s.status == "MULT" else s.status
            vals = [s.time_utc.strftime("%H%M"), f"{s.freq_khz:.1f}", s.call, s.country,
                    need, s.spotter, s.comment]
            bg = self.colors[STATUS_KEY.get(s.status, "spot_dupe")]["color"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setBackground(QBrush(QColor(bg)))
                it.setForeground(QBrush(QColor(text_color_for(bg))))
                t.setItem(r, c, it)
        all_ = self.spots.spots()
        n_mult = sum(1 for s in all_ if s.status == "MULT")
        n_q = sum(1 for s in all_ if s.status == "Q")
        self.summary_lbl.setText(f"{n_mult} mults · {n_q} Qs available · {len(all_)} spots")

    def _activate_row(self, index):
        if 0 <= index.row() < len(self._shown):
            self.spotActivated.emit(self._shown[index.row()])


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
