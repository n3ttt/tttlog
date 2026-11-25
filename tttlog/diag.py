"""Error log and freeze detector.

Everything goes to ~/.tttlog/logs/tttlog.log (rotated, 5 x 1 MB):
- a startup header (version, build, OS, Python, Qt, where the log and settings are)
- uncaught Python errors, from the main thread and from worker threads; the app keeps running
- Qt's own warnings
- freezes: when the window stops responding for FREEZE_SECS, the main thread's stack is
  written down (that is the line of code it is stuck on), and how long it froze when it recovers
Hard crashes (the process dies inside Qt or a driver) land in crash.log via faulthandler.

Help ▸ Open error log folder shows the files; Help ▸ Save a problem report… zips them up.
"""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import platform
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

from .config import CONFIG_DIR

LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "tttlog.log"
CRASH_FILE = LOG_DIR / "crash.log"
FREEZE_SECS = 2.0

log = logging.getLogger("tttlog")
_crash_fh = None
_watchdog: "FreezeWatchdog | None" = None


def setup(debug: bool = False) -> Path:
    """Start logging to LOG_FILE. Safe to call more than once."""
    global _crash_fh
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in log.handlers):
        h = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=4,
                                                 encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s"))
        log.addHandler(h)
        if sys.stderr is not None and debug:
            log.addHandler(logging.StreamHandler(sys.stderr))
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    log.propagate = False
    logging.captureWarnings(True)
    logging.getLogger("py.warnings").handlers = log.handlers

    sys.excepthook = _excepthook
    threading.excepthook = lambda a: _log_exc("error in thread " + (a.thread.name if a.thread else "?"),
                                              a.exc_type, a.exc_value, a.exc_traceback)
    if _crash_fh is None:
        try:
            _crash_fh = open(CRASH_FILE, "a", encoding="utf-8")
            _crash_fh.write(f"\n--- tttlog started {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
            _crash_fh.flush()
            faulthandler.enable(_crash_fh, all_threads=True)
        except OSError:
            pass
    _install_qt_handler()
    _header()
    return LOG_FILE


def _header():
    try:
        from . import __version__
        from .updater import display_version
        ver = display_version()
    except Exception:                                   # noqa: BLE001
        ver = "?"
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        qt = f"PySide6 {PySide6.__version__} / Qt {qVersion()}"
    except Exception:                                   # noqa: BLE001
        qt = "Qt ?"
    log.info("=" * 60)
    log.info("tttlog %s · %s %s (%s) · Python %s · %s · %s", ver, platform.system(), platform.release(),
             platform.machine(), platform.python_version(), qt,
             "packaged app" if getattr(sys, "frozen", False) else "from source")
    log.info("settings %s · log %s", CONFIG_DIR, LOG_FILE)


def _log_exc(what, etype, value, tb):
    log.error("%s: %s", what, "".join(traceback.format_exception(etype, value, tb)).rstrip())


def _excepthook(etype, value, tb):
    if issubclass(etype, KeyboardInterrupt):
        sys.__excepthook__(etype, value, tb)
        return
    _log_exc("uncaught error", etype, value, tb)
    for fn in list(_error_listeners):
        try:
            fn(f"{etype.__name__}: {value}")
        except Exception:                               # noqa: BLE001
            pass


_error_listeners: list = []


def on_error(fn):
    """Call fn(short text) when an uncaught error is logged (the window shows a banner)."""
    _error_listeners.append(fn)


def _install_qt_handler():
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
    qtlog = logging.getLogger("tttlog.qt")

    def handler(kind, ctx, msg):
        qtlog.log(levels.get(kind, logging.WARNING), "%s", msg)
    qInstallMessageHandler(handler)


class FreezeWatchdog:
    """The main thread ticks a heartbeat from a Qt timer; a background thread watches it.
    If the heartbeat stops for FREEZE_SECS, the main thread's stack goes in the log."""

    def __init__(self, freeze_secs: float = FREEZE_SECS, interval_ms: int = 200):
        from PySide6.QtCore import QTimer
        self.freeze_secs = freeze_secs
        self.beat = time.monotonic()
        self.main_id = threading.main_thread().ident
        self.freezes = 0
        self.timer = QTimer()
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._stop = threading.Event()
        self._frozen_since = 0.0
        self.thread = threading.Thread(target=self._watch, name="freeze-watchdog", daemon=True)
        self.thread.start()

    def _tick(self):
        now = time.monotonic()
        if self._frozen_since:
            log.warning("window responding again after %.1f s", now - self._frozen_since)
            self._frozen_since = 0.0
        self.beat = now

    def _watch(self):
        while not self._stop.wait(0.5):
            stalled = time.monotonic() - self.beat
            if stalled >= self.freeze_secs and not self._frozen_since:
                self._frozen_since = self.beat
                self.freezes += 1
                frame = sys._current_frames().get(self.main_id)
                stack = "".join(traceback.format_stack(frame)) if frame else "(no stack)"
                log.warning("window not responding for %.1f s; the main thread is here:\n%s",
                            stalled, stack.rstrip())

    def stop(self):
        self._stop.set()
        self.timer.stop()


def start_watchdog(freeze_secs: float = FREEZE_SECS) -> FreezeWatchdog:
    global _watchdog
    if _watchdog is None:
        _watchdog = FreezeWatchdog(freeze_secs)
    return _watchdog


class timed:
    """with diag.timed("load log"): ...  → logs how long it took if it was slow."""

    def __init__(self, what: str, slow_secs: float = 0.5):
        self.what, self.slow = what, slow_secs

    def __enter__(self):
        self.t = time.monotonic()
        return self

    def __exit__(self, *exc):
        dt = time.monotonic() - self.t
        (log.info if dt >= self.slow else log.debug)("%s took %.2f s", self.what, dt)
        return False


def problem_report(dest: Path) -> Path:
    """Zip the logs and the settings (no callbook password) for a bug report."""
    from .config import CALLBOOK_FILE
    dest = Path(dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(LOG_DIR.glob("*.log*")):
            z.write(p, f"logs/{p.name}")
        for p in sorted(CONFIG_DIR.glob("*.yaml")):
            if p.name != CALLBOOK_FILE.name:
                z.write(p, f"settings/{p.name}")
    return dest
