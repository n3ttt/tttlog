"""Dialogs: new log, station profile, macro editor, QSO edit."""
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QDoubleSpinBox, QHeaderView)

from ..contests.engine import Station, list_contests
from ..core.models import QSO


def _buttons(dlg):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class ClusterDialog(QDialog):
    def __init__(self, cfg: dict, station_call: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DX cluster")
        self._cfg = dict(cfg)
        f = QFormLayout(self)
        self.host = QLineEdit(str(cfg.get("host", "")))
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(int(cfg.get("port", 7373)))
        self.login = QLineEdit(str(cfg.get("login", "")))
        self.login.setPlaceholderText(f"{station_call}  (station call)")
        self.age = QSpinBox(); self.age.setRange(5, 240); self.age.setSuffix(" min")
        self.age.setValue(int(cfg.get("max_age_min", 30)))
        self.auto = QCheckBox("Connect when tttlog starts")
        self.auto.setChecked(bool(cfg.get("auto_connect", False)))
        self.auto_spot = QCheckBox("Auto-spot QSOs made in S&&P (call + frequency)")
        self.auto_spot.setChecked(bool(cfg.get("auto_spot_sp", False)))
        self.init = QLineEdit("; ".join(cfg.get("init_commands", [])))
        self.init.setPlaceholderText("e.g.  set/skimmer; sh/dx 30")
        self.kind = QComboBox()
        for key, text in [("auto", "Detect from login"), ("ar", "AR-Cluster (e.g. W3LPL, K1TTT)"),
                          ("cc", "CC Cluster (e.g. VE7CC)"), ("spider", "DXSpider")]:
            self.kind.addItem(text, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(cfg.get("cluster_type", "auto"))))
        self.kind.setToolTip("Decides which commands 'Send this filter to the cluster' uses")
        self.share = QCheckBox("Share my cluster connection with stations on the local network")
        self.share.setChecked(bool(cfg.get("share_cluster", True)))
        self.use_net = QCheckBox("When I'm not connected, use a networked station's connection")
        self.use_net.setChecked(bool(cfg.get("use_network_cluster", True)))
        for lbl, w in [("Host", self.host), ("Port", self.port), ("Login call", self.login),
                       ("Keep spots for", self.age), ("", self.auto), ("", self.auto_spot),
                       ("Commands after login", self.init), ("Cluster software", self.kind),
                       ("", self.share), ("", self.use_net)]:
            f.addRow(lbl, w)
        f.addRow(_buttons(self))

    def values(self) -> dict:
        out = dict(self._cfg)
        out.update(host=self.host.text().strip(), port=self.port.value(),
                   login=self.login.text().strip().upper(), max_age_min=self.age.value(),
                   auto_connect=self.auto.isChecked(), auto_spot_sp=self.auto_spot.isChecked(),
                   init_commands=[c.strip() for c in self.init.text().split(";") if c.strip()],
                   cluster_type=self.kind.currentData(), share_cluster=self.share.isChecked(),
                   use_network_cluster=self.use_net.isChecked())
        return out


