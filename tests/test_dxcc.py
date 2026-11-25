"""DXCC entities: LoTW's DXCC number beats cty.dat, WAE countries fold for DXCC,
and LoTW's date-only DXCC report repairs the log instead of adding copies."""
from datetime import datetime, timezone

from tttlog.contests.engine import ContestEngine, Station, load_rules
from tttlog.core import dxcc
from tttlog.core.cty import CtyDat
from tttlog.core.db import Log
from tttlog.core.models import QSO
from tttlog.export.adif import filter_import, parse_adif, qso_to_adif, repair

CTY = """\
United States:            05:  08:  NA:   37.53:    91.67:     5.0:  K:
    K,N,W;
American Samoa:           32:  62:  OC:  -14.32:   170.78:    11.0:  KH8:
    KH8;
Italy:                    15:  28:  EU:   42.82:   -12.58:    -1.0:  I:
    I;
Sicily:                   15:  28:  EU:   37.50:   -14.00:    -1.0:  *IT9:
    IT9;
"""

T = datetime(2024, 7, 2, 12, 30, tzinfo=timezone.utc)


def _cty(tmp_path):
    p = tmp_path / "cty.dat"
    p.write_text(CTY)
    return CtyDat(p)


def test_table_covers_lotw_numbers():
    assert dxcc.NAME[9] == "American Samoa"
    assert dxcc.NAME[291] == "United States"
    assert dxcc.WAE["Sicily"] == "Italy"


def test_dxcc_number_beats_cty(tmp_path):
    eng = ContestEngine(load_rules("GENERAL"), _cty(tmp_path), Station(call="N3TTT"))
    q = QSO(call="K8K", freq_khz=14200, mode="SSB", time_utc=T)
    assert eng.annotate(q, []).country == "United States"
    q.dxcc = 9
    assert eng.annotate(q, []).country == "American Samoa"
    assert q.cq_zone == 32


def test_wae_counts_once_for_dxcc_but_separately_for_cq(tmp_path):
    cty = _cty(tmp_path)
    log = [QSO(call="I2FAK", freq_khz=14200, mode="SSB", time_utc=T, exch_rcvd="100"),
           QSO(call="IT9FXY", freq_khz=14201, mode="SSB", time_utc=T, exch_rcvd="100")]
    arrl = ContestEngine(load_rules("ARRL-DX-SSB"), cty, Station(call="N3TTT", state="DE"))
    s = arrl.score(arrl.rescore(log))
    assert len(s.mult_sets["DXCC"]) == 1
    cq = ContestEngine(load_rules("CQ-WW-SSB"), cty, Station(call="N3TTT"))
    s = cq.score(cq.rescore([QSO(**{**x.__dict__, "exch_rcvd": "15"}) for x in log]))
    assert len(s.mult_sets["Countries"]) == 2


def test_adif_dxcc_round_trip(tmp_path):
    q = parse_adif("<CALL:3>K8K<QSO_DATE:8>20240702<BAND:3>20M<MODE:3>SSB<DXCC:1>9<EOR>")[0]
    assert q.dxcc == 9 and q.band == "20m" and getattr(q, "no_time", False)
    assert "<DXCC:1>9" in qso_to_adif(q)
    db = Log(tmp_path / "t.db")
    db.add(q)
    assert db.all()[0].dxcc == 9


def test_lotw_date_only_report_repairs_log():
    logged = QSO(call="K8K", freq_khz=14200, mode="SSB", time_utc=T)        # real QSO, no DXCC
    bandless = QSO(call="N5J", freq_khz=0, mode="SSB",                        # old date-only import
                   time_utc=datetime(2024, 8, 8, tzinfo=timezone.utc))
    report = parse_adif(
        "<CALL:3>K8K<QSO_DATE:8>20240702<BAND:3>20M<MODE:3>SSB<DXCC:1>9<EOR>"
        "<CALL:3>N5J<QSO_DATE:8>20240808<BAND:3>40M<MODE:3>SSB<DXCC:3>197<EOR>"
        "<CALL:3>K8K<QSO_DATE:8>20240702<BAND:3>20M<MODE:3>SSB<DXCC:1>9<EOR>")
    keep, n_same, _, reps = filter_import(report, [logged, bandless])
    assert keep == [] and n_same == 1 and len(reps) == 2
    for old, new in reps:
        assert repair(old, new)
    assert logged.dxcc == 9 and logged.freq_khz == 14200
    assert bandless.band == "40m" and bandless.dxcc == 197
