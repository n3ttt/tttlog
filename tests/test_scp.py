"""Super Check Partial: checking a download, updating it from the menu, and the hint
when there's no file."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import io

import pytest

from tttlog.core import cty
from test_rig import app, win  # noqa: F401  (fixtures)

GOOD = ("# Super Check Partial\n" + "\n".join(f"K{i}ABC" for i in range(1500)) + "\nJA1AA\nDL1ABC\n").encode()


def test_check_scp():
    assert cty.check_scp(GOOD) == 1502
    with pytest.raises(ValueError):
        cty.check_scp(b"<!DOCTYPE html><html><body>Just a moment...</body></html>")
    with pytest.raises(ValueError):
        cty.check_scp(b"K1ABC\nW1AW\n")


def test_update_from_the_menu_and_hint(app, win, tmp_path, monkeypatch):
    monkeypatch.setattr(cty, "USER_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(cty, "DATA_DIR", tmp_path / "shipped")          # no file shipped either
    win.scp = win._load_scp()
    assert win.scp == []
    win._update_partials("")
    assert "File ▸ Update Super Check Partial" in win.partials.item(0).text()

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: Resp(GOOD))
    win.update_scp()
    assert (tmp_path / "data" / "MASTER.SCP").exists() and len(win.scp) == 1502
    assert "1,502 calls" in win.banner_lbl.text()
    win.call.setText("JA1"); win._on_call_edited("JA1")
    assert [win.partials.item(i).text() for i in range(win.partials.count())] == ["JA1AA"]

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: Resp(b"<html>blocked</html>"))
    win.update_scp()                                                  # a web page: the good file stays
    assert "Couldn't update" in win.banner_lbl.text() and len(win._load_scp()) == 1502
