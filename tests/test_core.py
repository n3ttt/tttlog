from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from tttlog.core.cty import CtyDat
from tttlog.core.db import Log
from tttlog.core.models import QSO
from tttlog.contests.engine import ContestEngine, Station, load_rules, list_contests
from tttlog.export.adif import export_adif, import_adif
from tttlog.export.cabrillo import export_cabrillo

FIX = Path(__file__).parent / "fixtures" / "cty_sample.dat"
T0 = datetime(2027, 3, 6, 0, 1, tzinfo=timezone.utc)


@pytest.fixture
def cty():
    return CtyDat(FIX)


@pytest.fixture
def station():
    return Station(call="N3TTT", state="DE", cq_zone=5, club="Frankford Radio Club")


def q(call, khz, exch, minutes=0):
    return QSO(call=call, freq_khz=khz, mode="SSB", exch_sent="DE", exch_rcvd=exch,
               time_utc=T0 + timedelta(minutes=minutes), station_call="N3TTT",
               contest_id="ARRL-DX-SSB")


def test_cty_lookup(cty):
    assert cty.lookup("DL1ABC")[0].name == "Fed. Rep. of Germany"
    assert cty.lookup("N3TTT")[0].name == "United States"
    assert cty.lookup("KH6XX")[0].name == "Hawaii"
    assert cty.lookup("W6XYZ")[1] == 3            # exact-call zone override
    assert cty.lookup("DL/N3TTT")[0].name == "Fed. Rep. of Germany"
    assert cty.lookup("N3TTT/P")[0].name == "United States"
    assert cty.lookup("JA1XYZ")[1] == 25


def test_contests_listed():
    ids = {c["id"] for c in list_contests()}
    assert {"ARRL-DX-SSB", "CQ-WW-SSB", "CQ-WW-CW"} <= ids


def test_arrl_dx_scoring(cty, station):
    eng = ContestEngine(load_rules("ARRL-DX-SSB"), cty, station)
    log = [q("DL1ABC", 14200, "100"), q("G4XYZ", 14210, "KW", 1),
           q("DL1ABC", 14250, "100", 2),           # dupe
           q("DL1ABC", 21250, "100", 3),           # new band -> new mult
           q("W1AW", 14220, "", 4),                # W/VE - invalid in ARRL DX
           q("KH6XX", 14230, "1K", 5)]             # Hawaii counts as DX
    eng.rescore(log)
    s = eng.score(log)
    assert s.qsos == 4 and s.dupes == 1 and s.invalid == 1
    assert s.points == 12
    assert s.mults == 4                            # DL/20, G/20, DL/15, KH6/20
    assert s.total == 48
    assert eng.validate_rcvd("100") == []
    assert eng.validate_rcvd("") != []
    assert eng.sent_exchange() == "DE"


def test_new_mult_and_dupe_check(cty, station):
    eng = ContestEngine(load_rules("ARRL-DX-SSB"), cty, station)
    log = eng.rescore([q("DL1ABC", 14200, "100")])
    assert eng.is_dupe("dl1abc", "20m", "SSB", log)
    assert not eng.is_dupe("DL1ABC", "15m", "SSB", log)
    probe = eng.annotate(q("DK2XX", 14200, "100"), log)
    assert eng.is_new_mult(probe, log) == []       # Germany already on 20m
    probe = eng.annotate(q("JA1XX", 14200, "100"), log)
    assert eng.is_new_mult(probe, log) == ["DXCC"]


def test_cqww_points(cty, station):
    eng = ContestEngine(load_rules("CQ-WW-SSB"), cty, station)
    log = [QSO(call="DL1ABC", freq_khz=14200, mode="SSB", exch_rcvd="14", time_utc=T0),
           QSO(call="XE1AA", freq_khz=14200, mode="SSB", exch_rcvd="6", time_utc=T0 + timedelta(minutes=1)),
           QSO(call="W1AW", freq_khz=14200, mode="SSB", exch_rcvd="5", time_utc=T0 + timedelta(minutes=2))]
    eng.rescore(log)
    assert [x.points for x in log] == [3, 2, 0]
    s = eng.score(log)
    assert s.mults == 6                            # 3 zones + 3 countries on 20m
    assert eng.prefill("JA1XYZ") == "25"


def test_db_journal_recovery(tmp_path, cty, station):
    log = Log(tmp_path / "c.db")
    a = log.add(q("DL1ABC", 14200, "100"))
    b = log.add(q("G4XYZ", 14210, "KW", 1))
    b.exch_rcvd = "1K"
    log.update(b)
    log.delete(a.id)
    log.add(q("JA1XYZ", 21200, "500", 2))
    assert [x.call for x in log.all()] == ["G4XYZ", "JA1XYZ"]
    log.close()
    rec = Log.recover_from_journal(tmp_path / "c.journal", tmp_path / "r.db")
    got = rec.all()
    assert [x.call for x in got] == ["G4XYZ", "JA1XYZ"]
    assert got[0].exch_rcvd == "1K"


def test_exports(tmp_path, cty, station):
    eng = ContestEngine(load_rules("ARRL-DX-SSB"), cty, station)
    log = eng.rescore([q("DL1ABC", 14200, "100"), q("KH6XX", 21300.5, "1K", 1)])
    n = export_adif(log, tmp_path / "x.adi")
    assert n == 2
    back = import_adif(tmp_path / "x.adi")
    assert [x.call for x in back] == ["DL1ABC", "KH6XX"]
    assert back[1].freq_khz == pytest.approx(21300.5)
    assert back[0].time_utc == T0
    export_cabrillo(log, eng, tmp_path / "x.log")
    text = (tmp_path / "x.log").read_text()
    assert "CONTEST: ARRL-DX-SSB" in text
    assert "CLAIMED-SCORE: 12" in text
    assert "QSO: 14200 PH 2027-03-06 0001 N3TTT" in text
    assert text.strip().endswith("END-OF-LOG:")
