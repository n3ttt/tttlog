"""Sends N1MM-compatible UDP packets (see core/n1mm.py): RadioInfo every 10 s and on
every change, and rotor turn / stop commands."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QHostAddress, QHostInfo, QUdpSocket

from ..core import n1mm

RADIO_EVERY_MS = 10_000


class Broadcaster(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: dict = {}
        self.sock = QUdpSocket(self)
        self._radio: list[tuple[QHostAddress, int]] = []
        self._rotor: list[tuple[QHostAddress, int]] = []
        self._last = b""
        self._info = None                     # callable -> kwargs for n1mm.radio_info
        self._timer = QTimer(self, interval=RADIO_EVERY_MS, timeout=lambda: self.send_radio(force=True))
        self.sent: list[tuple[str, int, bytes]] = []    # last few packets (shown in tests / for checking)

    def configure(self, cfg: dict, info) -> None:
        self.cfg, self._info = dict(cfg), info
        self._radio = self._resolve(cfg.get("radio_targets", ""), n1mm.RADIO_PORT) if cfg.get("radio") else []
        self._rotor = self._resolve(cfg.get("rotor_targets", ""), n1mm.ROTOR_PORT) if cfg.get("rotor") else []
        self._last = b""
        if self._radio:
            self._timer.start()
            self.send_radio(force=True)
        else:
            self._timer.stop()

    @staticmethod
    def _resolve(text: str, port: int) -> list[tuple[QHostAddress, int]]:
        out = []
        for host, p in n1mm.parse_targets(text, port):
            addr = QHostAddress(host)
            if addr.isNull():                          # a name, e.g. shack-pc or a Tailscale name
                info = QHostInfo.fromName(host)
                v4 = [a for a in info.addresses() if a.protocol() == QHostAddress.IPv4Protocol]
                if not (v4 or info.addresses()):
                    continue
                addr = (v4 or info.addresses())[0]
            out.append((addr, p))
        return out

    def _send(self, data: bytes, targets) -> None:
        for addr, port in targets:
            self.sock.writeDatagram(data, addr, port)
            self.sent.append((addr.toString(), port, data))
        del self.sent[:-20]

    def send_radio(self, force: bool = False) -> None:
        if not self._radio or self._info is None:
            return
        data = n1mm.radio_info(**self._info())
        if force or data != self._last:
            self._last = data
            self._send(data, self._radio)

    @property
    def rotor_on(self) -> bool:
        return bool(self._rotor)

    def turn(self, azimuth: float, khz: float) -> bool:
        if not self._rotor:
            return False
        self._send(n1mm.rotor_turn(self.cfg.get("rotor_name", ""), azimuth, khz,
                                   bidirectional=bool(self.cfg.get("bidirectional"))), self._rotor)
        return True

    def stop(self, khz: float) -> bool:
        if not self._rotor:
            return False
        self._send(n1mm.rotor_stop(self.cfg.get("rotor_name", ""), khz), self._rotor)
        return True
