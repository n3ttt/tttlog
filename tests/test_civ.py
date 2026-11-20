"""Icom CI-V: frames, BCD, modes, and following / tuning / keying a fake Icom."""
import time

from tttlog import config
from tttlog.core import civ
from tttlog.core.civ import IcomDialect, frame, from_bcd, split_frames, to_bcd
from tttlog.core.rig import make_dialect

from tests.test_rig import _pump, app, win  # noqa: F401  (fixtures)


def test_bcd_and_frames():
    assert to_bcd(14_025_000, 5) == bytes.fromhex("0050021400")
    assert from_bcd(bytes.fromhex("0050021400")) == 14_025_000
    assert from_bcd(bytes.fromhex("5009000000")) == 950               # 9.50 kHz... nibble order
    assert from_bcd(b"\x0a\x00") is None                                # not BCD
    assert to_bcd(1_296_100_000, 5) == bytes.fromhex("0000109612")      # 1296.1 MHz
    assert frame(0x94, 0x03) == bytes.fromhex("fefe94e003fd")
    frames, rest = split_frames(bytes.fromhex("00 fe fe e0 94 03 00 50 02 14 00 fd fe fe fe e0 94 fb fd fe fe e0"))
    assert frames == [bytes.fromhex("e0940300500214 00".replace(" ", "")), bytes.fromhex("e094fb")]
    assert rest == bytes.fromhex("fefee0")
    assert civ.cw_speed_level(28) == 134 and civ.cw_speed_level(5) == 0 and civ.cw_speed_level(99) == 250


def test_dialect_parse_and_commands():
    d = make_dialect({"dialect": "icom", "civ_model": "ic7300"})
    assert isinstance(d, IcomDialect) and d.addr == 0x94
    assert make_dialect({"dialect": "icom", "civ_model": "ic7610"}).addr == 0x98
    assert make_dialect({"dialect": "icom", "civ_model": "ic7300", "civ_addr": 0x70}).addr == 0x70
    assert d.poll() == [bytes.fromhex(x) for x in ("fefe94e003fd", "fefe94e004fd", "fefe94e01a06fd")]

    p = lambda hexs: d.parse(bytes.fromhex(hexs))
    assert p("94e003") == []                                            # our own echo
    assert p("e09803 0050021400".replace(" ", "")) == []                # another radio on the bus
    assert p("e0940300500214 00".replace(" ", "")) == [("freq", 14025.0)]
    assert p("00940000204007 00".replace(" ", "")) == [("freq", 7402.0)]   # transceive broadcast
    assert p("e094040102") == [("mode", "USB")] and d.filt == 2
    assert p("e0941a060101") == [("mode", "DIGU")]                     # data mode on
    assert p("e094040002") == [("mode", "DIGL")]
    assert p("e0941a060000") == [("mode", "LSB")]
    assert p("e094040301") == [("mode", "CWU")] and p("e094040701") == [("mode", "CWL")]
    assert p("e094040801") == [("mode", "RTTY")] and p("e094040501") == [("mode", "FM")]

    assert d.set_freq(7025.25) == bytes.fromhex("fefe94e005 5052 0207 00 fd".replace(" ", ""))
    d.filt = 2
    assert d.set_mode("DIGU") == [bytes.fromhex("fefe94e0060102fd"), bytes.fromhex("fefe94e01a060102fd")]
    assert d.set_mode("USB") == [bytes.fromhex("fefe94e0060102fd"), bytes.fromhex("fefe94e01a060000fd")]
    assert d.set_mode("CWU") == [bytes.fromhex("fefe94e0060302fd")]
    assert d.ptt(True) == bytes.fromhex("fefe94e01c0001fd") and d.ptt(False) == bytes.fromhex("fefe94e01c0000fd")
    assert d.cw_speed(28) == bytes.fromhex("fefe94e0140c0134fd")
    long = d.cw("cq test n3ttt n3ttt n3ttt test 5nn de")
    assert len(long) == 2 and long[0] == frame(0x94, 0x17, data=b"CQ TEST N3TTT N3TTT N3TTT TEST")
    assert d.cw_abort()[0] == bytes.fromhex("fefe94e017fffd")


def test_older_radio_without_data_mode():
    d = make_dialect({"dialect": "icom", "civ_model": "ic7000"})
    assert len(d.poll()) == 2 and d.set_mode("USB") == [bytes.fromhex("fefe70e0060101fd")]
    assert not d.can_cw
    # a radio that refuses the data-mode query: give up after a few NGs
    d = make_dialect({"dialect": "icom", "civ_model": "other", "civ_addr": 0x94})
    for _ in range(3):
        d.poll()
        d.parse(bytes.fromhex("e094fa"))
    assert len(d.poll()) == 2


