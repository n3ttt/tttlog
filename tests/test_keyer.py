"""Voice + CW keyer: commands, Morse timing, WAV files, and keying a fake radio.

No real audio devices or radios: playback goes to a fake player and the radio
is the FakeFlex TCP server from test_rig.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import struct
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QTimer, Signal

from tttlog import config
from tttlog.core import keyer as K
from test_rig import FakeFlex, _pump, app, win  # noqa: F401  (fixtures)


# ---------------------------------------------------------------- pure logic
def test_cw_commands():
    assert K.cw_text("cq  test n3ttt?!") == "CQ TEST N3TTT?"
    cmds = K.cw_commands("flex", "cq test n3ttt n3ttt n3ttt test 5 5 5 5 tu")
    assert cmds == [b"KY CQ TEST N3TTT N3TTT ;", b"KY N3TTT TEST 5 5 5 5 TU;"]
    assert all(len(c) - len(b"KY ;") <= K.KY_CHUNK for c in cmds)
    assert K.cw_commands("yaesu", "TEST") == []                 # FTDX10 CAT can't send text
    assert K.cw_set_speed(28) == b"KS028;" and K.cw_set_speed(99) == b"KS060;"
    assert K.PTT_ON["flex"] == b"ZZTX1;" and K.PTT_OFF["yaesu"] == b"TX0;"


def test_morse_timing():
    el = K.morse_elements("PARIS", 20)                          # dit = 60 ms at 20 wpm
    assert el[0] == (True, pytest.approx(0.06)) and el[1] == (False, pytest.approx(0.06))
    assert K.cw_seconds("PARIS", 20) == pytest.approx(43 * 0.06)  # 50 units minus the final word gap
    assert K.morse_elements("E E", 20) == [(True, pytest.approx(0.06)), (False, pytest.approx(0.42)),
                                           (True, pytest.approx(0.06))]
    assert el[-1][0] is True                                    # never ends key-down... the last is a mark,
    # and LinePort always releases the line afterwards


def test_wav_files(tmp_path):
    pcm = struct.pack("<4h", 0, 1000, -1000, 32767)
    p = tmp_path / "a" / "cq.wav"
    K.write_wav(p, pcm, 8000)
    assert K.read_wav(p) == (pcm, 8000, 1)
    assert K.wav_seconds(p) == pytest.approx(4 / 8000)
    assert K.peak(pcm) == pytest.approx(32767 / 32768)
    stereo = K.convert_pcm16(pcm, 8000, 1, 16000, 2)
    assert len(stereo) == len(pcm) * 4
    assert K.convert_pcm16(stereo, 16000, 2, 8000, 1) == pcm
    assert K.float_to_pcm16(struct.pack("<2f", 0.5, -1.0)) == struct.pack("<2h", 16383, -32767)
    assert K.safe_wav_name("../my cq!.wav") == "my_cq.wav"
    assert K.wav_dir(Path("/x"), "n3ttt/p") == Path("/x/wav/N3TTT_P")


# ---------------------------------------------------------------- keying a fake radio
class FakePlayer(QObject):
    """Stands in for the sound card: 'plays' for a set time, then says it's done."""
    finished = Signal()
    failed = Signal(str)

    def __init__(self, secs=0.2, hang=False):
        super().__init__()
        self.secs, self.hang, self.played = secs, hang, []
        self.t = QTimer(singleShot=True, timeout=self.finished.emit)

    def play(self, pcm, rate, ch, device):
        self.played.append((len(pcm), rate, ch, device))
        if not self.hang:
            self.t.start(int(self.secs * 1000))

    def stop(self):
        self.t.stop()


def _radio(app, win, mode="01"):
    radio = FakeFlex()
    radio.freq_hz, radio.mode = 14250000, mode                  # USB (the app follows the radio)
    win.rig.start({**config.DEFAULT_RIG, "enabled": True, "port": radio.port, "poll_ms": 150})
    assert _pump(app, lambda: win.rig.state.startswith("connected to") and win.freq_khz == 14250.0)
    return radio


def _fake_player(win, **kw):
    p = FakePlayer(**kw)
    win.keyer.player.finished.disconnect()
    win.keyer.player.failed.disconnect()
    win.keyer.player = p
    p.finished.connect(win.keyer._voice_done)
    p.failed.connect(win.keyer._voice_failed)
    return p


def _wav(win, name, secs=0.5):
    path = win.wav_path(name)
    K.write_wav(path, b"\0\0" * int(8000 * secs), 8000)
    return path


def test_nothing_transmits_until_allowed(app, win):
    radio = _radio(app, win)
    player = _fake_player(win)
    _wav(win, "exch.wav")
    win.fkey(1)                                                 # SSB F2 (allow_tx is off by default)
    win.mode = "CW"; win.fkey(1)
    for _ in range(30):
        app.processEvents(); time.sleep(0.01)
    assert radio.writes == [] and player.played == []
    assert "Allow tttlog to transmit" in win.banner_lbl.text()
    win.rig.stop()


