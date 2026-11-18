"""Run / S&P: the toggle button, remembering the run frequency when jumping to a spot,
swapping back, needed-mult messages under the Log, and editable keys."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

from PySide6.QtGui import QKeySequence

from test_rig import app, win  # noqa: F401  (fixtures)


def _spot_line(call, khz, hhmm=None):
    hhmm = hhmm or datetime.now(timezone.utc).strftime("%H%M")
    return f"DX de W3LPL:    {khz:.1f}  {call:<12} CQ                     {hhmm}Z"


def test_run_button(app, win):
    win.run_mode = True; win._refresh_radio()
    assert win.run_btn.isChecked() and win.run_btn.text() == "RUN"
    win.run_btn.click()
    assert not win.run_mode and win.run_btn.text().replace("&&", "&") == "S&P"
    win.run_btn.click()
    assert win.run_mode


def test_jump_remembers_run_frequency_and_swaps_back(app, win):
    from tttlog.core.cluster import Spot
    win.set_mode("SSB"); win.set_freq(14250); win.run_mode = True; win._refresh_radio()
    win.go_to_spot(Spot(call="JA1AA", freq_khz=7150.0, spotter="W3LPL", mode="SSB"))
    assert win.freq_khz == 7150.0 and not win.run_mode and win.call.text() == "JA1AA"
    win.swap_run()                                          # back to running
    assert win.freq_khz == 14250 and win.run_mode and win.call.text() == ""
    assert "Back on your run frequency" in win.banner_lbl.text()
    win.swap_run()                                          # and back to the spot
    assert win.freq_khz == 7150.0 and not win.run_mode and win.call.text() == "JA1AA"


def test_swap_with_nothing_remembered(app, win):
    win.run_memory = None
    win.run_mode = False
    win.swap_run()
    assert "No run frequency remembered" in win.banner_lbl.text()


def test_needed_mult_messages(app, win):
    win._take_cluster_text(_spot_line("JA1AA", 14025.0))
    assert win.alerts.count() == 1
    assert "JA1AA" in win.alerts.item(0).text() and "14025.0" in win.alerts.item(0).text()
    win._take_cluster_text(_spot_line("JA1AA", 14025.2))    # spotted again: not repeated
    win._take_cluster_text(_spot_line("DL1ABC", 14030.0))
    assert win.alerts.count() == 2 and "DL1ABC" in win.alerts.item(0).text()   # newest first
    win.set_freq(7200); win.run_mode = True
    win._on_alert_clicked(win.alerts.item(1))               # click: go to JA1AA, run remembered
    assert win.freq_khz == 14025.0 and win.call.text() == "JA1AA" and win.run_memory["freq"] == 7200
    assert "(2)" in win.alerts_lbl.text()


def test_needed_mult_not_announced_when_worked(app, win):
    win.call.setText("JA1AA"); win.set_freq(14025.0); win.on_enter()   # work Japan first
    win._take_cluster_text(_spot_line("JA2BB", 14026.0))
    assert win.alerts.count() == 0


def test_editable_shortcuts(app, win):
    assert win.shortcut_actions["go_needed"].shortcut() == QKeySequence("Ctrl+G")
    win.set_shortcut("go_needed", "Ctrl+Shift+G")
    assert win.shortcut_actions["go_needed"].shortcut() == QKeySequence("Ctrl+Shift+G")
    assert win.settings.value("shortcuts/go_needed") == "Ctrl+Shift+G"
    assert QKeySequence("Ctrl+Shift+G").toString(QKeySequence.NativeText) in win.alerts_lbl.text()

    from tttlog.ui.dialogs import ShortcutsDialog
    from tttlog.ui.main_window import EDITABLE_SHORTCUTS
    d = ShortcutsDialog(EDITABLE_SHORTCUTS, {"go_needed": "Ctrl+G", "swap_run": "Ctrl+G", "toggle_run": "Ctrl+R"},
                        {"Ctrl+K": "Connect / disconnect"}, win)
    assert "used twice" in d.warn.text()                    # can't save two actions on one key
    d.edits["swap_run"].setKeySequence(QKeySequence("Ctrl+K"))
    assert "already Connect" in d.warn.text()               # warned, but allowed
    d.deleteLater()
