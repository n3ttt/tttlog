"""Score pane laid out like N1MM / Win-Test: bands, a column per mult kind, totals,
the score, and what a mult is worth in QSOs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tttlog.contests.engine import ContestEngine, Station, load_rules
from tttlog.core.cty import CtyDat
from tttlog.core.models import QSO
from tttlog.ui.score_pane import score_text, short_label

FIX = Path(__file__).parent / "fixtures" / "cty_sample.dat"
T0 = datetime(2027, 11, 27, 0, 0, tzinfo=timezone.utc)


def _log(eng, qsos):
    return eng.rescore([QSO(call=c, freq_khz=f, mode="SSB", exch_rcvd=z, time_utc=T0 + timedelta(minutes=i))
                        for i, (c, f, z) in enumerate(qsos)])


def test_cqww_score_like_n1mm():
    eng = ContestEngine(load_rules("CQ-WW-SSB"), CtyDat(FIX), Station(call="N3TTT", cq_zone=5))
    log = _log(eng, [("DL1ABC", 14200, "14"), ("JA1AA", 14210, "25"), ("DL2XYZ", 14220, "14"),
                     ("DL1ABC", 21300, "14"), ("DL1ABC", 14200, "14")])       # last one: a dupe
    s = eng.score(log)
    table, score, worth = score_text(eng, s)
    lines = table.split("\n")
    assert lines[0].split() == ["Band", "QSOs", "Pts", "ZN", "Cty"]
    assert lines[1].split()[:2] == ["20", "3"] and lines[2].split()[:2] == ["15", "1"]
    assert lines[-1].split()[0] == "Total" and lines[-1].split()[1] == "4"
    assert lines[1].split()[3:] == ["2", "2"]                  # 20m: zones 14 + 25, Germany + Japan
    assert lines[-1].split()[3:] == ["3", "3"]                 # totals add 15m's zone and country
    assert score == f"Score: {s.total:,}" and s.total == s.points * 6
    assert worth == f"1 Mult = {4 / 6:.1f} Q's"
    assert not any(l.startswith("40") for l in lines)          # bands with no QSOs left out


def test_general_log_shows_qsos_and_dxcc():
    eng = ContestEngine(load_rules("GENERAL"), CtyDat(FIX), Station(call="N3TTT", cq_zone=5))
    s = eng.score(_log(eng, [("DL1ABC", 14200, ""), ("JA1AA", 7150, "")]))
    table, score, worth = score_text(eng, s)
    assert "Pts" not in table and score == "QSOs 2  ·  DXCC 2" and worth == ""


def test_short_labels():
    assert [short_label(x) for x in ("Zones", "Countries", "Sections", "Something")] == ["ZN", "Cty", "Sec", "Some"]
