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


def test_wrong_contest_or_network_is_refused(app, tmp_path):
    a = station(tmp_path, "A")
    b = station(tmp_path, "B", contest="ARRL-DX-SSB", peers=[f"127.0.0.1:{a.port}"])
    c = station(tmp_path, "C", net="OTHER", peers=[f"127.0.0.1:{a.port}"])
    a.sync.local_put(qso("DL1ABC"))
    assert wait(lambda: "different contest" in a.peers.get("node-B", {}).get("note", ""))
    assert wait(lambda: "network" in a.peers.get("node-C", {}).get("note", ""))
    assert not a.linked() and b.sync.log.all() == [] and c.sync.log.all() == []
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
