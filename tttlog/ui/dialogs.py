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
        for lbl, w in [("Call", self.call), ("Operator", self.op), ("State/Prov", self.state),
                       ("CQ zone", self.zone), ("ITU zone", self.itu), ("Grid", self.grid),
                       ("Name", self.name), ("Address (use | between lines)", self.addr),
                       ("Club", self.club), ("Email", self.email)]:
            f.addRow(lbl, w)
        f.addRow(_buttons(self))

    def station(self) -> Station:
        return Station(call=self.call.text().upper().strip(), operator=self.op.text().upper().strip(),
                       state=self.state.text().upper().strip(), cq_zone=self.zone.value(),
                       itu_zone=self.itu.value(), grid=self.grid.text().upper().strip(),
                       name=self.name.text().strip(),
                       address=[a.strip() for a in self.addr.text().split("|") if a.strip()],
                       club=self.club.text().strip(), email=self.email.text().strip())


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
