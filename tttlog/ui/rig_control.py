"""Talks to the radio over TCP (SmartSDR CAT, a network CAT port) or a serial
port (USB CAT), polling frequency and mode.

Follow-only unless cfg["control"] is on: then set_freq / set_mode send the
radio commands. With control off nothing but read queries is ever sent.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket

from ..core import keyer as K
from ..core.rig import Dialect, make_dialect, split_replies

RETRY_MS = 3000
SILENT_SECS = 3.0          # no answer this long -> say so
HOLD_SECS = 0.8            # after tuning, ignore the radio's stale reports this long


class RigControl(QObject):
    freqChanged = Signal(float)          # kHz, from the radio
    modeChanged = Signal(str)            # radio mode name (USB, CWU, DIGU...)
    stateChanged = Signal(str)
    refused = Signal(str)                # the radio said NG to something (e.g. "cw")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: dict = {}
        self.dialect = Dialect("flex")
        self.dev = None                  # QTcpSocket or QSerialPort, reused across reconnects
        self.state = "off"
        self.freq_khz: float | None = None
        self.radio_mode: str | None = None
        self._buf = b""
        self._last_heard = 0.0
        self._hold_freq = self._hold_mode = 0.0
        self._poll = QTimer(self, interval=400, timeout=self._send_poll)
        self._retry = QTimer(self, singleShot=True, interval=RETRY_MS, timeout=self._open)

    # -- lifecycle ---------------------------------------------------------
    def start(self, cfg: dict) -> None:
        self.stop()
        self.cfg = dict(cfg)
        if not cfg.get("enabled"):
            return
        self.dialect = make_dialect(cfg)
        self._poll.setInterval(max(150, int(cfg.get("poll_ms", 400))))
        self._open()

    def stop(self) -> None:
        self._poll.stop()
        self._retry.stop()
        if self.dev is not None:
            self.dev.blockSignals(True)
            if isinstance(self.dev, QTcpSocket):
                self.dev.abort()
            else:
                self.dev.close()
            self.dev.deleteLater()
            self.dev = None
        self.freq_khz = self.radio_mode = None
        self._buf = b""
        self._set_state("off")

    @property
    def control(self) -> bool:
        return bool(self.cfg.get("control"))

    def is_connected(self) -> bool:
        return self.state.startswith("connected")

    def _open(self) -> None:
        if not self.cfg.get("enabled"):
            return
        if self.cfg.get("connection") == "serial":
            self._open_serial()
        else:
            self._open_tcp()

    def _open_tcp(self) -> None:
        if self.dev is None:
            self.dev = QTcpSocket(self)
            self.dev.connected.connect(self._on_open)
            self.dev.readyRead.connect(self._read)
            self.dev.disconnected.connect(lambda: self._lost("radio connection closed"))
            self.dev.errorOccurred.connect(lambda _e: self._lost(self.dev.errorString() if self.dev else ""))
        host, port = self.cfg.get("host", "127.0.0.1"), int(self.cfg.get("port", 5002))
        self._set_state(f"connecting to {host}:{port}")
        self.dev.blockSignals(True)                 # aborting an old link isn't a new failure
        self.dev.abort()
        self.dev.blockSignals(False)
        self.dev.connectToHost(host, port)

    def _open_serial(self) -> None:
        from PySide6.QtSerialPort import QSerialPort
        name = self.cfg.get("serial_port", "")
        if not name:
            self._set_state("no serial port chosen (Config ▸ Radio)")
            return
        if self.dev is None:
            self.dev = QSerialPort(self)
            self.dev.readyRead.connect(self._read)
            self.dev.errorOccurred.connect(self._serial_error)
        self.dev.close()
        self.dev.setPortName(name)
        self.dev.setBaudRate(int(self.cfg.get("baud", 38400)))
        if self.dev.open(QSerialPort.ReadWrite):
            self._on_open()
        else:
            self._lost(f"can't open {name}: {self.dev.errorString()}")

    def _serial_error(self, err) -> None:
        from PySide6.QtSerialPort import QSerialPort
        if err not in (QSerialPort.NoError,) and self.dev is not None and self.dev.isOpen():
            if err == QSerialPort.ResourceError:            # unplugged
                self.dev.close()
                self._lost("radio unplugged")

    def _on_open(self) -> None:
        self._buf = b""
        self._last_heard = time.monotonic()
        self._set_state("connected, waiting for the radio")
        self._send_poll()
        self._poll.start()

    def _lost(self, why: str) -> None:
        self._poll.stop()
        if self.cfg.get("enabled") and not self._retry.isActive():
            self._set_state(f"{why or 'no radio'} — retrying")
            self._retry.start()

    def _set_state(self, text: str) -> None:
        if text != self.state:
            self.state = text
            self.stateChanged.emit(text)

    # -- reading -----------------------------------------------------------
    def _send_poll(self) -> None:
        if self.dev is None or not self.dev.isOpen():
            return
        if self._last_heard and time.monotonic() - self._last_heard > SILENT_SECS:
            self._set_state("connected, but the radio isn't answering")
        for q in self.dialect.poll():
            self.dev.write(q)

    def _read(self) -> None:
        if self.dev is None:
            return
        split = getattr(self.dialect, "split", split_replies)    # CI-V frames or ";" replies
        replies, self._buf = split(self._buf + bytes(self.dev.readAll()))
        self._buf = self._buf[-256:]
        for r in replies:
            self.feed(r)

    def feed(self, reply) -> None:
        got = self.dialect.parse(reply)
        for item in (got if isinstance(got, list) else [got] if got else []):
            self._take(*item)

    def _take(self, kind: str, val) -> None:
        if val is None:
            return
        if kind == "refused":
            self.refused.emit(str(val))
            return
        if kind == "bkin":
            return                                   # kept on the dialect (dialect.bkin)
        self._last_heard = time.monotonic()
        name = self.cfg.get("dialect", "flex")
        if name == "icom":
            from ..core.civ import MODELS
            name = f"{MODELS.get(self.dialect.model, MODELS['other'])[0]}, CI-V {self.dialect.addr:02X}h"
        if not self.state.startswith("connected to"):
            self._set_state(f"connected to the radio ({name})")
        now = time.monotonic()
        if kind == "freq" and now >= self._hold_freq:
            if self.freq_khz is None or abs(val - self.freq_khz) >= 0.001:
                self.freq_khz = val
                self.freqChanged.emit(val)
        elif kind == "mode" and now >= self._hold_mode:
            if val != self.radio_mode:
                self.radio_mode = val
                self.modeChanged.emit(val)

    # -- keying (the keyer decides whether transmitting is allowed) ----------
    @property
    def dialect_name(self) -> str:
        return self.cfg.get("dialect", "flex")

    # The radio's own commands for PTT and CW (ASCII CAT radios or Icom CI-V).
    @property
    def can_send_cw(self) -> bool:
        d = self.dialect
        return d.can_cw if hasattr(d, "can_cw") else self.dialect_name in K.CAT_CW

    def ptt_command(self, on: bool) -> bytes:
        d = self.dialect
        if hasattr(d, "ptt"):
            return d.ptt(on)
        return (K.PTT_ON if on else K.PTT_OFF)[self.dialect_name]

    def cw_speed_command(self, wpm: int) -> bytes:
        d = self.dialect
        return d.cw_speed(wpm) if hasattr(d, "cw_speed") else K.cw_set_speed(wpm)

    def cw_commands(self, text: str) -> list[bytes]:
        d = self.dialect
        return d.cw(K.cw_text(text)) if hasattr(d, "cw") else K.cw_commands(self.dialect_name, text)

    def cw_setup_commands(self) -> tuple[list[bytes], str]:
        """Anything the radio needs before CAT CW goes on the air, and a note saying
        what was changed. Icom: CW text only transmits with break-in on, so turn
        on semi break-in if it's off (or not known yet)."""
        d = self.dialect
        if hasattr(d, "set_bkin") and d.bkin not in (1, 2):
            return [d.set_bkin(1)], "Turned on semi break-in (BK-IN): Icom radios only send CI-V CW with break-in on"
        return [], ""

    def cw_abort_commands(self) -> list[bytes]:
        d = self.dialect
        return d.cw_abort() if hasattr(d, "cw_abort") else K.cw_abort(self.dialect_name)

    def send_raw(self, cmd: bytes) -> bool:
        """Send a command (PTT, CW text) to a connected radio."""
        if self.dev is None or not self.dev.isOpen() or not self.is_connected():
            return False
        self.dev.write(cmd)
        if hasattr(self.dev, "flush"):
            self.dev.flush()
        return True

    # -- writing (only with control on) ------------------------------------
    def set_freq(self, khz: float) -> bool:
        if not (self.control and self.dev is not None and self.dev.isOpen()):
            return False
        self.dev.write(self.dialect.set_freq(khz))
        self.freq_khz = khz
        self._hold_freq = time.monotonic() + HOLD_SECS
        return True

    def set_mode(self, radio_mode: str) -> bool:
        if not (self.control and self.dev is not None and self.dev.isOpen()):
            return False
        cmd = self.dialect.set_mode(radio_mode)
        if cmd is None:
            return False
        for c in (cmd if isinstance(cmd, list) else [cmd]):
            self.dev.write(c)
        self.radio_mode = radio_mode
        self._hold_mode = time.monotonic() + HOLD_SECS
        return True
