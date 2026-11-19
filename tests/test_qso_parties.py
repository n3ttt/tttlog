"""State QSO parties: PA, NEQP, Delaware, Maryland-DC, from inside and outside the state."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tttlog.contests.engine import ContestEngine, Station, load_rules
from tttlog.core.cty import CtyDat
from tttlog.core.locations import LISTS
from tttlog.core.models import QSO

FIX = Path(__file__).parent / "fixtures" / "cty_sample.dat"
T0 = datetime(2027, 10, 9, 16, 0, tzinfo=timezone.utc)


def eng(cid, state, county="", section=""):
    return ContestEngine(load_rules(cid), CtyDat(FIX),
                         Station(call="N3TTT", state=state, county=county, section=section))


def log(e, rows):
    out = []
    for i, (call, khz, mode, exch) in enumerate(rows):
        q = QSO(call=call, freq_khz=khz, mode=mode, exch_rcvd=exch, time_utc=T0 + timedelta(minutes=i))
        q.exch_sent = e.sent_exchange(out, for_log=True)
        out.append(q)
    return e.rescore(out)


def test_county_lists():
    assert len(LISTS["pa_counties"]) == 67 and len(set(LISTS["pa_counties"])) == 67
    assert len(LISTS["neqp_counties"]) == 68 and "NHHIL" in LISTS["neqp_counties"]
    assert LISTS["de_counties"] == ["NDE", "KDE", "SDE"]
    assert len(LISTS["mdc_counties"]) == 25 and {"BAL", "WDC"} <= set(LISTS["mdc_counties"])


def test_pa_from_outside():
    e = eng("PA-QP", "DE", section="DE")
    assert e.in_state is False and e.sent_exchange([]) == "1 DE"
    assert e.validate_rcvd("12 ALL", "W3XX") == [] and e.validate_rcvd("12 XXX", "W3XX") == ["bad CNTY: XXX"]
    assert e.validate_rcvd("12 CAR/LEH", "W3XX") == []                      # county line
    l = log(e, [("W3AA", 14030, "CW", "1 ALL"), ("W3AA", 14250, "SSB", "2 ALL"),
                ("W3AA", 14031, "CW", "3 ALL"),                             # dupe: same band, mode, county
                ("W3MOB", 7030, "CW", "4 YOR"), ("W3MOB", 7031, "CW", "9 ADA"),  # a mobile, new county
                ("W3CL", 3550, "CW", "5 CAR/LEH"),                          # county line: 2 counties
                ("K1ABC", 14035, "CW", "6 CT")])                            # not a PA station: no credit
    s = e.score(l)
    assert s.dupes == 1 and s.invalid == 1
    assert s.points == 2 + 1 + 2 + 2 + 2 * 2                                # CW 2, phone 1; county line x2
    assert s.mult_sets["Counties"] == {("ALL",), ("YOR",), ("ADA",), ("CAR",), ("LEH",)}


def test_pa_from_inside():
    e = eng("PA-QP", "PA", county="LAN")
    assert e.in_state and e.sent_exchange([]) == "1 LAN"
    l = log(e, [("W3AA", 14030, "CW", "1 ALL"), ("K1ABC", 14035, "CW", "2 CT"), ("DL1ABC", 14040, "CW", "3 DX"),
                ("JA1AA", 14045, "CW", "4 DX")])
    s = e.score(l)
    assert s.mult_sets == {"Counties": {("ALL",)}, "Sections": {("CT",)}, "DX": {("DX",)}}   # DX: one mult
    assert s.total == 8 * 3


def test_neqp():
    out = eng("NEQP", "DE")
    assert out.sent_exchange([]) == "DE" and out.uses_rst
    l = log(out, [("W1AA", 14040, "CW", "NHHIL"), ("W1BB", 14280, "SSB", "CTCAP"), ("K3XX", 14045, "CW", "PA")])
    s = out.score(l)
    assert s.invalid == 1 and s.points == 2 + 1 and s.mults == 2
    ins = eng("NEQP", "NH", county="NHHIL")
    assert ins.in_state and ins.sent_exchange([]) == "NHHIL"
    l = log(ins, [("W1AA", 14040, "CW", "MAMID"), ("K3XX", 14045, "CW", "PA"), ("W1CC", 7040, "CW", "MABAR"),
                  ("DL1ABC", 14050, "CW", "DX")])
    s = ins.score(l)
    assert s.mult_sets["States/Prov"] == {("MA",), ("PA",)}                 # MAMID and MABAR both count MA
    assert s.mult_sets["DXCC"] == {("Fed. Rep. of Germany",)}


def test_delaware():
    ins = eng("DE-QP", "DE", county="NDE")
    assert ins.sent_exchange([]) == "NDE"
    l = log(ins, [("K3XX", 14040, "CW", "PA"), ("K3XX", 7040, "CW", "PA"), ("W3DE", 14250, "SSB", "KDE"),
                  ("DL1ABC", 14074, "FT8", "DX")])
    s = ins.score(l)
    assert s.points == 2 + 2 + 1 + 2
    assert s.mult_sets["States/Prov"] == {("20m", "PA"), ("40m", "PA")}    # per band; DE stations: points only
    out = eng("DE-QP", "PA")
    l = log(out, [("W3DE", 14040, "CW", "NDE"), ("W3DE", 14250, "SSB", "NDE"), ("W3DF", 14045, "CW", "SDE")])
    s = out.score(l)
    assert s.points == 20 + 10 + 20 and s.mult_sets["Counties"] == {("20m", "NDE"), ("20m", "SDE")}


def test_maryland_dc():
    ins = eng("MDC-QP", "MD", county="ANA")
    assert ins.sent_exchange([]) == "ANA" and not ins.uses_rst
    l = log(ins, [("W3AA", 14040, "CW", "BAL"), ("K3XX", 14250, "SSB", "PA"), ("K3YY", 7250, "SSB", "MD"),
                  ("VE3XX", 14045, "CW", "ON"), ("DL1ABC", 14050, "CW", "DL")])
    s = ins.score(l)
    assert s.points == 3 + 1 + 1 + 3 + 3
    assert s.mult_sets["Counties"] == {("BAL",)} and s.mult_sets["States"] == {("PA",)}   # MD isn't a state mult
    assert s.mult_sets["Provinces"] == {("ON",)} and s.mult_sets["DXCC"] == {("Fed. Rep. of Germany",)}
    out = eng("MDC-QP", "DE")
    assert out.sent_exchange([]) == "DE"
    s = out.score(log(out, [("W3AA", 14040, "CW", "WDC"), ("W3AB", 14041, "CW", "XYZ")]))
    assert s.invalid == 1 and s.mult_sets["Counties"] == {("WDC",)}
