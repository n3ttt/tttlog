"""Error log: uncaught errors and freezes land in the log file."""
import sys
import time
import zipfile

import pytest

from tttlog import diag


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    monkeypatch.setattr(diag, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(diag, "LOG_FILE", tmp_path / "logs" / "tttlog.log")
    monkeypatch.setattr(diag, "CRASH_FILE", tmp_path / "logs" / "crash.log")
    monkeypatch.setattr(diag, "CONFIG_DIR", tmp_path)
    for h in list(diag.log.handlers):
        diag.log.removeHandler(h)
    old = sys.excepthook
    yield tmp_path
    sys.excepthook = old
    for h in list(diag.log.handlers):
        h.close(); diag.log.removeHandler(h)


def _text():
    for h in diag.log.handlers:
        h.flush()
    return diag.LOG_FILE.read_text()


def test_header_and_uncaught_error(logdir):
    diag.setup()
    seen = []
    diag.on_error(seen.append)
    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    t = _text()
    assert "tttlog" in t and "Python" in t
    assert "ValueError: boom" in t and "Traceback" in t
    assert seen and "boom" in seen[-1]
    diag._error_listeners.clear()


def test_freeze_is_logged_with_the_stuck_line(logdir):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    diag.setup()
    dog = diag.FreezeWatchdog(freeze_secs=0.6, interval_ms=50)
    try:
        app.processEvents()
        time.sleep(1.5)                       # the "window" stops responding here
        app.processEvents(); time.sleep(0.1); app.processEvents()
    finally:
        dog.stop()
    t = _text()
    assert "window not responding" in t
    assert "test_freeze_is_logged_with_the_stuck_line" in t     # the stack points here
    assert "responding again" in t


def test_problem_report_has_logs_not_passwords(logdir):
    diag.setup()
    (logdir / "station.yaml").write_text("call: N3TTT\n")
    from tttlog import config
    config.CALLBOOK_FILE.parent.mkdir(parents=True, exist_ok=True)
    out = diag.problem_report(logdir / "r.zip")
    names = zipfile.ZipFile(out).namelist()
    assert "logs/tttlog.log" in names and "settings/station.yaml" in names
    assert not any("callbook" in n for n in names)
