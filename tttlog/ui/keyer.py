"""Voice and CW keyer: records messages from a microphone, plays them to the
radio's audio input with PTT, and sends CW (radio CAT or a keyed serial line).

Safety: nothing is transmitted unless cfg["allow_tx"] is on; stop() (Esc)
drops PTT at once; every transmission has a hard time limit; PTT is released
when tttlog closes.
"""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Signal

from ..core import keyer as K

RECORD_RATE = 48000
MAX_RECORD_SECS = 30


# ---------------------------------------------------------------- audio devices
def audio_inputs() -> list[str]:
    try:
        from PySide6.QtMultimedia import QMediaDevices
        return [d.description() for d in QMediaDevices.audioInputs()]
    except ImportError:
        return []


def audio_outputs() -> list[str]:
    try:
        from PySide6.QtMultimedia import QMediaDevices
        return [d.description() for d in QMediaDevices.audioOutputs()]
    except ImportError:
        return []


def _device(kind: str, name: str):
    from PySide6.QtMultimedia import QMediaDevices
    devs = QMediaDevices.audioInputs() if kind == "in" else QMediaDevices.audioOutputs()
    for d in devs:
        if d.description() == name:
            return d
    return QMediaDevices.defaultAudioInput() if kind == "in" else QMediaDevices.defaultAudioOutput()


# ---------------------------------------------------------------- playback
class AudioPlayer(QObject):
    """Plays 16-bit PCM to a named output device; emits finished when done."""
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sink = None
        self.buf = None

    def play(self, pcm: bytes, rate: int, ch: int, device_name: str) -> None:
        from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink
        self.stop()
        dev = _device("out", device_name)
        if dev.isNull():
            self.failed.emit("no audio output"); return
        fmt = QAudioFormat()
        fmt.setSampleRate(rate); fmt.setChannelCount(ch); fmt.setSampleFormat(QAudioFormat.Int16)
        if not dev.isFormatSupported(fmt):
            pref = dev.preferredFormat()
            new_rate, new_ch = pref.sampleRate(), max(1, pref.channelCount())
            pcm = K.convert_pcm16(pcm, rate, ch, new_rate, new_ch)
            fmt.setSampleRate(new_rate); fmt.setChannelCount(new_ch)
            if not dev.isFormatSupported(fmt):
                self.failed.emit(f"{dev.description()} can't play 16-bit audio"); return
        self.buf = QBuffer(self)
        self.buf.setData(QByteArray(pcm))
        self.buf.open(QIODevice.ReadOnly)
        self.sink = QAudioSink(dev, fmt, self)
        self.sink.stateChanged.connect(self._state)
        self.sink.start(self.buf)

    def _state(self, st) -> None:
        from PySide6.QtMultimedia import QAudio
        if self.sink is None:
            return
        if st == QAudio.State.IdleState:                    # played everything
            self.stop()
            self.finished.emit()
        elif st == QAudio.State.StoppedState and self.sink.error() != QAudio.Error.NoError:
            err = str(self.sink.error())
            self.stop()
            self.failed.emit(f"audio error: {err}")

    def stop(self) -> None:
        if self.sink is not None:
            self.sink.blockSignals(True)
            self.sink.stop()
            self.sink.deleteLater()
            self.sink = None
        if self.buf is not None:
            self.buf.close()
            self.buf.deleteLater()
            self.buf = None


