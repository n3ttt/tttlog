"""Local network: several tttlog computers in one shack sharing one log.

How stations link up:
  * every few seconds each station broadcasts a small UDP "I'm here" beacon
    (network name, station name, contest, TCP port) on udp_port;
  * a station that hears a beacon from the same network name and contest dials
    it over TCP; stations you add by hand (host or host:port) are dialed too;
  * on a new link both sides say hello with a vector of what they have, then
    send each other what's missing (see core/netsync.py); after that every new
    QSO, edit and delete is sent as it happens, and passed on to the others;
  * stations also send their status (op, band, frequency, mode, run/S&P) and
    short talk messages, which are passed on as well.

Messages are JSON, one per line. Nothing blocks the entry line.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone

import shiboken6
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtNetwork import (QAbstractSocket, QHostAddress, QNetworkInterface, QTcpServer,
                               QTcpSocket, QUdpSocket)
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
                               QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.netsync import LogSync

PROTO = 1
BEACON_MS = 3000
TICK_MS = 2000
STATUS_EVERY_S = 5
PEER_STALE_S = 15          # no word for this long: shown as offline
PEER_FORGET_S = 300
REDIAL_S = 5
MAX_LINE = 1 << 20         # a single message bigger than this is junk


def _host(addr: QHostAddress) -> str:
    s = addr.toString()
    return s[7:] if s.startswith("::ffff:") else s


def parse_peer(text: str, default_port: int) -> tuple[str, int] | None:
    """'192.168.1.20' or 'shack-pc:12071' -> (host, port)."""
    text = text.strip()
    if not text:
        return None
    host, _, port = text.rpartition(":") if text.count(":") == 1 else (text, "", "")
    try:
        return host.strip(), int(port) if port else default_port
    except ValueError:
        return None


class Link(QObject):
    """One TCP connection to another station."""

    messages = Signal(object, list)        # link, [message dicts]
    closed = Signal(object)

    def __init__(self, sock: QTcpSocket, outbound: bool, addr: tuple[str, int], parent=None):
        super().__init__(parent)
        self.sock, self.outbound, self.addr = sock, outbound, addr
        sock.setParent(self)
        self.peer_id = ""
        self.ready = False                 # hello received and accepted
        self.dead = False
        self._graceful = False
        self._buf = b""
        sock.readyRead.connect(self._read)
        sock.disconnected.connect(self.close)
        sock.errorOccurred.connect(lambda _e: self.close())

    def connected(self) -> bool:
        return self.sock.state() == QAbstractSocket.ConnectedState

    def send(self, msg: dict) -> None:
        if self.connected():
            self.sock.write((json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8"))

    def close(self, graceful: bool = False) -> None:
        """Stop using this link. Safe to call from inside the socket's own
        signal handlers: nothing is shut or freed here. The NetNode calls
        finish() a moment later from its own timer. (Aborting a socket inside
        its own readyRead crashed on Windows.)"""
        if self.dead:
            return
        self.dead, self.ready = True, False
        self._graceful = graceful
        self.sock.blockSignals(True)                 # no more readyRead / error re-entry
        self.closed.emit(self)

    def finish(self) -> None:
        """Shut the socket and free the link now. Only called from the node's
        timer or stop(), never from inside this socket's signals. Freed at
        once rather than with deleteLater(): a link still waiting to be freed
        when its node was garbage-collected crashed Python on Linux."""
        if self._graceful and self.connected():
            self.sock.flush()                        # hand the "bye" to the OS first
            self.sock.disconnectFromHost()
        else:
            self.sock.abort()
        if shiboken6.isValid(self):
            shiboken6.delete(self)

    def _read(self) -> None:
        self._buf += bytes(self.sock.readAll())
        *lines, self._buf = self._buf.split(b"\n")
        if len(self._buf) > MAX_LINE:
            self.close()
            return
        out = []
        for raw in lines:
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if isinstance(m, dict):
                out.append(m)
        if out:
            self.messages.emit(self, out)


class NetNode(QObject):
    """This station on the local network."""

    logChanged = Signal()                  # QSOs arrived / changed: rescore and redraw
    peersChanged = Signal()
    talkReceived = Signal(str, str)        # from station, text
    stateChanged = Signal(str)

    def __init__(self, node_id: str, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.cfg: dict = {}
        self.sync: LogSync | None = None
        self.contest = ""
        self.links: list[Link] = []
        self.peers: dict[str, dict] = {}   # node id -> what we know about that station
        self.port = 0
        self.status: dict = {}
        self._status_n = 0
        self._boot = uuid.uuid4().hex[:8]
        self._status_sent = 0.0
        self._last_dial: dict[tuple, float] = {}
        self._known: set[tuple] = set()    # (host, port) we've linked with before: redial if lost
        self._seen = deque(maxlen=2000)    # talk message ids already shown / passed on
        self._seen_set: set[str] = set()
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._accept)
        self.udp: QUdpSocket | None = None
        self._beacon = QTimer(self, interval=BEACON_MS, timeout=self._send_beacon)
        self._tick = QTimer(self, interval=TICK_MS, timeout=self._maintain)
        # Closed links are shut and freed from here, outside their socket's
        # signal handlers. This timer belongs to the node, so it can't fire
        # after the node (and its links) are gone.
        self._dead: list[Link] = []
        self._reaper = QTimer(self, singleShot=True, interval=0, timeout=self._reap)

    # ------------------------------------------------------------ control
    @property
    def running(self) -> bool:
        return self.server.isListening()

    @property
    def name(self) -> str:
        return self.cfg.get("station_name", "") or "STATION"

    def start(self, cfg: dict) -> bool:
        self.stop()
        self.cfg = dict(cfg)
        want = int(cfg.get("tcp_port", 12071))
        if not self.server.listen(QHostAddress.Any, want) and not self.server.listen(QHostAddress.Any, 0):
            self.stateChanged.emit(f"Network off: can't listen ({self.server.errorString()})")
            return False
        self.port = self.server.serverPort()
        self.udp = QUdpSocket(self)
        if cfg.get("udp_port"):
            if not self.udp.bind(QHostAddress.AnyIPv4, int(cfg["udp_port"]),
                                 QUdpSocket.ShareAddress | QUdpSocket.ReuseAddressHint):
                self.stateChanged.emit(f"Can't hear other stations' beacons ({self.udp.errorString()}); "
                                       "add them by address in Config ▸ Local network")
            self.udp.readyRead.connect(self._read_udp)
        self._beacon.start(); self._tick.start()
        self._send_beacon(); self._maintain()
        self.stateChanged.emit(self.summary())
        return True

    def stop(self) -> None:
        self._beacon.stop(); self._tick.stop()
        for l in list(self.links):
            l.close()
        self.links.clear()
        self._reap()
        self.server.close()
        if self.udp:
            self.udp.close()
            if shiboken6.isValid(self.udp):
                shiboken6.delete(self.udp)
            self.udp = None
        self.peers.clear()
        self._known.clear()
        self.port = 0
        self.peersChanged.emit()
        self.stateChanged.emit("Network off")

    def set_log(self, sync: LogSync | None, contest: str) -> None:
        """A log was opened: relink so everyone swaps what's missing for this log."""
        self.sync, self.contest = sync, contest
        for l in list(self.links):
            l.close()
        self._last_dial.clear()
        if self.running:
            self._send_beacon(); self._maintain()

    def linked(self) -> list[dict]:
        return [p for p in self.peers.values() if p.get("direct")]

    def summary(self) -> str:
        if not self.running:
            return "Network off"
        n = len(self.linked())
        return (f"Network {self.cfg.get('net_name', '')} as {self.name} · port {self.port} · "
                f"{n} station{'s' if n != 1 else ''} linked")

    # ------------------------------------------------------------ sending
    def publish(self, ev: dict) -> None:
        """A local QSO / edit / delete: tell every station."""
        self._send_all({"t": "ev", "e": ev})

    def set_status(self, status: dict) -> None:
        changed = status != self.status
        self.status = dict(status)
        if changed and time.monotonic() - self._status_sent > 1:
            self._send_status()

    def talk(self, text: str) -> None:
        mid = uuid.uuid4().hex
        self._remember(mid)
        self._send_all({"t": "talk", "id": mid, "o": self.node_id, "name": self.name, "text": text})

    def _send_all(self, msg: dict, skip: Link | None = None) -> None:
        for l in self.links:
            if l.ready and l is not skip:
                l.send(msg)

    def _status_msg(self) -> dict:
        self._status_n += 1
        return {"t": "st", "o": self.node_id, "b": self._boot, "n": self._status_n, "name": self.name,
                "contest": self.contest, "clock": datetime.now(timezone.utc).isoformat(), **self.status}

    def _send_status(self) -> None:
        self._status_sent = time.monotonic()
        self._send_all(self._status_msg())

    def _hello(self) -> dict:
        return {"t": "hello", "p": PROTO, "node": self.node_id, "name": self.name,
                "net": self.cfg.get("net_name", ""), "contest": self.contest, "port": self.port,
                "vector": self.sync.vector() if self.sync else {}}

    # ------------------------------------------------------------ discovery
    def _broadcast_addrs(self) -> list[QHostAddress]:
        out = {}
        for iface in QNetworkInterface.allInterfaces():
            f = iface.flags()
            if not (f & QNetworkInterface.IsUp) or f & QNetworkInterface.IsLoopBack:
                continue
            for e in iface.addressEntries():
                b = e.broadcast()
                if e.ip().protocol() == QAbstractSocket.IPv4Protocol and not b.isNull():
                    out[b.toString()] = b
        out.setdefault("255.255.255.255", QHostAddress(QHostAddress.Broadcast))
        return list(out.values())

    def _send_beacon(self) -> None:
        if not self.udp or not self.cfg.get("udp_port"):
            return
        data = json.dumps({"app": "tttlog", "p": PROTO, "node": self.node_id, "name": self.name,
                           "net": self.cfg.get("net_name", ""), "contest": self.contest,
                           "port": self.port}).encode()
        for addr in self._broadcast_addrs():
            self.udp.writeDatagram(data, addr, int(self.cfg["udp_port"]))

    def _read_udp(self) -> None:
        while self.udp and self.udp.hasPendingDatagrams():
            dg = self.udp.receiveDatagram()
            try:
                m = json.loads(bytes(dg.data()))
            except ValueError:
                continue
            if (not isinstance(m, dict) or m.get("app") != "tttlog" or m.get("node") == self.node_id
                    or m.get("net") != self.cfg.get("net_name") or not isinstance(m.get("port"), int)):
                continue
            host = _host(dg.senderAddress())
            p = self._peer(m["node"], m.get("name", "?"))
            p.update(contest=m.get("contest", ""), host=host, port=m["port"], heard=time.monotonic())
            if not p.get("direct") and m.get("contest") == self.contest and self.sync:
                self._dial(host, m["port"])
            self.peersChanged.emit()

    # ------------------------------------------------------------ links
    def _dial(self, host: str, port: int) -> None:
        key = (host, int(port))
        now = time.monotonic()
        if now - self._last_dial.get(key, -1e9) < REDIAL_S:
            return
        if any(l.addr == key and not l.dead for l in self.links):
            return
        self._last_dial[key] = now
        sock = QTcpSocket()
        link = self._add_link(sock, True, key)
        sock.connected.connect(lambda: link.send(self._hello()))
        sock.connectToHost(host, int(port))

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            link = self._add_link(sock, False, (_host(sock.peerAddress()), sock.peerPort()))
            link.send(self._hello())

    def _add_link(self, sock, outbound, addr) -> Link:
        link = Link(sock, outbound, addr, self)
        link.messages.connect(self._on_messages)
        link.closed.connect(self._on_closed)
        self.links.append(link)
        return link

    def _on_closed(self, link: Link) -> None:
        if link in self.links:
            self.links.remove(link)
        self._dead.append(link)
        self._reaper.start()
        if link.peer_id and link.peer_id in self.peers:
            if not any(l.ready and l.peer_id == link.peer_id for l in self.links):
                self.peers[link.peer_id]["direct"] = False
            self.peersChanged.emit()
            self.stateChanged.emit(self.summary())

    def _reap(self) -> None:
        dead, self._dead = self._dead, []
        for l in dead:
            l.finish()

    def _maintain(self) -> None:
        now = time.monotonic()
        for pid, p in list(self.peers.items()):
            if now - p.get("heard", 0) > PEER_FORGET_S and not p.get("direct"):
                del self.peers[pid]
        default = int(self.cfg.get("tcp_port", 12071))
        targets = set(self._known)
        for text in self.cfg.get("peers", []):
            hp = parse_peer(text, default)
            if hp:
                targets.add(hp)
        linked_addrs = {(p.get("host"), p.get("port")) for p in self.peers.values() if p.get("direct")}
        if self.sync:
            for host, port in targets:
                if (host, port) not in linked_addrs:
                    self._dial(host, port)
        if self.links and now - self._status_sent >= STATUS_EVERY_S:
            self._send_status()
        self.peersChanged.emit()

    def _peer(self, pid: str, name: str) -> dict:
        p = self.peers.setdefault(pid, {"name": name, "status": {}, "n": 0, "heard": 0.0,
                                        "direct": False, "note": ""})
        p["name"] = name or p["name"]
        return p

    # ------------------------------------------------------------ receiving
    def _on_messages(self, link: Link, msgs: list[dict]) -> None:
        if self.sync and len(msgs) > 1:
            with self.sync.bulk():
                changed = any([self._handle(link, m) for m in msgs])
        else:
            changed = any([self._handle(link, m) for m in msgs])
        if changed:
            self.logChanged.emit()

    def _handle(self, link: Link, m: dict) -> bool:
        """Returns True if the log changed."""
        if link.dead:
            return False
        t = m.get("t")
        if t == "hello":
            self._on_hello(link, m)
            return False
        if not link.ready:
            return False
        if t == "ev" and self.sync and isinstance(m.get("e"), dict):
            new, changed = self.sync.apply(m["e"])
            if new:
                self._send_all(m, skip=link)       # pass it on
            return changed
        if t == "st" and isinstance(m.get("o"), str) and m["o"] != self.node_id:
            p = self._peer(m["o"], str(m.get("name", "?")))
            # (b = that station's run id, so a restarted station's count starting over is accepted)
            if isinstance(m.get("n"), int) and (m.get("b") != p.get("b") or m["n"] > p["n"]):
                p["n"], p["b"] = m["n"], m.get("b")
                p["status"] = {k: m.get(k) for k in ("op", "band", "freq", "mode", "run", "qsos")}
                p["contest"] = m.get("contest", "")
                p["heard"] = time.monotonic()
                if m["o"] == link.peer_id:
                    p["clock_off"] = _clock_offset(m.get("clock"))
                self._send_all(m, skip=link)
                self.peersChanged.emit()
            return False
        if t == "talk" and isinstance(m.get("id"), str) and m["id"] not in self._seen_set:
            self._remember(m["id"])
            self.talkReceived.emit(str(m.get("name", "?"))[:16], str(m.get("text", ""))[:500])
            self._send_all(m, skip=link)
            return False
        if t == "bye":
            if link.peer_id in self.peers:
                self.peers[link.peer_id]["note"] = str(m.get("why", ""))[:80]
            link.close()
        return False

    def _on_hello(self, link: Link, m: dict) -> None:
        pid = m.get("node")
        if not isinstance(pid, str) or pid == self.node_id or m.get("p") != PROTO:
            link.close(); return
        p = self._peer(pid, str(m.get("name", "?"))[:16])
        p.update(contest=m.get("contest", ""), host=link.addr[0], port=m.get("port"), heard=time.monotonic())
        why = ""
        if m.get("net") != self.cfg.get("net_name"):
            why = "different network name"
        elif not self.sync or not m.get("contest"):
            why = "no log open"
        elif m.get("contest") != self.contest:
            why = f"different contest ({m.get('contest')})"
        if why:
            p["note"] = why
            link.send({"t": "bye", "why": why})
            link.close(graceful=True)
            self.peersChanged.emit()
            return
        # Both sides may have dialed: keep the link dialed by the smaller node id.
        for other in [l for l in self.links if l.ready and l.peer_id == pid and l is not link]:
            dial_new = self.node_id if link.outbound else pid
            dial_old = self.node_id if other.outbound else pid
            if dial_old <= dial_new:
                link.close(); return
            other.close()
        link.peer_id, link.ready = pid, True
        p.update(direct=True, note="")
        if isinstance(m.get("port"), int):
            self._known.add((link.addr[0], m["port"]))
        link.send(self._status_msg())
        vec = m.get("vector") if isinstance(m.get("vector"), dict) else {}
        for ev in self.sync.events_after(vec):
            link.send({"t": "ev", "e": ev})
        self.peersChanged.emit()
        self.stateChanged.emit(self.summary())

    def _remember(self, mid: str) -> None:
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(mid)
        self._seen_set.add(mid)


