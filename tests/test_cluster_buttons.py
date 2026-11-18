"""Cluster window command buttons (N1MM style) and command-line history."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from tttlog import config
from test_rig import app, win  # noqa: F401  (fixtures)


def test_defaults_and_tokens():
    b = config.cluster_buttons({})
    assert len(b) == 12 and b[0] == {"label": "SH/DX", "command": "SH/DX 30"}
    assert config.cluster_buttons({"buttons": [{"label": "X", "command": "Y"}]})[1] == {"label": "", "command": ""}
    assert config.expand_cluster_command("SH/DX {CALL} | SH/WWV", "N3TTT", "DL1ABC", 14025.5) == \
        ["SH/DX DL1ABC", "SH/WWV"]
    assert config.expand_cluster_command("DX {FREQ} {CALL} by {MYCALL}", "N3TTT", "JA1AA", 7025) == \
        ["DX 7025.0 JA1AA by N3TTT"]


def _capture(win, monkeypatch):
    sent = []
    monkeypatch.setattr(win, "_cluster_command", lambda c: sent.append(c) or True)
    return sent


def test_buttons_send_commands(app, win, monkeypatch):
    sent = _capture(win, monkeypatch)
    tp = win.telnet_pane
    assert [b.text() for b in tp.cmd_buttons[:3]] == ["SH/DX", "DX of call", "WWV"]
    tp.cmd_buttons[0].click()
    assert sent == ["SH/DX 30"]
    tp.cmd_buttons[1].click()                                   # {CALL} with no call anywhere
    assert sent == ["SH/DX 30"] and "Type a call first" in win.banner_lbl.text()
    win.call.setText("dl1abc")
    tp.cmd_buttons[1].click()
    assert sent[-1] == "SH/DX DL1ABC"


def test_reconnect_button(app, win, monkeypatch):
    calls = []
    monkeypatch.setattr(win, "cluster_connect", lambda on: calls.append(on))
    _capture(win, monkeypatch)
    win.cluster_button("{CONN}")
    assert calls == [False, True]


def test_edited_buttons_are_saved(app, win, monkeypatch):
    sent = _capture(win, monkeypatch)
    from tttlog.ui.dialogs import ClusterButtonsDialog
    dlg = ClusterButtonsDialog(config.cluster_buttons(win.cluster_cfg), win)
    dlg.table.item(11, 0).setText("Two")
    dlg.table.item(11, 1).setText("SH/DX 10 | SH/WWV 1")
    dlg.table.item(10, 0).setText("")
    dlg.table.item(10, 1).setText("")
    win.cluster_cfg["buttons"] = dlg.buttons()
    dlg.deleteLater()
    config.save_cluster(win.cluster_cfg)
    win.telnet_pane.set_buttons(config.cluster_buttons(win.cluster_cfg))
    assert not win.telnet_pane.cmd_buttons[10].isEnabled()
    win.telnet_pane.cmd_buttons[11].click()
    assert sent == ["SH/DX 10", "SH/WWV 1"]
    assert config.load_cluster()["buttons"][11]["command"] == "SH/DX 10 | SH/WWV 1"
    win._show_cluster_buttons(False)
    assert win.telnet_pane.button_box.isHidden() and config.load_cluster()["show_buttons"] is False


def test_command_history(app, win, monkeypatch):
    sent = _capture(win, monkeypatch)
    tp = win.telnet_pane
    for c in ("sh/dx 30", "sh/wwv"):
        tp.cmd.setText(c); win._cluster_cmd()
    assert sent == ["sh/dx 30", "sh/wwv"] and tp.cmd.text() == ""

    def key(k):
        app.sendEvent(tp.cmd, QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
    key(Qt.Key_Up); assert tp.cmd.text() == "sh/wwv"
    key(Qt.Key_Up); assert tp.cmd.text() == "sh/dx 30"
    key(Qt.Key_Down); key(Qt.Key_Down); assert tp.cmd.text() == ""


# ---------------------------------------------------------------- F-keys: right-click to edit
def test_edit_one_fkey(app, win, monkeypatch):
    from tttlog.ui import main_window as mw
    from tttlog.ui.dialogs import FKeyDialog

    def fake_exec(self):
        self.label.setText("CQ fast"); self.text.setText("CQ {MYCALL}"); self.wav.setText("cq fast.wav")
        return FKeyDialog.RECORD
    monkeypatch.setattr(FKeyDialog, "exec", fake_exec)
    recorded = []
    monkeypatch.setattr(win, "record_fkey", lambda n: recorded.append(n))
    win.set_mode("SSB"); win.run_mode = True
    win.edit_fkey(0)
    m = config.load_macros()["SSB"]["RUN"][0]
    assert m == {**m, "label": "CQ fast", "text": "CQ {MYCALL}", "wav": "cq_fast.wav"}
    assert win.fbuttons[0].text() == "F1 CQ fast" and recorded == [0]
    assert "Right-click to edit" in win.fbuttons[0].toolTip()

    monkeypatch.setattr(FKeyDialog, "exec", lambda self: (self.text.setText("TU {MYCALL} TEST"), 1)[1])
    win.mode = "CW"; win._refresh_radio()
    win.edit_fkey(2)                                            # CW page: no voice file
    assert config.load_macros()["CW"]["RUN"][2]["text"] == "TU {MYCALL} TEST" and recorded == [0]


def test_mode_dropdown(app, win):
    """General log: a mode dropdown in the main window (not just the menu)."""
    box = win.mode_box
    assert not box.isHidden()
    modes = [box.itemText(i) for i in range(box.count())]
    assert {"SSB", "CW", "FT8"} <= set(modes)
    box.textActivated.emit("CW")                      # what picking it in the dropdown does
    assert win.mode == "CW" and win.rst.text() == "599"
    win.set_mode("FT8")                               # menu / typed / radio changes show in it
    assert box.currentText() == "FT8"
