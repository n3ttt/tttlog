"""Import ADIF: skip QSOs already in the log, and (optionally) contest dupes."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timedelta, timezone

from tttlog.contests.engine import ContestEngine, Station, load_rules
from tttlog.core.cty import CtyDat
from tttlog.core.models import QSO
from tttlog.export.adif import export_adif, filter_import

from tests.test_rig import _pump, app, win  # noqa: F401  (fixtures)

T0 = datetime(2027, 3, 6, 0, 0, tzinfo=timezone.utc)


def q(call, khz, minutes, mode="SSB", exch="100"):
    return QSO(call=call, freq_khz=khz, mode=mode, exch_rcvd=exch, time_utc=T0 + timedelta(minutes=minutes))


def engine():
    from pathlib import Path
    cty = CtyDat(Path(__file__).parent / "fixtures" / "cty_sample.dat")
    return ContestEngine(load_rules("ARRL-DX-SSB"), cty, Station(call="N3TTT", state="DE"))


def test_skip_same_qsos():
    log = [q("DL1ABC", 14200, 0), q("G4XYZ", 14210, 5)]
    new = [q("DL1ABC", 14205, 1),          # same QSO (1 min off, same band/mode)
           q("DL1ABC", 21200, 1),          # other band: new
           q("G4XYZ", 14210, 30),          # same band, 25 min later: a new QSO (contest dupe)
           q("JA1AA", 14220, 40), q("JA1AA", 14220, 40)]    # twice in the file
    keep, same, dupe, _ = filter_import(new, log, engine(), skip_same=True, skip_dupes=False)
    assert [(x.call, x.band) for x in keep] == [("DL1ABC", "15m"), ("G4XYZ", "20m"), ("JA1AA", "20m")]
    assert (same, dupe) == (2, 0)
    keep, same, dupe, _ = filter_import(new, log, engine(), skip_same=False, skip_dupes=False)
    assert len(keep) == 5 and same == dupe == 0                    # both off: everything


def test_skip_contest_dupes():
    log = [q("DL1ABC", 14200, 0)]
    new = [q("DL1ABC", 14200, 60), q("DL1ABC", 21200, 61), q("ZS6XX", 7100, 62), q("ZS6XX", 7150, 90)]
    keep, same, dupe, _ = filter_import(new, log, engine(), skip_same=True, skip_dupes=True)
    assert [(x.call, x.band) for x in keep] == [("DL1ABC", "15m"), ("ZS6XX", "40m")]
    assert (same, dupe) == (0, 2)


def test_import_menu(app, win, tmp_path, monkeypatch):  # noqa: F811
    import tttlog.ui.main_window as mw
    from tttlog.ui import dialogs
    from PySide6.QtWidgets import QFileDialog
    f = tmp_path / "other.adi"
    export_adif([q("DL1ABC", 14200, 0, exch=""), q("DL1ABC", 14200, 90, exch=""),
                 q("JA1AA", 21200, 5, exch="")], f)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(f), "")))
    choice = {"same": True, "dupes": False}

    class Dlg(dialogs.ImportDialog):
        def exec(self):
            self.same.setChecked(choice["same"]); self.dupes.setChecked(choice["dupes"])
            return True
    monkeypatch.setattr(dialogs, "ImportDialog", Dlg)

    win.import_adif()
    assert len(win.qsos) == 3 and "Imported 3 QSOs" in win.banner_lbl.text()
    win.import_adif()                                              # the same file again
    assert len(win.qsos) == 3 and "skipped 3 already in the log" in win.banner_lbl.text()
    choice["same"] = False
    win.import_adif()                                              # unticked: imports them again
    assert len(win.qsos) == 6