# ---------------------------------------------------------------- fake radio
class FakeIcom:
    """An IC-7300 on a raw CI-V TCP bridge. Echoes every frame back (like 'CI-V USB
    Echo Back' ON or a one-wire bus), answers reads, and records commands."""

    def __init__(self, addr=0x94, echo=True, data_ok=True):
        from PySide6.QtNetwork import QHostAddress, QTcpServer
        self.addr, self.echo, self.data_ok = addr, echo, data_ok
        self.freq_hz, self.mode, self.filt, self.data = 14_074_000, 0x01, 1, True
        self.writes: list[bytes] = []
        self.ptt = False
        self.bkin = 0                      # break-in OFF, like the user's IC-705
        self.sent_on_air: list[bytes] = []
        self.server = QTcpServer()
        assert self.server.listen(QHostAddress.LocalHost, 0)
        self.server.newConnection.connect(self._conn)
        self.port = self.server.serverPort()
        self.clients = []

    def reply(self, c, cmd, data=b""):
        c.write(frame(civ.CTRLID, cmd, None, data, frm=self.addr))

    def _conn(self):
        c = self.server.nextPendingConnection()
        self.clients.append(c)
        buf = [b""]

        def read():
            raw = bytes(c.readAll())
            if self.echo:
                c.write(raw)
            frames, buf[0] = split_frames(buf[0] + raw)
            for f in frames:
                to, cmd, data = f[0], f[2], f[3:]
                if to != self.addr:
                    continue
                if cmd == 0x03:
                    self.reply(c, 0x03, to_bcd(self.freq_hz, 5))
                elif cmd == 0x04:
                    self.reply(c, 0x04, bytes([self.mode, self.filt]))
                elif cmd == 0x16 and data == b"\x47":
                    self.reply(c, 0x16, bytes([0x47, self.bkin]))
                elif cmd == 0x17 and data != b"\xff" and self.mode not in (0x03, 0x07):
                    self.writes.append(f)
                    self.reply(c, 0xFA)                     # CW text outside CW mode: NG
                elif cmd == 0x1A and data[:1] == b"\x06" and len(data) == 1:
                    if self.data_ok:
                        self.reply(c, 0x1A, bytes([0x06, int(self.data), self.filt if self.data else 0]))
                    else:
                        self.reply(c, 0xFA)
                else:
                    self.writes.append(f)
                    if cmd == 0x05:
                        self.freq_hz = from_bcd(data[:5])
                    elif cmd == 0x06:
                        self.mode = data[0]
                    elif cmd == 0x1A and data[:1] == b"\x06":
                        self.data = bool(data[1])
                    elif cmd == 0x1C:
                        self.ptt = bool(data[1])
                    elif cmd == 0x16 and data[:1] == b"\x47":
                        self.bkin = data[1]
                    elif cmd == 0x17 and data != b"\xff" and (self.bkin or self.ptt):
                        self.sent_on_air.append(data)       # only with break-in on (or PTT)
                    self.reply(c, 0xFB)
        c.readyRead.connect(read)


def _cfg(radio, control, **kw):
    return {**config.DEFAULT_RIG, "enabled": True, "dialect": "icom", "civ_model": "ic7300",
            "port": radio.port, "poll_ms": 150, "control": control, **kw}


def test_follows_an_icom(app, win):  # noqa: F811
    radio = FakeIcom()
    win.rig.start(_cfg(radio, control=False))
    assert _pump(app, lambda: win.freq_khz == 14074.0 and win.mode == "FT8")   # USB + data = digital
    assert "IC-7300, CI-V 94h" in win.rig.state
    radio.freq_hz, radio.mode, radio.data = 14_025_500, 0x03, False            # dial + CW
    assert _pump(app, lambda: win.freq_khz == 14025.5 and win.mode == "CW")
    radio.mode = 0x01
    assert _pump(app, lambda: win.mode == "SSB")
    for _ in range(30):
        app.processEvents(); time.sleep(0.01)
    assert radio.writes == []                                                 # follow-only: reads only
    win.rig.stop()


