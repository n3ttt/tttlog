from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tttlog.contests.engine import ContestEngine, Station, load_rules
from tttlog.core import rates
from tttlog.core.cluster import (LOGIN_RE, Spot, SpotList, guess_mode, parse_spot,
                                 strip_telnet)
from tttlog.core.cty import CtyDat
from tttlog.core.models import QSO

FIX = Path(__file__).parent / "fixtures" / "cty_sample.dat"
T0 = datetime(2027, 3, 6, 0, 0, tzinfo=timezone.utc)


def q(call, khz=14200.0, minutes=0.0, dupe=False):
    return QSO(call=call, freq_khz=khz, mode="SSB", exch_rcvd="100",
               time_utc=T0 + timedelta(minutes=minutes), is_dupe=dupe)


@pytest.fixture
def engine():
    return ContestEngine(load_rules("ARRL-DX-SSB"), CtyDat(FIX),
                         Station(call="N3TTT", state="DE", cq_zone=5))


# ------------------------------------------------------------------ rates
def test_rate_last_n():
    log = [q(f"DL{i}AA", minutes=i * 3) for i in range(10)]     # 10 QSOs, 0..27 min
    now = T0 + timedelta(minutes=30)
    assert rates.rate_last_n(log, 10, now) == pytest.approx(20.0)  # 10 in 30 min
    assert rates.rate_last_n(log, 100, now) == 0                  # not enough QSOs yet
    # dupes don't count
    assert rates.rate_last_n(log + [q("X", minutes=29, dupe=True)], 10, now) == pytest.approx(20.0)


def test_rate_floor_on_burst():
    log = [q(f"DL{i}AA", minutes=0) for i in range(10)]
    assert rates.rate_last_n(log, 10, T0) == pytest.approx(600.0)  # 10 per 1-minute floor


def test_counts_and_best60():
    log = [q(f"G{i}A", minutes=m) for i, m in enumerate([0, 5, 10, 50, 55, 70, 125])]
    now = T0 + timedelta(minutes=130)
    assert rates.count_since(log, 60, now) == 1                   # only 125
    assert rates.count_since(log, 15, now) == 1
    assert rates.best_60(log) == 5                                # 0..55


def test_hourly_with_mults(engine):
    log = [q("DL1A", 14200, 5), q("DL2B", 14200, 10), q("G4X", 21300, 20),
           q("DL3C", 21300, 70), q("W1AW", 14200, 75)]            # W1AW is invalid in ARRL DX
    engine.rescore(log)
    rows = rates.hourly(log, mult_keys=engine.mult_values, is_valid=engine.is_valid)
    assert [r.hour.hour for r in rows] == [0, 1]
    assert rows[0].qsos == 3 and rows[0].by_band == {"20m": 2, "15m": 1} and rows[0].mults == 2
    assert rows[1].qsos == 1 and rows[1].mults == 1               # DL on 15m is a new band-mult


# ------------------------------------------------------------------ cluster parsing
NOW = datetime(2027, 3, 6, 12, 40, tzinfo=timezone.utc)


@pytest.mark.parametrize("line,call,khz,spotter,mode,hhmm", [
    ("DX de W3LPL:     14205.0  DL1ABC       CQ up 1                        1234Z", "DL1ABC", 14205.0, "W3LPL", "SSB", "1234"),
    ("DX de K1TTT-#:   21025.1  JA1XYZ       CW 24 dB 28 WPM CQ             1238Z", "JA1XYZ", 21025.1, "K1TTT", "CW", "1238"),
    ("DX de N3TTT:      7180.0  G4XYZ                                        1239Z FN20", "G4XYZ", 7180.0, "N3TTT", "SSB", "1239"),
    ("DX de KB3Z:      14074.0  EA8ZZ        FT8 -12dB                      1240Z", "EA8ZZ", 14074.0, "KB3Z", "DIGI", "1240"),
    ("DX de W1AW:  3790.0 ZS6ABC", "ZS6ABC", 3790.0, "W1AW", "SSB", "1240"),
])
def test_parse_spot(line, call, khz, spotter, mode, hhmm):
    s = parse_spot(line, NOW)
    assert (s.call, s.freq_khz, s.spotter, s.mode, s.time_utc.strftime("%H%M")) == \
        (call, khz, spotter, mode, hhmm)


def test_parse_spot_rejects_other_lines():
    assert parse_spot("W3LPL de N3TTT 6-Mar-2027 1240Z dxspider >", NOW) is None
    assert parse_spot("WWV de VE7CC <18>:   SFI=150, A=5, K=1", NOW) is None


def test_spot_time_before_midnight():
    s = parse_spot("DX de VE3ABC:  28450.0  PY2AA  loud  2359Z", NOW.replace(hour=0, minute=2))
    assert s.time_utc.day == 5 and s.time_utc.hour == 23


def test_strip_telnet():
    raw = bytes([255, 251, 1]) + b"login: " + bytes([255, 255]) + b"x" + bytes([255, 250, 24, 1, 255, 240]) + b"ok"
    assert strip_telnet(raw) == b"login: \xffxok"