class StationDialog(QDialog):
    def __init__(self, st: Station, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Station profile")
        f = QFormLayout(self)
        self.call = QLineEdit(st.call)
        self.op = QLineEdit(st.operator)
        self.state = QLineEdit(st.state)
        self.zone = QSpinBox(); self.zone.setRange(1, 40); self.zone.setValue(st.cq_zone)
        self.itu = QSpinBox(); self.itu.setRange(1, 90); self.itu.setValue(st.itu_zone)
        self.grid = QLineEdit(st.grid)
        self.name = QLineEdit(st.name)
        self.addr = QLineEdit(" | ".join(st.address))
        self.club = QLineEdit(st.club)
        self.email = QLineEdit(st.email)
        from ..core.privileges import CLASSES, normalize
        self.lic = QComboBox()
        self.lic.addItem("None (no band limits)", "")
        for c in CLASSES:
            self.lic.addItem(c, c)
        self.lic.setCurrentIndex(max(0, self.lic.findData(normalize(st.license_class))))
        self.lic.setToolTip("US license class: tttlog warns when you're outside its privileges, keeps "
                            "band buttons inside them, and won't key the radio outside them")
        for lbl, w in [("Call", self.call), ("Operator", self.op), ("State/Prov", self.state),
                       ("CQ zone", self.zone), ("ITU zone", self.itu), ("Grid", self.grid),
                       ("Name", self.name), ("Address (use | between lines)", self.addr),
                       ("Club", self.club), ("Email", self.email), ("US license class", self.lic)]:
            f.addRow(lbl, w)
        f.addRow(_buttons(self))

    def station(self) -> Station:
        return Station(call=self.call.text().upper().strip(), operator=self.op.text().upper().strip(),
                       state=self.state.text().upper().strip(), cq_zone=self.zone.value(),
                       itu_zone=self.itu.value(), grid=self.grid.text().upper().strip(),
                       name=self.name.text().strip(),
                       address=[a.strip() for a in self.addr.text().split("|") if a.strip()],
                       club=self.club.text().strip(), email=self.email.text().strip(),
                       license_class=self.lic.currentData() or "")


class NewLogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New log")
        f = QFormLayout(self)
        self.contest = QComboBox()
        self._contests = list_contests()
        for c in self._contests:
            self.contest.addItem(c["name"], c["id"])
        self.path = QLineEdit()
        browse = QPushButton("…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout(); row.addWidget(self.path); row.addWidget(browse)
        f.addRow("Contest / log type", self.contest)
        f.addRow("Log file", row)
        f.addRow(_buttons(self))
        self.contest.currentIndexChanged.connect(self._default_path)
        self._default_path()

    def _default_path(self):
        d = Path.home() / "Documents" / "tttlog"
        cid = self.contest.currentData() or "log"
        if cid == "GENERAL":                       # one general log you keep adding to
            self.path.setText(str(d / "general_log.db"))
        else:
            self.path.setText(str(d / f"{cid}_{datetime.utcnow():%Y%m%d}.db"))

    def _browse(self):
        p, _ = QFileDialog.getSaveFileName(self, "Log file", self.path.text(), "Log (*.db)")
        if p:
            self.path.setText(p)

    def values(self) -> tuple[str, Path]:
        return self.contest.currentData(), Path(self.path.text())


class MacroDialog(QDialog):
    """Edit the 12 function keys for each mode (SSB/CW) and Run/S&P."""
    COLS = ["Key", "Label", "Text", "WAV (SSB)"]

    def __init__(self, macros: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Function-key macros")
        self.resize(760, 460)
        self.macros = copy.deepcopy(macros)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(list(self.macros.keys()))
        self.page = QComboBox(); self.page.addItems(["RUN", "SP"])
        top.addWidget(self.mode); top.addWidget(self.page); top.addStretch()
        v.addLayout(top)
        self.table = QTableWidget(12, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        v.addWidget(self.table)
        hint = QLabel("Text fields: {MYCALL} {CALL} {EXCH} {RST} {STATE} {ZONE} are filled in.  "
                      "Actions: {CLEAR} wipes the entry line, {SPOT} spots the last QSO to the cluster.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addWidget(_buttons(self))
        self._cur = None
        self.mode.currentIndexChanged.connect(self._switch)
        self.page.currentIndexChanged.connect(self._switch)
        self._switch()

    def _store(self):
        if not self._cur:
            return
        m, p = self._cur
        rows = []
        for r in range(12):
            get = lambda c: (self.table.item(r, c).text() if self.table.item(r, c) else "")
            rows.append({"key": f"F{r + 1}", "label": get(1), "text": get(2), "wav": get(3)})
        self.macros[m][p] = rows

    def _switch(self):
        self._store()
        m, p = self.mode.currentText(), self.page.currentText()
        self._cur = (m, p)
        for r, row in enumerate(self.macros[m][p][:12]):
            for c, k in enumerate(["key", "label", "text", "wav"]):
                it = QTableWidgetItem(str(row.get(k, "")))
                self.table.setItem(r, c, it)

    def result_macros(self) -> dict:
        self._store()
        return self.macros


class FKeyDialog(QDialog):
    """Right-click an F-key button: edit that one key (label, text, voice file)."""
    RECORD = 2                                   # exec() result: save, then record the voice message

    def __init__(self, key: str, page: str, mode: str, macro: dict, voice: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{key} · {mode} {page}")
        self.resize(460, 0)
        f = QFormLayout(self)
        self.label = QLineEdit(macro.get("label", ""))
        self.text = QLineEdit(macro.get("text", ""))
        self.wav = QLineEdit(macro.get("wav", ""))
        f.addRow("Label", self.label)
        f.addRow("Text" if not voice else "Text (shown)", self.text)
        if voice:
            f.addRow("Voice file", self.wav)
        hint = QLabel("{MYCALL} {CALL} {EXCH} {RST} {STATE} {ZONE} are filled in · "
                      "{CLEAR} wipes the entry line · {SPOT} spots the last QSO")
        hint.setWordWrap(True)
        f.addRow(hint)
        box = _buttons(self)
        if voice:
            rec = box.addButton("Save && record…", QDialogButtonBox.ActionRole)
            rec.setToolTip("Save, then record this key's message (Esc or the key again to stop)")
            rec.clicked.connect(lambda: self.done(self.RECORD))
        f.addRow(box)
        self.voice = voice
        self.text.setFocus()

    def macro(self, old: dict) -> dict:
        out = dict(old)
        out.update(label=self.label.text().strip(), text=self.text.text().strip())
        if self.voice:
            from ..core.keyer import safe_wav_name
            w = self.wav.text().strip()
            out["wav"] = safe_wav_name(w) if w else ""
        return out


class EditQsoDialog(QDialog):
    def __init__(self, q: QSO, parent=None):
        super().__init__(parent)
        self.q = q
        self.setWindowTitle(f"Edit QSO {q.call}")
        f = QFormLayout(self)
        self.call = QLineEdit(q.call)
        self.freq = QDoubleSpinBox(); self.freq.setRange(1800, 450000); self.freq.setDecimals(1)
        self.freq.setValue(q.freq_khz)
        self.mode = QComboBox(); self.mode.addItems(["SSB", "CW", "RTTY", "FT8"])
        self.mode.setCurrentText(q.mode)
        self.time = QLineEdit(q.time_utc.strftime("%Y-%m-%d %H:%M:%S"))
        self.rst_s = QLineEdit(q.rst_sent); self.rst_r = QLineEdit(q.rst_rcvd)
        self.ex_s = QLineEdit(q.exch_sent); self.ex_r = QLineEdit(q.exch_rcvd)
        for lbl, w in [("Call", self.call), ("Freq kHz", self.freq), ("Mode", self.mode),
                       ("Time UTC", self.time), ("RST sent", self.rst_s), ("RST rcvd", self.rst_r),
                       ("Exch sent", self.ex_s), ("Exch rcvd", self.ex_r)]:
            f.addRow(lbl, w)
        f.addRow(_buttons(self))

    def apply(self) -> QSO:
        q = self.q
        q.call = self.call.text().upper().strip()
        q.freq_khz = self.freq.value()
        q.mode = self.mode.currentText()
        q.time_utc = datetime.strptime(self.time.text().strip(), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=q.time_utc.tzinfo)
        q.rst_sent, q.rst_rcvd = self.rst_s.text().strip(), self.rst_r.text().strip()
        q.exch_sent, q.exch_rcvd = self.ex_s.text().upper().strip(), self.ex_r.text().upper().strip()
        return q


class NetworkDialog(QDialog):
    """Config ▸ Local network: share one log between computers in the shack."""

    def __init__(self, cfg: dict, port_in_use: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Local network")
        self._cfg = dict(cfg)
        f = QFormLayout(self)
        self.enabled = QCheckBox("Share the log with other tttlog stations on this network")
        self.enabled.setChecked(bool(cfg.get("enabled")))
        self.name = QLineEdit(str(cfg.get("station_name", "")))
        self.name.setMaxLength(16)
        self.name.setPlaceholderText("e.g. RUN1, MULT, SHACK")
        self.net = QLineEdit(str(cfg.get("net_name", "TTTLOG")))
        self.net.setMaxLength(32)
        self.tcp = QSpinBox(); self.tcp.setRange(1024, 65535); self.tcp.setValue(int(cfg.get("tcp_port", 12071)))
        self.udp = QSpinBox(); self.udp.setRange(1024, 65535); self.udp.setValue(int(cfg.get("udp_port", 12070)))
        self.peers = QLineEdit(", ".join(cfg.get("peers", [])))
        self.peers.setPlaceholderText("only if stations don't find each other, e.g. 192.168.1.20, shack-pc:12071")
        note = QLabel(
            "Stations with the same network name and the same contest share one log:\n"
            "every QSO, edit and delete shows up on all of them, and dupes count across stations.\n"
            "Each station keeps a full copy, so a station that drops out catches up when it's back.\n"
            "Windows will ask to allow tttlog through the firewall: allow it on Private networks."
            + (f"\nListening now on port {port_in_use}." if port_in_use else ""))
        note.setWordWrap(True)
        f.addRow(self.enabled)
        for lbl, w in [("This station's name", self.name), ("Network name", self.net),
                       ("TCP port", self.tcp), ("Discovery (UDP) port", self.udp),
                       ("Other stations by address", self.peers)]:
            f.addRow(lbl, w)
        f.addRow(note)
        f.addRow(_buttons(self))

    def values(self) -> dict:
        out = dict(self._cfg)
        out.update(enabled=self.enabled.isChecked(),
                   station_name=self.name.text().strip().upper() or out.get("station_name", ""),
                   net_name=self.net.text().strip().upper() or "TTTLOG",
                   tcp_port=self.tcp.value(), udp_port=self.udp.value(),
                   peers=[p.strip() for p in self.peers.text().replace(";", ",").split(",") if p.strip()])
        return out


class WsjtxDialog(QDialog):
    """Config ▸ WSJT-X: log QSOs that WSJT-X / JTDX / MSHV logs."""

    def __init__(self, cfg: dict, state: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("WSJT-X")
        self._cfg = dict(cfg)
        f = QFormLayout(self)
        self.enabled = QCheckBox("Log QSOs from WSJT-X (also JTDX, MSHV)")
        self.enabled.setChecked(bool(cfg.get("enabled")))
        self.address = QLineEdit(str(cfg.get("address", "127.0.0.1")))
        self.address.setPlaceholderText("127.0.0.1, or a multicast group like 224.0.0.1")
        self.port = QSpinBox(); self.port.setRange(1024, 65535); self.port.setValue(int(cfg.get("port", 2237)))
        note = QLabel(
            "In WSJT-X: File > Settings > Reporting > UDP Server. Use the same address and port as here "
            "(WSJT-X's default is 127.0.0.1, port 2237). When you click Log QSO in WSJT-X, the QSO goes "
            "into the open tttlog log (and to the other networked stations).\n"
            "If GridTracker or JTAlert already listens on that port, set WSJT-X and all of them to a "
            "multicast address such as 224.0.0.1 so each gets every QSO."
            + (f"\nNow: {state}" if state else ""))
        note.setWordWrap(True)
        f.addRow(self.enabled)
        f.addRow("UDP Server address", self.address)
        f.addRow("UDP Server port", self.port)
        f.addRow(note)
        f.addRow(_buttons(self))

    def values(self) -> dict:
        out = dict(self._cfg)
        out.update(enabled=self.enabled.isChecked(),
                   address=self.address.text().strip() or "127.0.0.1", port=self.port.value())
        return out


class RadioDialog(QDialog):
    """Config ▸ Radio: CAT connection (Flex via SmartSDR, Kenwood/Elecraft, Yaesu)."""

    def __init__(self, cfg: dict, state: str = "", parent=None):
        from ..core.rig import DIALECTS
        super().__init__(parent)
        self.setWindowTitle("Radio")
        self._cfg = dict(cfg)
        f = QFormLayout(self)
        self.enabled = QCheckBox("Connect to the radio")
        self.enabled.setChecked(bool(cfg.get("enabled")))
        self.dialect = QComboBox()
        for key, name in DIALECTS.items():
            self.dialect.addItem(name, key)
        self.dialect.setCurrentIndex(max(0, self.dialect.findData(cfg.get("dialect", "flex"))))
        self.conn = QComboBox()
        self.conn.addItem("Network (TCP)", "tcp")
        self.conn.addItem("Serial / USB", "serial")
        self.conn.setCurrentIndex(max(0, self.conn.findData(cfg.get("connection", "tcp"))))
        self.host = QLineEdit(str(cfg.get("host", "127.0.0.1")))
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(int(cfg.get("port", 5002)))
        self.serial = QComboBox(); self.serial.setEditable(True)
        try:
            from PySide6.QtSerialPort import QSerialPortInfo
            for info in QSerialPortInfo.availablePorts():
                self.serial.addItem(f"{info.portName()}  {info.description()}".strip(), info.portName())
        except ImportError:
            pass
        cur = str(cfg.get("serial_port", ""))
        i = self.serial.findData(cur)
        if i >= 0:
            self.serial.setCurrentIndex(i)
        else:
            self.serial.setEditText(cur)
        self.baud = QComboBox(); self.baud.setEditable(True)
        for b in ("4800", "9600", "19200", "38400", "57600", "115200"):
            self.baud.addItem(b)
        self.baud.setCurrentText(str(cfg.get("baud", 38400)))
        self.control = QCheckBox("Let tttlog tune the radio (band buttons, typed kHz, spots, mode)")
        self.control.setChecked(bool(cfg.get("control")))
        note = QLabel(
            "Without that box ticked tttlog only reads the radio: it follows the dial and logs the real "
            "frequency and mode, and never changes anything on the radio.\n"
            "FlexRadio on a Mac: SmartSDR for Mac's CAT port (default 127.0.0.1, port 5002). "
            "On Windows: a TCP port from SmartSDR CAT.\n"
            "Yaesu FTDX10: Serial / USB, the radio's Enhanced COM port, at the radio's CAT RATE."
            + (f"\nNow: {state}" if state else ""))
        note.setWordWrap(True)
        f.addRow(self.enabled)
        f.addRow("Radio", self.dialect)
        f.addRow("Connection", self.conn)
        f.addRow("Host", self.host)
        f.addRow("TCP port", self.port)
        f.addRow("Serial port", self.serial)
        f.addRow("Baud", self.baud)
        f.addRow(self.control)
        f.addRow(note)
        f.addRow(_buttons(self))
        self.conn.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        tcp = self.conn.currentData() == "tcp"
        for w in (self.host, self.port):
            w.setEnabled(tcp)
        for w in (self.serial, self.baud):
            w.setEnabled(not tcp)

    def values(self) -> dict:
        out = dict(self._cfg)
        text = self.serial.currentText().strip()
        idx = self.serial.currentIndex()
        if idx >= 0 and text == self.serial.itemText(idx):
            port = self.serial.itemData(idx)                # picked from the list
        else:
            port = text.split()[0] if text else ""          # typed by hand
        try:
            baud = int(self.baud.currentText())
        except ValueError:
            baud = 38400
        out.update(enabled=self.enabled.isChecked(), dialect=self.dialect.currentData(),
                   connection=self.conn.currentData(), host=self.host.text().strip() or "127.0.0.1",
                   port=self.port.value(), serial_port=port, baud=baud,
                   control=self.control.isChecked())
        return out


def _serial_combo(current: str) -> QComboBox:
    box = QComboBox(); box.setEditable(True)
    box.addItem("(none)", "")
    try:
        from PySide6.QtSerialPort import QSerialPortInfo
        for info in QSerialPortInfo.availablePorts():
            box.addItem(f"{info.portName()}  {info.description()}".strip(), info.portName())
    except ImportError:
        pass
    i = box.findData(current)
    if i >= 0:
        box.setCurrentIndex(i)
    else:
        box.setEditText(current)
    return box


def _serial_value(box: QComboBox) -> str:
    text, idx = box.currentText().strip(), box.currentIndex()
    if idx >= 0 and text == box.itemText(idx):
        return box.itemData(idx) or ""
    return text.split()[0] if text and text != "(none)" else ""


class ClusterButtonsDialog(QDialog):
    """Right-click the cluster command buttons ▸ Edit buttons: 12 x (label, command)."""

    def __init__(self, buttons: list[dict], parent=None):
        from .. import config
        super().__init__(parent)
        self.setWindowTitle("Cluster command buttons")
        self.resize(560, 470)
        v = QVBoxLayout(self)
        self.table = QTableWidget(12, 2)
        self.table.setHorizontalHeaderLabels(["Button", "Command sent to the cluster"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._fill(buttons)
        v.addWidget(self.table)
        hint = QLabel("{MYCALL} your call · {CALL} the call in the entry line (else your last QSO's) · "
                      "{FREQ} your frequency in kHz · {CONN} reconnect to the cluster · "
                      "| between commands sends several, e.g.  SH/DX 30 | SH/WWV")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = QHBoxLayout()
        reset = QPushButton("Back to the defaults")
        reset.clicked.connect(lambda: self._fill(config.DEFAULT_CLUSTER_BUTTONS))
        row.addWidget(reset); row.addStretch()
        v.addLayout(row)
        v.addWidget(_buttons(self))

    def _fill(self, buttons):
        rows = list(buttons) + [{"label": "", "command": ""}] * (12 - len(buttons))
        for r, d in enumerate(rows[:12]):
            self.table.setItem(r, 0, QTableWidgetItem(d.get("label", "")))
            self.table.setItem(r, 1, QTableWidgetItem(d.get("command", "")))

    def buttons(self) -> list[dict]:
        get = lambda r, c: (self.table.item(r, c).text().strip() if self.table.item(r, c) else "")
        return [{"label": get(r, 0) or get(r, 1)[:12], "command": get(r, 1)} for r in range(12)]


class KeyerDialog(QDialog):
    """Config ▸ Voice & CW keyer: audio devices, PTT, CW keying, and recording messages."""

    def __init__(self, cfg: dict, keyer, macros: dict, wav_dir: Path, parent=None):
        from ..core import keyer as K
        from .keyer import audio_inputs, audio_outputs
        super().__init__(parent)
        self.setWindowTitle("Voice & CW keyer")
        self.resize(640, 640)
        self._cfg, self.keyer, self.wav_dir, self.K = dict(cfg), keyer, wav_dir, K
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.allow = QCheckBox("Allow tttlog to transmit (key the radio)")
        self.allow.setChecked(bool(cfg.get("allow_tx")))
        self.mic = QComboBox(); self.mic.addItem("System default", "")
        for d in audio_inputs():
            self.mic.addItem(d, d)
        self.mic.setCurrentIndex(max(0, self.mic.findData(cfg.get("mic", ""))))
        self.out = QComboBox(); self.out.addItem("System default", "")
        for d in audio_outputs():
            self.out.addItem(d, d)
        self.out.setCurrentIndex(max(0, self.out.findData(cfg.get("radio_out", ""))))
        self.ptt = QComboBox()
        for key, label in (("cat", "Radio CAT command"), ("rts", "RTS on the keying port"),
                           ("dtr", "DTR on the keying port"), ("vox", "None (radio uses VOX)")):
            self.ptt.addItem(label, key)
        self.ptt.setCurrentIndex(max(0, self.ptt.findData(cfg.get("ptt", "cat"))))
        self.cw = QComboBox()
        for key, label in (("cat", "Radio sends the text (CAT: Flex, Kenwood, Elecraft)"),
                           ("dtr", "tttlog keys DTR on the keying port"),
                           ("rts", "tttlog keys RTS on the keying port")):
            self.cw.addItem(label, key)
        self.cw.setCurrentIndex(max(0, self.cw.findData(cfg.get("cw", "cat"))))
        self.line = _serial_combo(str(cfg.get("line_port", "")))
        self.wpm = QSpinBox(); self.wpm.setRange(10, 60); self.wpm.setValue(int(cfg.get("wpm", 28)))
        self.wpm.setSuffix(" wpm")
        self.cut = QComboBox()
        for key, label in K.CUT_STYLES.items():
            self.cut.addItem(label, key)
        self.cut.setCurrentIndex(max(0, self.cut.findData(cfg.get("cut", "nt"))))
        self.cut_exch = QCheckBox("Also in the exchange (zone, serial number), not just the RST")
        self.cut_exch.setChecked(bool(cfg.get("cut_exch")))
        self.lead = QSpinBox(); self.lead.setRange(0, 1000); self.lead.setSuffix(" ms")
        self.lead.setValue(int(cfg.get("ptt_lead_ms", 120)))
        self.tail = QSpinBox(); self.tail.setRange(0, 2000); self.tail.setSuffix(" ms")
        self.tail.setValue(int(cfg.get("ptt_tail_ms", 150)))
        f.addRow(self.allow)
        f.addRow("Microphone (recording)", self.mic)
        f.addRow("Audio to the radio", self.out)
        f.addRow("PTT", self.ptt)
        f.addRow("CW", self.cw)
        f.addRow("Keying serial port", self.line)
        f.addRow("CW speed", self.wpm)
        f.addRow("Cut numbers (CW)", self.cut)
        f.addRow("", self.cut_exch)
        f.addRow("PTT before audio", self.lead)
        f.addRow("PTT after audio", self.tail)
        v.addLayout(f)
        note = QLabel(
            "FlexRadio: pick the DAX TX audio device and turn DAX on for the transmit slice.  "
            "Yaesu FTDX10: audio is the radio's USB Audio CODEC (menu SSB MOD SOURCE = REAR); CW needs "
            "DTR keying on the radio's Standard COM port (menu PC KEYING = DTR).\n"
            "Keys: F1–F12 send · Ctrl+Shift+F1–F12 record that key's message · Esc stops · "
            "PgUp / PgDn CW speed.")
        note.setWordWrap(True)
        v.addWidget(note)

        v.addWidget(QLabel("<b>Voice messages</b> (SSB function keys)"))
        self.msgs = QTableWidget(0, 4)
        self.msgs.setHorizontalHeaderLabels(["Message", "File", "Length", ""])
        self.msgs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.msgs.verticalHeader().setVisible(False)
        v.addWidget(self.msgs, 1)
        row = QHBoxLayout()
        self.rec_btn = QPushButton("● Record"); self.rec_btn.clicked.connect(self._record)
        self.play_btn = QPushButton("▶ Play here"); self.play_btn.clicked.connect(self._play)
        self.stop_btn = QPushButton("■ Stop"); self.stop_btn.clicked.connect(self._stop)
        self.status = QLabel()
        for w in (self.rec_btn, self.play_btn, self.stop_btn):
            row.addWidget(w)
        row.addWidget(self.status, 1)
        v.addLayout(row)
        v.addWidget(_buttons(self))
        self._files: list[tuple[str, str]] = []
        seen = set()
        for page in ("RUN", "SP"):
            for m in macros.get("SSB", {}).get(page, []):
                w = m.get("wav", "")
                if w and w not in seen:
                    seen.add(w)
                    self._files.append((f"{page} {m.get('key', '')} {m.get('label', '')}".strip(), w))
        self._fill()
        self.keyer.stateChanged.connect(self._on_state)
        self.keyer.levelChanged.connect(self._on_level)
        self.keyer.recorded.connect(self._on_recorded)
        self.keyer.problem.connect(self._on_problem)

    def _fill(self):
        cur = self.msgs.currentRow()
        self.msgs.setRowCount(len(self._files))
        for r, (label, name) in enumerate(self._files):
            path = self.wav_dir / name
            secs = self.K.wav_seconds(path) if path.exists() else 0
            self.msgs.setItem(r, 0, QTableWidgetItem(label))
            self.msgs.setItem(r, 1, QTableWidgetItem(name))
            self.msgs.setItem(r, 2, QTableWidgetItem(f"{secs:.1f} s" if secs else "—"))
            self.msgs.setItem(r, 3, QTableWidgetItem("" if secs else "not recorded"))
        self.msgs.selectRow(max(0, cur))

    def _selected(self) -> Path | None:
        r = self.msgs.currentRow()
        return self.wav_dir / self._files[r][1] if 0 <= r < len(self._files) else None

    def _record(self):
        p = self._selected()
        if p is None:
            self.status.setText("Pick a message first"); return
        if self.keyer.recorder.active:
            self.keyer.stop_recording(); return
        self.keyer.record(p, mic=self.mic.currentData())

    def _play(self):
        p = self._selected()
        if p is not None and p.exists():
            self.keyer.preview(p)

    def _stop(self):
        if self.keyer.recorder.active:
            self.keyer.stop_recording()
        self.keyer.stop()

    def _on_state(self, s: str):
        self.status.setText(s)
        self.rec_btn.setText("■ Stop recording" if self.keyer.recorder.active else "● Record")

    def _on_recorded(self, _path: str):
        self._fill()

    def _on_problem(self, why: str):
        self.status.setText(why)

    def _on_level(self, lvl: float):
        if self.keyer.recorder.active:
            bars = "█" * int(lvl * 20)
            self.status.setText(f"● Recording {self.keyer.recorder.seconds():.1f} s  {bars}")

    def done(self, r):
        self._stop()
        for sig, slot in ((self.keyer.stateChanged, self._on_state), (self.keyer.levelChanged, self._on_level),
                          (self.keyer.recorded, self._on_recorded), (self.keyer.problem, self._on_problem)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().done(r)

    def values(self) -> dict:
        out = dict(self._cfg)
        out.update(allow_tx=self.allow.isChecked(), mic=self.mic.currentData(),
                   radio_out=self.out.currentData(), ptt=self.ptt.currentData(), cw=self.cw.currentData(),
                   line_port=_serial_value(self.line), wpm=self.wpm.value(),
                   cut=self.cut.currentData(), cut_exch=self.cut_exch.isChecked(),
                   ptt_lead_ms=self.lead.value(), ptt_tail_ms=self.tail.value())
        return out
