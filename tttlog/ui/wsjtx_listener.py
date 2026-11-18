"""Listens for WSJT-X (JTDX, MSHV, ...) on UDP and reports logged QSOs.

Set WSJT-X's Settings > Reporting > UDP Server to the same address and port
as Config > WSJT-X in tttlog (default 127.0.0.1 : 2237). WSJT-X's
"Accept UDP requests" box doesn't matter: tttlog only listens.

If another program (GridTracker, JTAlert) already listens on that port, use a
multicast address (e.g. 224.0.0.1) in WSJT-X and in every listening program,
so they all get every packet.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QUdpSocket

from ..core import wsjtx

QUIET_SECS = 45          # WSJT-X sends a heartbeat every 15 s


class WsjtxListener(QObject):
    adifLogged = Signal(str, str)        # ADIF record, sending program
    stateChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sock: QUdpSocket | None = None
        self.peer = ""                    # program last heard from
        self.state = "off"
        self._quiet = QTimer(self, singleShot=True, interval=QUIET_SECS * 1000, timeout=self._went_quiet)

    def start(self, cfg: dict) -> bool:
        self.stop()
        if not cfg.get("enabled"):
            return False
        addr = QHostAddress(str(cfg.get("address") or "127.0.0.1"))
        port = int(cfg.get("port") or 2237)
        self.sock = QUdpSocket(self)
        ok = self.sock.bind(QHostAddress(QHostAddress.AnyIPv4), port,
                            QAbstractSocket.ShareAddress | QAbstractSocket.ReuseAddressHint)
        if not ok:
            err = self.sock.errorString()
            self._drop_socket()
            self._set_state(f"can't listen on UDP {port}: {err}")
            return False
        if addr.isMulticast() and not self.sock.joinMulticastGroup(addr):
            self._set_state(f"listening on {port}, but couldn't join {addr.toString()}")
        else:
            self._set_state(f"waiting for WSJT-X on {addr.toString()}:{port}")
        self.sock.readyRead.connect(self._read)
        return True

    def stop(self) -> None:
        self._quiet.stop()
        self._drop_socket()
        self.peer = ""
        self._set_state("off")

    def _drop_socket(self) -> None:
        if self.sock is not None:
            self.sock.blockSignals(True)
            self.sock.close()
            self.sock.deleteLater()
            self.sock = None

    def is_listening(self) -> bool:
        return self.sock is not None

    def _set_state(self, text: str) -> None:
        if text != self.state:
            self.state = text
            self.stateChanged.emit(text)

    def _went_quiet(self) -> None:
        if self.sock is not None:
            self._set_state(f"{self.peer or 'WSJT-X'} not heard for {QUIET_SECS} s")

    def _read(self) -> None:
        sock = self.sock
        while sock is not None and sock.hasPendingDatagrams():
            dg = sock.receiveDatagram()
            self.handle(bytes(dg.data()))

    def handle(self, data: bytes) -> None:
        m = wsjtx.parse(data)
        if m is None:
            return
        self.peer = m.id or "WSJT-X"
        if m.type == wsjtx.CLOSE:
            self._quiet.stop()
            self._set_state(f"{self.peer} closed")
            return
        self._quiet.start()
        if m.type == wsjtx.HEARTBEAT:
            self._set_state(f"connected to {self.peer} {m.text}".rstrip())
        elif m.type == wsjtx.LOGGED_ADIF:
            self._set_state(f"connected to {self.peer}")
            self.adifLogged.emit(m.text, self.peer)
