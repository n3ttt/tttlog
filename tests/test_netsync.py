"""Log sharing between stations, without sockets."""
from datetime import datetime, timedelta, timezone

from tttlog.core.db import Log
from tttlog.core.models import QSO
from tttlog.core.netsync import LogSync

T0 = datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc)


def q(call, minutes=0, khz=14200.0):
    return QSO(call=call, freq_khz=khz, mode="SSB", exch_rcvd="14", time_utc=T0 + timedelta(minutes=minutes))


def node(tmp_path, name):
    return LogSync(Log(tmp_path / f"{name}.db"), node_id=f"node-{name}", station_name=name.upper())


def swap(a: LogSync, b: LogSync):
    """What two stations do when they connect: send each other what's missing."""
    for ev in a.events_after(b.vector()):
        b.apply(ev)
    for ev in b.events_after(a.vector()):
        a.apply(ev)


def calls(s: LogSync):
    return sorted((x.call, x.station_name) for x in s.log.all())


def test_two_stations_end_up_with_the_same_log(tmp_path):
    a, b = node(tmp_path, "run"), node(tmp_path, "mult")
    a.local_put(q("DL1ABC")); a.local_put(q("G4XYZ", 1))
    b.local_put(q("JA1AA", 2))
    swap(a, b)
    assert calls(a) == calls(b) == [("DL1ABC", "RUN"), ("G4XYZ", "RUN"), ("JA1AA", "MULT")]
    assert a.vector() == b.vector() == {"node-run": 2, "node-mult": 1}
    swap(a, b)                                            # nothing new: nothing changes
    assert len(a.log.all()) == 3


def test_live_events_edits_and_deletes(tmp_path):
    a, b = node(tmp_path, "a"), node(tmp_path, "b")
    ev = a.local_put(q("DL1ABC"))
    assert b.apply(ev) == (True, True)
    assert b.apply(ev) == (False, False)                  # second copy (another path) ignored
    x = b.log.find_uid(ev["u"])
    x.exch_rcvd = "15"                                    # B fixes the zone
    a.apply(b.local_put(x))
    assert a.log.find_uid(ev["u"]).exch_rcvd == "15"
    a.apply(b.local_delete(b.log.find_uid(ev["u"])))
    assert a.log.all() == [] and b.log.all() == []


def test_newest_edit_wins_on_every_station(tmp_path):
    a, b = node(tmp_path, "a"), node(tmp_path, "b")
    ev = a.local_put(q("DL1ABC")); b.apply(ev)
    xa, xb = a.log.find_uid(ev["u"]), b.log.find_uid(ev["u"])
    xa.exch_rcvd = "14A"; ea = a.local_put(xa)            # both edit while unlinked
    xb.exch_rcvd = "14B"; eb = b.local_put(xb)
    swap(a, b)
    winner = "14B" if (eb["t"], eb["o"]) > (ea["t"], ea["o"]) else "14A"
    assert a.log.find_uid(ev["u"]).exch_rcvd == b.log.find_uid(ev["u"]).exch_rcvd == winner


def test_delete_arriving_before_the_qso_sticks(tmp_path):
    a, b, c = node(tmp_path, "a"), node(tmp_path, "b"), node(tmp_path, "c")
    add = a.local_put(q("DL1ABC")); b.apply(add)
    dele = b.local_delete(b.log.find_uid(add["u"]))
    assert c.apply(dele) == (True, False)                 # C hears the delete first
    assert c.apply(add) == (True, False)                  # older add doesn't bring it back
    assert c.log.all() == []


def test_late_joiner_and_relay(tmp_path):
    a, b, c = node(tmp_path, "a"), node(tmp_path, "b"), node(tmp_path, "c")
    for i in range(5):
        a.local_put(q(f"DL{i}AA", i))
    swap(a, b)                                            # C was off; it only ever talks to B
    swap(b, c)
    assert len(c.log.all()) == 5 and c.vector() == {"node-a": 5}


def test_gap_is_refilled(tmp_path):
    a, b = node(tmp_path, "a"), node(tmp_path, "b")
    evs = [a.local_put(q(f"DL{i}AA", i)) for i in range(3)]
    b.apply(evs[0]); b.apply(evs[2])                      # #2 got lost
    assert b.vector() == {"node-a": 1}
    swap(a, b)
    assert len(b.log.all()) == 3 and b.vector() == {"node-a": 3}


def test_existing_log_is_shared_when_networking_starts(tmp_path):
    log = Log(tmp_path / "old.db")
    log.add(q("DL1ABC")); log.add(q("G4XYZ", 1))
    a = LogSync(log, "node-a", "A")
    b = node(tmp_path, "b")
    swap(a, b)
    assert sorted(x.call for x in b.log.all()) == ["DL1ABC", "G4XYZ"]
    a2 = LogSync(log, "node-a", "A")                      # reopening doesn't add events again
    assert a2.count() == 2


def test_bad_events_are_ignored(tmp_path):
    b = node(tmp_path, "b")
    for bad in [{}, {"o": "x", "s": "1", "t": "", "a": "put", "u": "abcdefgh", "q": {}},
                {"o": "x", "s": 1, "t": "t", "a": "put", "u": "abcdefgh", "q": {"call": "X"}},
                {"o": "x", "s": 1, "t": "t", "a": "drop", "u": "abcdefgh", "q": None}]:
        assert b.apply(bad) == (False, False)
    assert b.log.all() == []


def test_bulk_catch_up_is_fast(tmp_path):
    import time
    a, b = node(tmp_path, "a"), node(tmp_path, "b")
    with a.bulk():
        for i in range(1500):
            a.local_put(q(f"K{i}AA", i * 0.5))
    t = time.monotonic()
    with b.bulk():
        for ev in a.events_after(b.vector()):
            b.apply(ev)
    assert len(b.log.all()) == 1500
    assert time.monotonic() - t < 10