# ---------------------------------------------------------------- recording
class Recorder(QObject):
    level = Signal(float)                # 0..1, for a meter
    stopped = Signal(str)                # saved path ("" if nothing was saved)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.src = None
        self.io = None
        self.path: Path | None = None
        self.data = bytearray()
        self.float_samples = False
        self.rate, self.ch = RECORD_RATE, 1
        self.started = 0.0
        self._limit = QTimer(self, singleShot=True, interval=MAX_RECORD_SECS * 1000, timeout=self.stop)

    @property
    def active(self) -> bool:
        return self.src is not None

    def seconds(self) -> float:
        return len(self.data) / (2.0 * self.ch * self.rate) if self.rate else 0.0

    def start(self, path: Path, mic: str) -> bool:
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource
        self.cancel()
        dev = _device("in", mic)
        if dev.isNull():
            self.failed.emit("no microphone found"); return False
        fmt = QAudioFormat()
        fmt.setSampleRate(RECORD_RATE); fmt.setChannelCount(1); fmt.setSampleFormat(QAudioFormat.Int16)
        if not dev.isFormatSupported(fmt):
            fmt = dev.preferredFormat()
        if fmt.sampleFormat() not in (QAudioFormat.Int16, QAudioFormat.Float):
            fmt.setSampleFormat(QAudioFormat.Int16)
        self.float_samples = fmt.sampleFormat() == QAudioFormat.Float
        self.rate, self.ch = fmt.sampleRate(), max(1, fmt.channelCount())
        self.path, self.data = path, bytearray()
        self.src = QAudioSource(dev, fmt, self)
        self.io = self.src.start()
        if self.io is None:
            self.src = None
            self.failed.emit(f"can't record from {dev.description()}"); return False
        self.io.readyRead.connect(self._read)
        self.started = time.monotonic()
        self._limit.start()
        return True

    def _read(self) -> None:
        if self.io is None:
            return
        chunk = bytes(self.io.readAll())
        if self.float_samples:
            chunk = K.float_to_pcm16(chunk)
        self.data += chunk
        self.level.emit(K.peak(chunk))

    def stop(self) -> str:
        """Stop and save. Returns the saved path ("" if too short to keep)."""
        if self.src is None:
            return ""
        self._read()
        self._close()
        saved = ""
        pcm = bytes(self.data)
        if self.ch > 1:
            pcm = K.convert_pcm16(pcm, self.rate, self.ch, self.rate, 1)
        if self.path and len(pcm) >= 2 * self.rate // 5:         # at least 0.2 s
            K.write_wav(self.path, pcm, self.rate, 1)
            saved = str(self.path)
        self.stopped.emit(saved)
        return saved

    def cancel(self) -> None:
        if self.src is not None:
            self._close()
            self.stopped.emit("")

    def _close(self) -> None:
        self._limit.stop()
        if self.src is not None:
            self.src.stop()
            self.src.deleteLater()
        self.src = self.io = None


# ---------------------------------------------------------------- serial line keying
class LinePort(QObject):
    """Keys DTR/RTS on a serial port from its own thread (steady CW timing)."""
    done = Signal()
    failed = Signal(str)

    def __init__(self, port: str, cw_line: str, ptt_line: str, parent=None):
        super().__init__(parent)
        self.port, self.cw_line, self.ptt_line = port, cw_line, ptt_line
        self.q: queue.Queue = queue.Queue()
        self._abort = threading.Event()
        self.thread = threading.Thread(target=self._run, name="tttlog-keyline", daemon=True)
        self.thread.start()

    def ptt(self, on: bool) -> None:
        self.q.put(("ptt", on))

    def cw(self, elements) -> None:
        self._abort.clear()
        self.q.put(("cw", elements))

    def abort(self) -> None:
        self._abort.set()
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        self.q.put(("release", None))

    def close(self) -> None:
        self.abort()
        self.q.put(None)
        self.thread.join(timeout=2)

    def _run(self) -> None:
        from PySide6.QtSerialPort import QSerialPort
        sp = QSerialPort()
        sp.setPortName(self.port)
        if not sp.open(QIODevice.ReadWrite):
            self.failed.emit(f"can't open keying port {self.port}: {sp.errorString()}")
            return
        sp.setFlowControl(QSerialPort.NoFlowControl)

        def line(which, on):
            if which == "dtr":
                sp.setDataTerminalReady(on)
            elif which == "rts":
                sp.setRequestToSend(on)

        line("dtr", False); line("rts", False)
        try:
            while True:
                item = self.q.get()
                if item is None:
                    break
                kind, arg = item
                if kind == "ptt":
                    line(self.ptt_line, arg)
                elif kind == "release":
                    line(self.cw_line, False); line(self.ptt_line, False)
                elif kind == "cw":
                    for down, secs in arg:
                        if self._abort.is_set():
                            break
                        line(self.cw_line, down)
                        _sleep(secs)
                    line(self.cw_line, False)
                    self.done.emit()
        finally:
            line("dtr", False); line("rts", False)
            sp.close()


def _sleep(secs: float) -> None:
    end = time.perf_counter() + secs
    if secs > 0.004:
        time.sleep(secs - 0.003)
    while time.perf_counter() < end:
        pass


