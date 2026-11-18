"""Real TCP links between stations on this computer (no broadcast needed)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from tttlog.core.db import Log
from tttlog.core.models import QSO
from tttlog.core.netsync import LogSync
from tttlog.ui.network_pane import NetNode, parse_peer


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait(cond, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def station(tmp_path, name, contest="CQ-WW-SSB", net="TEST", peers=()):
    sync = LogSync(Log(tmp_path / f"{name}.db"), f"node-{name}", name)
    n = NetNode(f"node-{name}")
    n.set_log(sync, contest)
    assert n.start({"station_name": name, "net_name": net, "tcp_port": 0, "udp_port": 0,
                    "peers": list(peers)})
    return n


def qso(call):
    return QSO(call=call, freq_khz=14200, mode="SSB", exch_rcvd="14",
               time_utc=datetime.now(timezone.utc).replace(microsecond=0))


def test_parse_peer():
    assert parse_peer("192.168.1.20", 12071) == ("192.168.1.20", 12071)
    assert parse_peer("shack-pc:12099", 12071) == ("shack-pc", 12099)
    assert parse_peer("  ", 12071) is None and parse_peer("x:abc", 1) is None


def test_two_stations_share_log_status_and_talk(app, tmp_path):
    a = station(tmp_path, "RUN")
    a.sync.local_put(qso("DL1ABC"))                       # logged before the link came up
    b = station(tmp_path, "MULT", peers=[f"127.0.0.1:{a.port}"])
    assert wait(lambda: a.linked() and b.linked())
    assert wait(lambda: [x.call for x in b.sync.log.all()] == ["DL1ABC"])

    got = []
    a.logChanged.connect(lambda: got.append(1))
    b.publish(b.sync.local_put(qso("JA1AA")))              # live QSO from B
    assert wait(lambda: sorted(x.call for x in a.sync.log.all()) == ["DL1ABC", "JA1AA"])
    assert got and a.sync.log.find_uid(b.sync.log.all()[-1].uid).station_name == "MULT"

    a.set_status({"op": "N3TTT", "band": "20m", "freq": 14200.0, "mode": "SSB", "run": True, "qsos": 2})
    assert wait(lambda: b.peers["node-RUN"]["status"].get("band") == "20m")
    said = []
    b.talkReceived.connect(lambda who, text: said.append((who, text)))
    a.talk("QSY 40m please")
    assert wait(lambda: said == [("RUN", "QSY 40m please")])
    a.stop(); b.stop()


def test_three_stations_relay_and_reconnect(app, tmp_path):
    a = station(tmp_path, "A")
    b = station(tmp_path, "B", peers=[f"127.0.0.1:{a.port}"])
    c = station(tmp_path, "C", peers=[f"127.0.0.1:{b.port}"])   # C only knows B
    assert wait(lambda: len(b.linked()) == 2)
    a.publish(a.sync.local_put(qso("PY2AA")))
    assert wait(lambda: [x.call for x in c.sync.log.all()] == ["PY2AA"])   # passed on by B

    c.stop()                                              # C drops out, A keeps logging
    a.publish(a.sync.local_put(qso("ZS6ABC")))
    c.start({"station_name": "C", "net_name": "TEST", "tcp_port": 0, "udp_port": 0,
             "peers": [f"127.0.0.1:{b.port}"]})
    assert wait(lambda: sorted(x.call for x in c.sync.log.all()) == ["PY2AA", "ZS6ABC"], 8)
    for n in (a, b, c):
        n.stop()


def test_different_contest_links_with_warning_but_keeps_logs_apart(app, tmp_path):
    a = station(tmp_path, "A")
    b = station(tmp_path, "B", contest="ARRL-DX-SSB", peers=[f"127.0.0.1:{a.port}"])
    c = station(tmp_path, "C", net="OTHER", peers=[f"127.0.0.1:{a.port}"])
    warnings = []
    a.contestWarning.connect(warnings.append)
    a.publish(a.sync.local_put(qso("DL1ABC")))
    assert wait(lambda: a.linked() and b.linked())                  # linked: not a hard fault
    assert wait(lambda: warnings and "ARRL-DX-SSB" in warnings[0])  # but warned, once
    assert "log not shared" in a.mismatch(a.peers["node-B"])
    a.publish(a.sync.local_put(qso("JA1AA")))
    wait(lambda: False, 0.5)
    assert b.sync.log.all() == []                                   # logs stay apart
    said = []
    b.talkReceived.connect(lambda who, text: said.append(text))
    a.talk("you're on the wrong contest")                           # talk still works
    assert wait(lambda: said == ["you're on the wrong contest"])
    assert wait(lambda: "network" in a.peers.get("node-C", {}).get("note", ""))   # other network: refused
    assert len(warnings) == 1

    # B opens the same contest: the link is renegotiated and B catches up
    b.set_log(b.sync, "CQ-WW-SSB")
    assert wait(lambda: sorted(x.call for x in b.sync.log.all()) == ["DL1ABC", "JA1AA"], 8)
    assert a.mismatch(a.peers["node-B"]) == ""
    for n in (a, b, c):
        n.stop()


def test_shared_cluster_connection(app, tmp_path):
    a = station(tmp_path, "A")                                      # connected to the cluster
    b = station(tmp_path, "B", peers=[f"127.0.0.1:{a.port}"])
    c = station(tmp_path, "C", contest="ARRL-DX-SSB", peers=[f"127.0.0.1:{b.port}"])   # via B, other contest
    assert wait(lambda: len(b.linked()) == 2)
    a.set_cluster_up(True)
    assert wait(lambda: b.cluster_source() and c.cluster_source())
    assert c.cluster_source()["name"] == "A"

    got_b, got_c, cmds = [], [], []
    b.clusterLines.connect(lambda src, lines: got_b.extend(lines))
    c.clusterLines.connect(lambda src, lines: got_c.extend(lines))
    a.clusterCommand.connect(lambda who, text: cmds.append((who, text)))
    spot = "DX de W3LPL:     14205.0  DL1ABC       59 loud           1234Z"
    a.publish_cluster(["Welcome to the node", spot])
    assert wait(lambda: got_b == ["Welcome to the node", spot] and got_c == got_b)

    assert c.send_cluster_command("dx 14025.0 JA1AA") == "A"      # relayed through B
    assert wait(lambda: cmds == [("C", "dx 14025.0 JA1AA")])

    a.set_cluster_up(False)                                         # A drops the cluster
    assert wait(lambda: b.cluster_source() is None)
    assert b.send_cluster_command("sh/dx") is None
    for n in (a, b, c):
        n.stop()


def test_both_dial_keeps_one_link(app, tmp_path):
    a = station(tmp_path, "A")
    b = station(tmp_path, "B", peers=[f"127.0.0.1:{a.port}"])
    a.cfg["peers"] = [f"127.0.0.1:{b.port}"]; a._maintain()
    assert wait(lambda: a.linked() and b.linked())
    wait(lambda: False, 0.5)
    assert len([l for l in a.links if l.ready]) == 1 and len([l for l in b.links if l.ready]) == 1
    a.stop(); b.stop()


def test_beacon_discovery(app, tmp_path):
    """Two stations find each other by UDP broadcast (skipped where the OS blocks it)."""
    cfg = {"net_name": "BEACON", "tcp_port": 0, "udp_port": 12370, "peers": []}
    nodes = []
    for name in ("X", "Y"):
        n = NetNode(f"node-{name}")
        n.set_log(LogSync(Log(tmp_path / f"{name}.db"), f"node-{name}", name), "CQ-WW-SSB")
        n.start({**cfg, "station_name": name})
        nodes.append(n)
    ok = wait(lambda: nodes[0].linked() and nodes[1].linked(), 8)
    for n in nodes:
        n.stop()
    if not ok:
        pytest.skip("UDP broadcast not delivered on this machine")


def test_two_windows_share_dupes(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from tttlog import config
    from tttlog.contests.engine import Station
    import tttlog.ui.main_window as mw
    for name in ("STATION_FILE", "MACROS_FILE", "CLUSTER_FILE", "COLORS_FILE"):
        monkeypatch.setattr(config, name, tmp_path / "cfg" / getattr(config, name).name)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    config.save_station(Station(call="N3TTT", state="DE", cq_zone=5))

    wins = []
    for name, peers in (("RUN", []), ("MULT", None)):
        ini = str(tmp_path / f"{name}.ini")
        monkeypatch.setattr(mw, "QSettings", lambda *a, ini=ini: QSettings(ini, QSettings.IniFormat))
        if peers is None:
            peers = [f"127.0.0.1:{wins[0].net.port}"]
        cfg = {**config.DEFAULT_NETWORK, "enabled": True, "station_name": name, "net_name": "T",
               "tcp_port": 0, "udp_port": 0, "peers": peers}
        monkeypatch.setattr(config, "load_network", lambda cfg=cfg: dict(cfg))
        monkeypatch.setattr(config, "node_id", lambda name=name: f"node-{name}")
        w = mw.MainWindow()
        db = tmp_path / f"{name}.db"
        l = Log(db); l.set_meta("contest_id", "ARRL-DX-SSB"); l.close()
        w.open_log(db)
        wins.append(w)
    run, mult = wins
    assert wait(lambda: run.net.linked() and mult.net.linked())

    run.call.setText("DL1ABC"); run.exch.setText("100"); run.on_enter()
    assert wait(lambda: [q.call for q in mult.qsos] == ["DL1ABC"])
    mult.call.setText("DL1ABC"); mult._live_check("DL1ABC")
    assert "DUPE on 20m (worked by RUN)" in mult.banner_lbl.text()
    assert wait(lambda: mult.network_pane.table.rowCount() == 2)
    assert mult.log_table.item(0, 8).text() == "RUN"
    for w in wins:
        w.close()


def test_two_windows_share_one_cluster_connection(app, tmp_path, monkeypatch):
    """RUN is logged in to the cluster; MULT (not connected) gets its spots and
    sends its spot through RUN. The two are on different contests: warned, still linked."""
    from PySide6.QtCore import QSettings
    from PySide6.QtNetwork import QHostAddress, QTcpServer
    from tttlog import config
    from tttlog.contests.engine import Station
    import tttlog.ui.main_window as mw
    for name in ("STATION_FILE", "MACROS_FILE", "CLUSTER_FILE", "COLORS_FILE"):
        monkeypatch.setattr(config, name, tmp_path / "cfg" / getattr(config, name).name)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    config.save_station(Station(call="N3TTT", state="DE", cq_zone=5))

    server = QTcpServer(); assert server.listen(QHostAddress.LocalHost, 0)
    clients, received = [], []

    def on_conn():
        c = server.nextPendingConnection()
        clients.append(c)
        c.readyRead.connect(lambda c=c: received.append(bytes(c.readAll()).decode()))
        c.write(b"Welcome to W3LPL AR-Cluster node\r\nPlease enter your call: ")
    server.newConnection.connect(on_conn)
    config.save_cluster({**config.DEFAULT_CLUSTER, "host": "127.0.0.1", "port": server.serverPort()})

    wins = []
    for name, contest in (("RUN", "ARRL-DX-SSB"), ("MULT", "CQ-WW-SSB")):
        ini = str(tmp_path / f"{name}.ini")
        monkeypatch.setattr(mw, "QSettings", lambda *a, ini=ini: QSettings(ini, QSettings.IniFormat))
        peers = [f"127.0.0.1:{wins[0].net.port}"] if wins else []
        cfg = {**config.DEFAULT_NETWORK, "enabled": True, "station_name": name, "net_name": "T",
               "tcp_port": 0, "udp_port": 0, "peers": peers}
        monkeypatch.setattr(config, "load_network", lambda cfg=cfg: dict(cfg))
        monkeypatch.setattr(config, "node_id", lambda name=name: f"node-{name}")
        w = mw.MainWindow()
        db = tmp_path / f"{name}.db"
        l = Log(db); l.set_meta("contest_id", contest); l.close()
        w.open_log(db)
        wins.append(w)
    run, mult = wins
    assert wait(lambda: run.net.linked() and mult.net.linked())
    assert wait(lambda: "log not shared" in mult.banner_lbl.text() or "NOT shared" in mult.banner_lbl.text())
    assert wait(lambda: mult.network_pane.table.rowCount() == 2)
    assert any("log not shared" in (mult.network_pane.table.item(r, 7).text())
               for r in range(mult.network_pane.table.rowCount()))

    run.cluster_connect(True)
    assert wait(lambda: clients and any("N3TTT" in r for r in received))        # RUN logged in
    assert run.cluster_kind == "ar"
    assert wait(lambda: mult.net.cluster_source() is not None)
    assert "Using RUN's cluster connection" in mult.telnet_pane.status_lbl.text()

    clients[0].write(b"DX de W3LPL:     14205.0  DL1ABC       59 loud           1234Z\r\n"
                     b"DX de K1TTT-#:   14025.0  JA1AA        CW 20 dB 28 WPM CQ  1234Z\r\n")
    assert wait(lambda: len(mult.spots_pane.spots) == 2)                        # came over the LAN
    assert mult.cluster_kind == "ar"
    mult.spots_pane._change_filter(skimmer="no")
    assert [s.call for s in mult.spots_pane.filtered_spots()] == ["DL1ABC"]
    assert len(run.spots_pane.filtered_spots()) == 2                          # filters are per station

    mult.telnet_pane.cmd.setText("sh/dx 5"); mult._cluster_cmd()                 # typed at MULT
    assert wait(lambda: any("sh/dx 5" in r for r in received))
    mult.send_filter_to_cluster()                                               # out through RUN's login
    assert wait(lambda: any("set dx filter not skimmer" in r for r in received))
    for w in wins:
        w.close()
    server.close()


def test_operator_profile_follows_to_another_station(app, tmp_path, monkeypatch):
    """K3ABC sets up their panes and license class at RUN; OPON K3ABC at MULT brings both."""
    from PySide6.QtCore import QRect, QSettings
    from tttlog import config
    from tttlog.contests.engine import Station
    import tttlog.ui.main_window as mw
    for name in ("STATION_FILE", "MACROS_FILE", "CLUSTER_FILE", "COLORS_FILE"):
        monkeypatch.setattr(config, name, tmp_path / "cfg" / getattr(config, name).name)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    config.save_station(Station(call="N3TTT", state="DE", cq_zone=5, license_class="Extra"))

    wins = []
    for name in ("RUN", "MULT"):
        ini = str(tmp_path / f"{name}.ini")
        monkeypatch.setattr(mw, "QSettings", lambda *a, ini=ini: QSettings(ini, QSettings.IniFormat))
        peers = [f"127.0.0.1:{wins[0].net.port}"] if wins else []
        cfg = {**config.DEFAULT_NETWORK, "enabled": True, "station_name": name, "net_name": "T",
               "tcp_port": 0, "udp_port": 0, "peers": peers}
        monkeypatch.setattr(config, "load_network", lambda cfg=cfg: dict(cfg))
        monkeypatch.setattr(config, "node_id", lambda name=name: f"node-{name}")
        w = mw.MainWindow()
        w.resize(1200, 760); w.show()
        wins.append(w)
    run, mult = wins
    assert wait(lambda: run.net.linked() and mult.net.linked())

    run.opon("K3ABC")
    run.set_license_class("K3ABC", "General")
    run.canvas.place(run.dock_log, QRect(3, 12, 20, 14))
    run.dock_telnet.set_minimized(True)
    run.opon("N3TTT")                                   # K3ABC leaves RUN: their profile is sent
    theirs = run.dock_log.grid.getRect()
    assert wait(lambda: mult.settings.value("op_class/K3ABC") == "General")

    mult.opon("K3ABC")                                  # ...and sits down at MULT
    wait(lambda: False, 0.3)
    assert mult.license_class == "General"
    assert mult.dock_log.grid.getRect() == (3, 12, 20, 14) and mult.dock_telnet.minimized
    assert "K3ABC's window layout" in mult.banner_lbl.text()

    for w in wins:
        w.close()


def test_profiles_newest_wins_and_late_stations_catch_up(app, tmp_path):
    a = station(tmp_path, "RUN")
    b = station(tmp_path, "MULT", peers=[f"127.0.0.1:{a.port}"])
    assert wait(lambda: a.linked() and b.linked())
    got = []
    b.profileReceived.connect(lambda op, d, at: got.append((op, d, at)))
    a.publish_profile("k3abc", {"class": "General"}, 100.0)
    assert wait(lambda: got and got[-1][0] == "K3ABC")
    a.publish_profile("K3ABC", {"class": "Extra"}, 50.0)         # older than what's known: ignored
    wait(lambda: False, 0.3)
    assert b.profiles["K3ABC"] == (100.0, {"class": "General"})
    c = station(tmp_path, "CW", peers=[f"127.0.0.1:{a.port}"])   # links later
    assert wait(lambda: c.profiles.get("K3ABC") == (100.0, {"class": "General"}))
    for n in (a, b, c):
        n.stop()