def test_voice_message_keys_and_unkeys(app, win):
    radio = _radio(app, win)
    player = _fake_player(win, secs=0.2)
    win.keyer.configure({**config.DEFAULT_KEYER, "allow_tx": True, "radio_out": "DAX TX",
                         "ptt_lead_ms": 50, "ptt_tail_ms": 50})
    _wav(win, "cq.wav")
    win.fkey(0)                                                 # RUN F1 = CQ
    assert _pump(app, lambda: "ZZTX1" in radio.writes)
    assert _pump(app, lambda: player.played)
    assert player.played[0][3] == "DAX TX" and win.tx_lbl.text().startswith("TX F1")
    assert _pump(app, lambda: "ZZTX0" in radio.writes)          # audio done -> PTT off
    assert win.tx_lbl.text() == ""
    assert radio.writes.index("ZZTX1") < radio.writes.index("ZZTX0")
    assert not win.keyer.busy
    win.rig.stop()


def test_escape_stops_and_time_limit(app, win):
    radio = _radio(app, win)
    _fake_player(win, hang=True)                                # audio that never finishes
    win.keyer.configure({**config.DEFAULT_KEYER, "allow_tx": True, "ptt_lead_ms": 0})
    _wav(win, "cq.wav", secs=0.1)
    win.fkey(0)
    assert _pump(app, lambda: "ZZTX1" in radio.writes)
    win.escape()                                                # Esc: unkey now, don't wipe
    assert _pump(app, lambda: "ZZTX0" in radio.writes) and not win.keyer.busy
    assert win.tx_lbl.text() == "Stopped"

    radio.writes.clear()
    win.call.setText("DL1ABC")
    win.fkey(0)                                                 # hangs again: the time limit unkeys
    assert _pump(app, lambda: "ZZTX0" in radio.writes, ms=6000)
    assert "time limit" in win.banner_lbl.text()
    win.escape()                                                # idle Esc wipes the entry line
    assert win.call.text() == ""
    win.rig.stop()


def test_cw_over_cat(app, win):
    radio = _radio(app, win, mode="04")                         # CWU
    win.keyer.configure({**config.DEFAULT_KEYER, "allow_tx": True, "wpm": 30})
    assert _pump(app, lambda: win.mode == "CW")
    win.call.setText("DL1ABC")
    win.fkey(0)                                                 # RUN F1 CW = CQ
    assert _pump(app, lambda: any(w.startswith("KY ") for w in radio.writes))
    assert "KS030" in radio.writes and "TX F1 (30 wpm)" in win.tx_lbl.text()
    win.change_wpm(+2)
    assert win.keyer.wpm == 32 and config.load_keyer()["wpm"] == 32
    win.escape()                                                # abort: back to receive
    assert _pump(app, lambda: "ZZTX0" in radio.writes)
    win.rig.stop()


def test_yaesu_cw_needs_a_keying_port(app, win):
    win.rig.cfg = {**config.DEFAULT_RIG, "dialect": "yaesu"}
    win.rig.state = "connected to the radio (yaesu)"
    win.keyer.configure({**config.DEFAULT_KEYER, "allow_tx": True})
    win.set_mode("CW")
    assert not win.keyer.send_cw("TEST")
    assert "DTR or RTS" in win.banner_lbl.text()


def test_record_assigns_a_file(app, win, monkeypatch):
    calls = []
    monkeypatch.setattr(win.keyer, "record", lambda path, mic=None: calls.append(Path(path)) or True)
    win.macros["SSB"]["RUN"][9]["wav"] = ""                      # F10 "Spare" has no file yet
    win.record_fkey(9)
    assert calls and calls[0].name == "run_f10.wav"
    assert config.load_macros()["SSB"]["RUN"][9]["wav"] == "run_f10.wav"
    assert calls[0].parent == config.CONFIG_DIR / "wav" / "N3TTT"
    calls.clear()
    win.record_fkey(11)                                         # F12 = {CLEAR}: not a message
    assert not calls and "action key" in win.banner_lbl.text()


def test_cut_numbers():
    assert K.cut_numbers("599", "nt", rst=True) == "5NN"
    assert K.cut_numbers("599", "all", rst=True) == "5NN"          # the 5 stays a 5 in an RST
    assert K.cut_numbers("579", "all", rst=True) == "5BN"
    assert K.cut_numbers("599", "none", rst=True) == "599"
    assert K.cut_numbers("05", "nt") == "T5" and K.cut_numbers("001", "ant") == "TTA"
    assert K.cut_numbers("14", "nt") == "14" and K.cut_numbers("14", "all") == "A4"


def test_cw_macros_send_cut_numbers(app, win):
    sent = []
    win.keyer.send_cw = lambda t: sent.append(t) or True
    win.mode = "CW"
    win.macros["CW"]["RUN"][1]["text"] = "{RST} {ZONE}"
    win.fkey(1)
    assert sent[-1] == "5NN 5"                                    # default: 5NN, exchange as is
    win.keyer_cfg.update(cut="all", cut_exch=True)
    win.fkey(1)
    assert sent[-1] == "5NN E"
    win.keyer_cfg.update(cut="none")
    win.fkey(1)
    assert sent[-1] == "599 5"
    win.macros["CW"]["RUN"][0]["text"] = "CQ {MYCALL}"            # callsigns are never cut
    win.keyer_cfg.update(cut="all", cut_exch=True)
    win.fkey(0)
    assert sent[-1] == "CQ N3TTT"