def test_tunes_an_icom(app, win):  # noqa: F811
    radio = FakeIcom()
    radio.data = False
    win.rig.start(_cfg(radio, control=True))
    assert _pump(app, lambda: win.freq_khz == 14074.0 and win.rig.is_connected())
    win.set_mode("CW")
    win.band_pane.buttons["40m"].click()
    assert _pump(app, lambda: radio.freq_hz == 7_025_000 and radio.mode == 0x03)
    win.set_mode("FT8")
    assert _pump(app, lambda: radio.mode == 0x01 and radio.data)               # USB + data mode
    for _ in range(60):                                                        # stale polls don't bounce it
        app.processEvents(); time.sleep(0.01)
    assert win.mode == "FT8"
    win.rig.stop()


def test_older_icom_refuses_data_query(app, win):  # noqa: F811
    radio = FakeIcom(addr=0x94, data_ok=False)
    radio.data = False
    win.rig.start(_cfg(radio, control=False, civ_model="other", civ_addr=0x94))
    assert _pump(app, lambda: win.freq_khz == 14074.0 and win.mode == "SSB")
    assert _pump(app, lambda: not win.rig.dialect.data_ok)                    # stops asking
    win.rig.stop()


def test_cw_and_ptt_on_an_icom(app, win):  # noqa: F811
    radio = FakeIcom()
    radio.mode, radio.data = 0x03, False
    win.rig.start(_cfg(radio, control=False))
    win.keyer.configure({**config.DEFAULT_KEYER, "allow_tx": True, "wpm": 28})
    assert _pump(app, lambda: win.mode == "CW")
    win.call.setText("DL1ABC")
    win.fkey(0)                                                                # RUN F1 = CQ
    assert _pump(app, lambda: any(f[2] == 0x17 for f in radio.writes))
    assert any(f[2] == 0x14 and f[3:] == bytes.fromhex("0c0134") for f in radio.writes)   # 28 wpm
    sent = b"".join(f[3:] for f in radio.writes if f[2] == 0x17)
    assert b"N3TTT" in sent
    assert radio.bkin == 1 and radio.sent_on_air                               # break-in turned on first
    assert "semi break-in" in win.banner_lbl.text()
    win.escape()                                                               # abort: stop CW, receive
    assert _pump(app, lambda: any(f[2] == 0x17 and f[3:] == b"\xff" for f in radio.writes))
    win.rig.stop()


def test_icom_break_in_already_on_is_left_alone(app, win):  # noqa: F811
    radio = FakeIcom()
    radio.mode, radio.data, radio.bkin = 0x03, False, 2                        # full break-in
    win.rig.start(_cfg(radio, control=False))
    win.keyer.configure({**config.DEFAULT_KEYER, "allow_tx": True})
    assert _pump(app, lambda: win.mode == "CW" and win.rig.dialect.bkin == 2)  # read while in CW
    win.call.setText("DL1ABC"); win.fkey(0)
    assert _pump(app, lambda: radio.sent_on_air)
    assert radio.bkin == 2 and not any(f[2] == 0x16 and len(f) > 4 for f in radio.writes)
    win.rig.stop()


def test_icom_refuses_cw_outside_cw_mode(app, win):  # noqa: F811
    radio = FakeIcom()
    radio.mode, radio.data = 0x01, False                                       # radio left in USB
    win.rig.start(_cfg(radio, control=False))
    win.keyer.configure({**config.DEFAULT_KEYER, "allow_tx": True})
    assert _pump(app, lambda: win.rig.is_connected() and win.mode == "SSB")
    win.mode = "CW"                                                            # tttlog thinks CW
    assert win.keyer.send_cw("TEST")
    assert _pump(app, lambda: "refused the CW" in win.banner_lbl.text())
    assert not win.keyer.keyed
    win.rig.stop()


def test_stale_transmit_off_banner_clears(app, win, monkeypatch):  # noqa: F811
    from tttlog.ui import main_window as mw
    radio = FakeIcom()
    radio.mode, radio.data = 0x03, False
    win.rig.start(_cfg(radio, control=False))
    assert _pump(app, lambda: win.mode == "CW")
    win.keyer.configure({**config.DEFAULT_KEYER, "allow_tx": False})
    win.call.setText("DL1ABC"); win.fkey(0)
    assert "Allow tttlog to transmit" in win.banner_lbl.text()

    class Dlg:                                                                 # user ticks Allow, OK
        def __init__(self, *a): pass
        def exec(self): return True
        def values(self): return {**config.DEFAULT_KEYER, "allow_tx": True}
    monkeypatch.setattr(mw, "KeyerDialog", Dlg)
    monkeypatch.setattr(config, "save_keyer", lambda cfg: None)
    win.edit_keyer()
    assert "Allow tttlog to transmit" not in win.banner_lbl.text()
    win.rig.stop()