def _clock_offset(text) -> float | None:
    try:
        return (datetime.fromisoformat(text) - datetime.now(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return None


# ====================================================================== pane
class NetworkPane(QWidget):
    """Who's on the network, what they're doing, and talk messages."""

    talkSent = Signal(str)
    COLS = ["Station", "Op", "Band", "kHz", "Mode", "Run", "QSOs", "Link"]

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self.status_lbl = QLabel("Network off — Config ▸ Local network")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self.status_lbl)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setFocusPolicy(Qt.NoFocus)
        v.addWidget(self.table, 2)
        self.console = QPlainTextEdit(readOnly=True)
        self.console.setMaximumBlockCount(300)
        self.console.setPlaceholderText("Talk messages between stations")
        v.addWidget(self.console, 1)
        self.say = QLineEdit(placeholderText="Message to all stations, Enter to send")
        self.say.setStyleSheet("font: 11pt;")
        self.say.returnPressed.connect(self._send)
        v.addWidget(self.say)

    def _send(self):
        text = self.say.text().strip()
        if text:
            self.talkSent.emit(text)
        self.say.clear()

    def add_talk(self, who: str, text: str):
        self.console.appendPlainText(f"{datetime.now(timezone.utc):%H%M}Z {who}: {text}")

    def refresh(self, me: dict, peers: list[dict], state: str):
        """me / peers: {name, status{op, band, freq, mode, run, qsos}, direct, heard, note, clock_off}."""
        self.status_lbl.setText(state)
        rows = [me] + sorted(peers, key=lambda p: p["name"])
        t = self.table
        t.setRowCount(len(rows))
        now = time.monotonic()
        mine = me.get("status", {})
        for r, p in enumerate(rows):
            st = p.get("status") or {}
            online = p is me or now - p.get("heard", 0) < PEER_STALE_S
            if p is me:
                link = "this station"
            elif p.get("note"):
                link = p["note"]
            elif p.get("direct") and online:
                link = "linked"
            elif online:
                link = "seen" if not st else "via others"
            else:
                link = "offline"
            off = p.get("clock_off")
            if off is not None and abs(off) > 60:
                link += f" · clock {off:+.0f}s"
            freq = st.get("freq")
            vals = [p["name"], st.get("op") or "", st.get("band") or "",
                    f"{freq:.1f}" if isinstance(freq, (int, float)) else "", st.get("mode") or "",
                    {True: "RUN", False: "S&P"}.get(st.get("run"), ""),
                    str(st.get("qsos", "")) if st.get("qsos") is not None else "", link]
            same = (p is not me and online and st.get("band") and st.get("band") == mine.get("band")
                    and st.get("mode") == mine.get("mode"))
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if same:
                    it.setBackground(QBrush(QColor("#ffd166")))
                    it.setForeground(QBrush(QColor("black")))
                    it.setToolTip("Same band and mode as you")
                elif not online:
                    it.setForeground(QBrush(QColor("#888888")))
                if p is me:
                    f = it.font(); f.setBold(True); it.setFont(f)
                t.setItem(r, c, it)