def test_guess_mode_and_login_prompt():
    assert guess_mode(14025) == "CW" and guess_mode(14250) == "SSB"
    assert guess_mode(14250, "CW skimmer") == "CW" and guess_mode(7074, "FT8") == "DIGI"
    for p in ["login: ", "Please enter your call: ", "Call:", "callsign:"]:
        assert LOGIN_RE.search(p.strip())
    assert not LOGIN_RE.search("DX de W3LPL: 14025.0 DL1ABC CQ 1234Z")


# ------------------------------------------------------------------ spot evaluation
def test_spotlist_evaluate(engine):
    log = engine.rescore([q("DL1ABC", 14200, 0), q("G4XYZ", 14210, 1)])
    sl = SpotList(max_age_min=30)
    for line in [
        "DX de W3LPL:  14250.0  DL1ABC   1239Z",   # worked on 20m -> DUPE
        "DX de W3LPL:  14260.0  DL2ZZ    1239Z",   # DL already a 20m mult -> Q
        "DX de W3LPL:  14270.0  JA1AA    1239Z",   # new 20m mult
        "DX de W3LPL:  21300.0  DL1ABC   1239Z",   # DL1ABC on 15m -> new band-mult
        "DX de W3LPL:  14280.0  W1AW     1239Z",   # US station: not valid in ARRL DX
        "DX de W3LPL:  14025.0  PY2AA    1239Z",   # CW segment in an SSB contest
        "DX de W3LPL:  18130.0  XE1AA    1239Z",   # 17m not a contest band
    ]:
        sl.add(parse_spot(line, NOW))
    sl.evaluate(engine, log)
    got = {(s.call, s.band): s.status for s in sl.spots()}
    assert got == {("DL1ABC", "20m"): "DUPE", ("DL2ZZ", "20m"): "Q", ("JA1AA", "20m"): "MULT",
                   ("DL1ABC", "15m"): "MULT", ("W1AW", "20m"): "INVALID",
                   ("PY2AA", "20m"): "INVALID", ("XE1AA", "17m"): "INVALID"}
    assert next(s for s in sl.spots() if s.call == "JA1AA").mults == ["DXCC"]

    # work JA1AA and re-evaluate: the spot flips to DUPE
    log = engine.rescore(log + [q("JA1AA", 14270, 2)])
    sl.evaluate(engine, log)
    assert next(s for s in sl.spots() if s.call == "JA1AA").status == "DUPE"


def test_spotlist_keeps_latest_and_ages_out():
    sl = SpotList(max_age_min=30)
    sl.add(Spot("DL1A", 14200, "W3LPL", time_utc=NOW - timedelta(minutes=40)))
    sl.add(Spot("DL1A", 14205, "K3LR", time_utc=NOW - timedelta(minutes=5)))   # replaces
    sl.add(Spot("G4X", 14210, "K3LR", time_utc=NOW - timedelta(minutes=45)))
    assert len(sl) == 2
    sl.prune(NOW)
    assert [(s.call, s.spotter) for s in sl.spots()] == [("DL1A", "K3LR")]


# ------------------------------------------------------------------ needed grid
def test_need_grid_states(engine):
    from tttlog.core import needed
    log = engine.rescore([q("DL1ABC", 14200, 0), q("G4XYZ", 21300, 1)])
    sl = SpotList()
    for line in ["DX de W3LPL:  14260.0  DL2ZZ    1239Z",     # Germany 20m: worked, spotted again
                 "DX de W3LPL:  14270.0  JA1AA    1239Z",     # Japan 20m: needed + spotted
                 "DX de W3LPL:  14025.0  PY2AA    1239Z"]:    # CW in SSB contest: not "spotted"
        sl.add(parse_spot(line, NOW))
    sl.evaluate(engine, log)
    mdef = needed.mult_defs(engine)[0]
    cols, rows = needed.need_grid(engine, mdef, log, sl.spots())
    assert cols == ["160m", "80m", "40m", "20m", "15m", "10m"]
    by = {r.value: r for r in rows}
    assert "United States" not in by and "Canada" not in by          # excluded in ARRL DX
    assert by["Fed. Rep. of Germany"].cells["20m"] == "worked_spotted"
    assert by["Fed. Rep. of Germany"].cells["15m"] == "needed"
    assert by["England"].cells["15m"] == "worked"
    assert by["Japan"].cells["20m"] == "needed_spotted"
    assert by["Japan"].spots["20m"][0].call == "JA1AA"
    assert by["Brazil"].cells["20m"] == "needed"
    c = needed.counts(rows)
    assert c["worked"] + c["worked_spotted"] == 2 and c["needed_spotted"] == 1


def test_need_grid_cqww_zones():
    from tttlog.core import needed
    eng = ContestEngine(load_rules("CQ-WW-SSB"), CtyDat(FIX), Station(call="N3TTT", cq_zone=5))
    log = eng.rescore([QSO(call="DL1ABC", freq_khz=14200, mode="SSB", exch_rcvd="14", time_utc=T0)])
    zones = next(m for m in needed.mult_defs(eng) if m["type"] == "cq_zone")
    cols, rows = needed.need_grid(eng, zones, log, [])
    assert len(rows) == 40
    assert rows[13].cells["20m"] == "worked" and rows[13].cells["40m"] == "needed"
    countries = next(m for m in needed.mult_defs(eng) if m["type"] == "dxcc")
    _, rows = needed.need_grid(eng, countries, log, [])
    assert any(r.value == "United States" for r in rows)              # own country counts in CQWW