# ---------------------------------------------------------------- the keyer
class Keyer(QObject):
    stateChanged = Signal(str)           # "" = idle
    levelChanged = Signal(float)
    problem = Signal(str)
    recorded = Signal(str)               # path of a new recording

    def __init__(self, rig, parent=None):
        super().__init__(parent)
        self.rig = rig
        self.cfg: dict = {}
        self.state = ""
        self.keyed = False                # PTT (or CW) is on
        self.player = AudioPlayer(self)
        self.player.finished.connect(self._voice_done)
        self.player.failed.connect(self._voice_failed)
        self.recorder = Recorder(self)
        self.recorder.level.connect(self.levelChanged)
        self.recorder.stopped.connect(self._record_stopped)
        self.recorder.failed.connect(self.problem)
        self.line: LinePort | None = None
        self._line_key = None
        self._pending = QTimer(self, singleShot=True, timeout=self._begin_audio)   # PTT lead
        self._audio: tuple | None = None
        self._tail = QTimer(self, singleShot=True, timeout=self._unkey)
        self._limit = QTimer(self, singleShot=True, timeout=self._timed_out)
        self._cw_done = QTimer(self, singleShot=True, timeout=self._cw_finished)
        self._previewing = False

    # -- settings ----------------------------------------------------------
    def configure(self, cfg: dict) -> None:
        self.stop()
        self.cfg = dict(cfg)
        want_line = (self.cfg.get("cw") in ("dtr", "rts") or self.cfg.get("ptt") in ("dtr", "rts")) \
            and self.cfg.get("line_port")
        key = (self.cfg.get("line_port"), self.cfg.get("cw"), self.cfg.get("ptt")) if want_line else None
        if key != self._line_key:
            if self.line is not None:
                self.line.close(); self.line.deleteLater(); self.line = None
            if key:
                cw_line = self.cfg["cw"] if self.cfg["cw"] in ("dtr", "rts") else ""
                ptt_line = self.cfg["ptt"] if self.cfg["ptt"] in ("dtr", "rts") else ""
                self.line = LinePort(self.cfg["line_port"], cw_line, ptt_line, self)
                self.line.failed.connect(self.problem)
                self.line.done.connect(self._cw_finished)
            self._line_key = key

    @property
    def wpm(self) -> int:
        return int(self.cfg.get("wpm", 28))

    def set_wpm(self, wpm: int) -> int:
        wpm = max(10, min(60, int(wpm)))
        self.cfg["wpm"] = wpm
        if self.cfg.get("cw", "cat") == "cat" and self.cfg.get("allow_tx"):
            self.rig.send_raw(self.rig.cw_speed_command(wpm))
        return wpm

    @property
    def busy(self) -> bool:
        return self.keyed or self._pending.isActive() or self._tail.isActive()

    def _set_state(self, s: str) -> None:
        if s != self.state:
            self.state = s
            self.stateChanged.emit(s)

    def why_not(self, cw: bool) -> str:
        """'' if we can transmit, else what's missing."""
        if not self.cfg.get("allow_tx"):
            return "Transmitting is off: Config ▸ Voice & CW keyer ▸ Allow tttlog to transmit"
        uses_cat = (self.cfg.get("cw", "cat") == "cat") if cw else (self.cfg.get("ptt", "cat") == "cat")
        if uses_cat and not self.rig.is_connected():
            return "The radio isn't connected (Config ▸ Radio)"
        if cw and self.cfg.get("cw", "cat") == "cat" and not self.rig.can_send_cw:
            return ("This radio can't send CW text over CAT: in Config ▸ Voice & CW keyer pick DTR or RTS "
                    "keying on its second serial port")
        if not uses_cat and ((cw and self.cfg.get("cw") in ("dtr", "rts")) or
                             (not cw and self.cfg.get("ptt") in ("dtr", "rts"))) and self.line is None:
            return "No keying serial port chosen (Config ▸ Voice & CW keyer)"
        return ""

    # -- PTT -----------------------------------------------------------------
    def _ptt(self, on: bool) -> None:
        how = self.cfg.get("ptt", "cat")
        if how == "cat":
            self.rig.send_raw(self.rig.ptt_command(on))
        elif how in ("dtr", "rts") and self.line is not None:
            self.line.ptt(on)

    # -- voice -------------------------------------------------------------
    def send_voice(self, path: Path) -> bool:
        why = self.why_not(cw=False)
        if why:
            self.problem.emit(why); return False
        try:
            pcm, rate, ch = K.read_wav(Path(path))
        except (OSError, EOFError, ValueError) as e:
            self.problem.emit(f"Can't read {Path(path).name}: {e}"); return False
        self.stop()
        secs = len(pcm) / (2.0 * ch * rate)
        self.keyed = True
        self._ptt(True)
        self._set_state(f"TX voice: {Path(path).stem}")
        self._limit.start(int(min(float(self.cfg.get("max_tx_secs", 90)), secs + 3) * 1000))
        lead = int(self.cfg.get("ptt_lead_ms", 120)) if self.cfg.get("ptt", "cat") != "vox" else 0
        self._previewing = False
        self._audio = (pcm, rate, ch)
        self._pending.start(max(0, lead))
        return True

    def _begin_audio(self) -> None:
        if self._audio and self.keyed:
            pcm, rate, ch = self._audio
            self.player.play(pcm, rate, ch, self.cfg.get("radio_out", ""))

    def preview(self, path: Path) -> bool:
        """Play a recording on this computer's speakers (no PTT)."""
        try:
            pcm, rate, ch = K.read_wav(Path(path))
        except (OSError, EOFError, ValueError) as e:
            self.problem.emit(f"Can't read {Path(path).name}: {e}"); return False
        self.stop()
        self._previewing = True
        self._set_state(f"Playing {Path(path).stem} (not transmitting)")
        self.player.play(pcm, rate, ch, "")
        return True

    def _voice_done(self) -> None:
        if self._previewing:
            self._previewing = False
            self._set_state(""); return
        self._tail.start(int(self.cfg.get("ptt_tail_ms", 150)))

    def _voice_failed(self, why: str) -> None:
        self.problem.emit(why)
        self.stop()

    # -- CW ----------------------------------------------------------------
    def send_cw(self, text: str) -> bool:
        txt = K.cw_text(text)
        if not txt:
            return False
        why = self.why_not(cw=True)
        if why:
            self.problem.emit(why); return False
        self.stop()
        secs = K.cw_seconds(txt, self.wpm)
        self.keyed = True
        self._set_state(f"TX CW {self.wpm} wpm: {txt}")
        self._limit.start(int(min(float(self.cfg.get("max_tx_secs", 90)), secs + 5) * 1000))
        if self.cfg.get("cw", "cat") == "cat":
            self.rig.send_raw(self.rig.cw_speed_command(self.wpm))
            for cmd in self.rig.cw_commands(txt):
                self.rig.send_raw(cmd)
            self._cw_done.start(int(secs * 1000) + 300)     # the radio doesn't say when it's done
        else:
            if self.cfg.get("ptt") in ("dtr", "rts") and self.cfg.get("ptt") != self.cfg.get("cw"):
                self._ptt(True)
            self.line.cw(K.morse_elements(txt, self.wpm))
        return True

    def _cw_finished(self) -> None:
        if self.keyed:
            if self.cfg.get("cw") in ("dtr", "rts") and self.cfg.get("ptt") in ("dtr", "rts"):
                self._ptt(False)
            self.keyed = False
            self._limit.stop()
            self._set_state("")

    # -- stopping ------------------------------------------------------------
    def _unkey(self) -> None:
        if self.keyed:
            self._ptt(False)
        self.keyed = False
        self._limit.stop()
        self._set_state("")

    def _timed_out(self) -> None:
        self.problem.emit("Transmit time limit reached: stopped sending")
        self.stop()

    def stop(self) -> bool:
        """Stop anything being sent or played, release PTT. True if something was stopped."""
        was = self.busy or self._previewing or bool(self.state and not self.recorder.active)
        self._pending.stop(); self._tail.stop(); self._limit.stop(); self._cw_done.stop()
        self.player.stop()
        self._previewing = False
        if self.keyed:
            if self.cfg.get("cw", "cat") == "cat" and self.state.startswith("TX CW"):
                for cmd in self.rig.cw_abort_commands():
                    self.rig.send_raw(cmd)
            if self.line is not None:
                self.line.abort()
            self._ptt(False)
        self.keyed = False
        if not self.recorder.active:
            self._set_state("")
        return was

    def shutdown(self) -> None:
        self.stop()
        self.recorder.cancel()
        if self.line is not None:
            self.line.close()
            self.line = None
            self._line_key = None

    # -- recording -----------------------------------------------------------
    def record(self, path: Path, mic: str | None = None) -> bool:
        self.stop()
        if self.recorder.start(Path(path), self.cfg.get("mic", "") if mic is None else mic):
            self._set_state(f"● Recording {Path(path).stem}… (Esc or the same key to stop)")
            return True
        return False

    def stop_recording(self) -> str:
        return self.recorder.stop()

    def _record_stopped(self, saved: str) -> None:
        self._set_state("")
        if saved:
            self.recorded.emit(saved)
