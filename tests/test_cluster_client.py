"""Telnet client and refresh-timer behaviour (from PR #1 review)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QElapsedTimer
from PySide6.QtNetwork import QHostAddress, QTcpServer
from PySide6.QtWidgets import QApplication

from tttlog import config
from tttlog.core.cluster import Spot, split_telnet, strip_telnet


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def pump(app, cond, ms=3000):
    t = QElapsedTimer(); t.start()
    while not cond() and t.elapsed() < ms:
        app.processEvents()
    return cond()


class FakeCluster:
    def __init__(self):
        self.server = QTcpServer()
        assert self.server.listen(QHostAddress.LocalHost, 0)
        self.conns, self.received = [], []
        self.server.newConnection.connect(self._on_conn)

    def _on_conn(self):
        c = self.server.nextPendingConnection()
        self.conns.append(c)
        c.readyRead.connect(lambda: self.received.append(bytes(c.readAll()).decode()))
        c.write(b"login: ")

    @property
    def port(self):
        return self.server.serverPort()


# ---------------------------------------------------------------- split telnet
def test_split_telnet_keeps_incomplete_sequences():
    assert split_telnet(b"ab\xff") == (b"ab", b"\xff")
    assert split_telnet(b"ab\xff\xfb") == (b"ab", b"\xff\xfb")
    assert split_telnet(b"ab\xff\xfa\x18\x01") == (b"ab", b"\xff\xfa\x18\x01")   # SB without SE yet
    assert split_telnet(b"\xff\xfb\x01ok") == (b"ok", b"")
    assert strip_telnet(b"x\xff\xff\xff\xfd\x03y") == b"x\xffy"


def test_spot_survives_telnet_sequence_split_across_reads(app):
    from tttlog.ui.cluster_pane import ClusterClient
    fake = FakeCluster()
    c = ClusterClient()
    lines = []
    c.line.connect(lines.append)
    c.connect_to("127.0.0.1", fake.port, "N3TTT")
    assert pump(app, lambda: any("N3TTT" in r for r in fake.received))
    sock = fake.conns[0]
    for chunk in (b"\xff", b"\xfb", b"\x01DX de W3LPL:  14250.0  DL1ABC  CQ  1234Z\r\n"):
        sock.write(chunk); sock.flush()
        pump(app, lambda: False, 60)
    assert pump(app, lambda: any(l.startswith("DX de") for l in lines)), lines
    c.disconnect_from()


# ---------------------------------------------------------------- reconnect
def test_intentional_reconnect_does_not_leave_a_retry_pending(app):
    from tttlog.ui.cluster_pane import ClusterClient
    fake = FakeCluster()
    c = ClusterClient()
    c.connect_to("127.0.0.1", fake.port, "N3TTT")
    assert pump(app, c.is_connected)
    c.connect_to("127.0.0.1", fake.port, "N3TTT")     # e.g. cluster settings saved
    assert pump(app, lambda: len(fake.conns) == 2 and c.is_connected())
    pump(app, lambda: False, 200)
    assert not c._retry.isActive(), "healthy connection would be dropped by a stale retry"
    c.disconnect_from()


def test_retry_cancelled_once_connected(app):
    from tttlog.ui.cluster_pane import ClusterClient
    fake = FakeCluster()
    c = ClusterClient()
    c._want = True
    c._retry.start()                                   # a retry left over from a drop
    c.connect_to("127.0.0.1", fake.port, "N3TTT")
    assert pump(app, c.is_connected)
    assert not c._retry.isActive()
    c.disconnect_from()


# ---------------------------------------------------------------- refresh under load
def test_spots_and_needed_refresh_during_steady_traffic(app):
    from tttlog.ui.cluster_pane import SpotsPane
    from tttlog.ui.needed_pane import NeededPane
    colors = {k: dict(v) for k, v in config.DEFAULT_COLORS.items()}
    spots, needed = SpotsPane(colors), NeededPane(colors)
    now = datetime.now(timezone.utc)
    t = QElapsedTimer(); t.start()
    i = 0
    # a new spot every ~100 ms for 1.2 s: never a 250/300 ms pause
    while t.elapsed() < 1200:
        spots.add_spot(Spot(f"DL{i}AA", 14200 + i, "W3LPL", time_utc=now, status="Q"), None, [])
        needed.update_data([], spots.spots.spots())
        i += 1
        pump(app, lambda: False, 100)
    assert spots.refreshes > 0, "Spots table never refreshed while spots kept arriving"
    assert spots.table.rowCount() > 0
    assert needed.refreshes > 0, "Needed window never refreshed while spots kept arriving"
