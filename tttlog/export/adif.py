"""ADIF 3.1 export / import."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ..core import dxcc as dxcc_table
from ..core.models import QSO, band_from_khz, band_start_khz

ADIF_MODE = {"USB": ("SSB", "USB"), "LSB": ("SSB", "LSB")}


def _f(tag: str, val) -> str:
    val = "" if val is None else str(val)
    return f"<{tag}:{len(val.encode('utf-8'))}>{val} " if val != "" else ""


def qso_to_adif(q: QSO) -> str:
    mode, submode = ADIF_MODE.get(q.mode.upper(), (q.mode.upper(), ""))
    t = q.time_utc
    general = q.contest_id == "GENERAL"      # notes, not a contest exchange
    rec = (
        _f("CALL", q.call.upper())
        + _f("QSO_DATE", t.strftime("%Y%m%d"))
        + _f("TIME_ON", t.strftime("%H%M%S"))
        + _f("BAND", q.band)
        + _f("FREQ", f"{q.freq_khz / 1000:.6f}".rstrip("0").rstrip("."))
        + _f("MODE", mode)
        + _f("SUBMODE", submode)
        + _f("RST_SENT", q.rst_sent)
        + _f("RST_RCVD", q.rst_rcvd)
        + _f("STX_STRING", "" if general else q.exch_sent)
        + _f("SRX_STRING", "" if general else q.exch_rcvd)
        + _f("COMMENT", q.exch_rcvd if general else "")
        + _f("STATION_CALLSIGN", q.station_call)
        + _f("OPERATOR", q.operator)
        + _f("CONTEST_ID", "" if general else q.contest_id)
        + _f("COUNTRY", q.country if q.country != "?" else "")
        + _f("DXCC", q.dxcc or dxcc_table.NUMBER.get(dxcc_table.WAE.get(q.country, q.country), ""))
        + _f("CQZ", q.cq_zone)
    )
    return rec + "<EOR>\n"


def export_adif(qsos: list[QSO], path: str | Path, program: str = "tttlog") -> int:
    hdr = (f"ADIF export from {program}\n"
           + _f("ADIF_VER", "3.1.4") + _f("PROGRAMID", program)
           + _f("CREATED_TIMESTAMP", datetime.now(timezone.utc).strftime("%Y%m%d %H%M%S"))
           + "<EOH>\n")
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(hdr)
        for q in qsos:
            fh.write(qso_to_adif(q))
            n += 1
    return n


_TAG = re.compile(r"<(\w+):(\d+)(?::\w)?>", re.I)


def import_adif(path: str | Path, general: bool = False) -> list[QSO]:
    """Read QSOs. general=True fills the notes from NAME / QTH / COMMENT."""
    return parse_adif(Path(path).read_text(encoding="utf-8", errors="replace"), general)


def parse_adif(text: str, general: bool = False) -> list[QSO]:
    """QSOs from ADIF text (a file, or one record from WSJT-X)."""
    eoh = re.search(r"<eoh>", text, re.I)
    body = text[eoh.end():] if eoh else text
    out = []
    for rec in re.split(r"<eor>", body, flags=re.I):
        fields, pos = {}, 0
        while (m := _TAG.search(rec, pos)):
            n = int(m.group(2))
            fields[m.group(1).upper()] = rec[m.end():m.end() + n]
            pos = m.end() + n
        if "CALL" not in fields:
            continue
        d, t = fields.get("QSO_DATE", "19700101"), fields.get("TIME_ON", "0000").ljust(6, "0")
        when = datetime.strptime(d + t[:6], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        mode = fields.get("SUBMODE") or fields.get("MODE", "SSB")
        if mode.upper() in ("USB", "LSB"):
            mode = "SSB"
        rcvd = fields.get("SRX_STRING", "")
        if general and not rcvd:
            rcvd = " ".join(fields[k] for k in ("GRIDSQUARE", "NAME", "QTH", "COMMENT") if fields.get(k))
        try:
            khz = float(fields.get("FREQ", "0") or 0) * 1000
        except ValueError:
            khz = 0.0
        if band_from_khz(khz) is None and fields.get("BAND"):
            # LoTW and others often give only BAND: put it on that band
            khz = band_start_khz(fields["BAND"].strip().lower(), mode) or khz
        try:
            ent = int(fields.get("DXCC", "") or 0) or None
        except ValueError:
            ent = None
        out.append(QSO(
            call=fields["CALL"], freq_khz=khz, dxcc=ent,
            mode=mode, rst_sent=fields.get("RST_SENT", ""), rst_rcvd=fields.get("RST_RCVD", ""),
            exch_sent=fields.get("STX_STRING", ""), exch_rcvd=rcvd,
            time_utc=when, station_call=fields.get("STATION_CALLSIGN", ""),
            operator=fields.get("OPERATOR", ""), contest_id=fields.get("CONTEST_ID", "")))
        if not fields.get("TIME_ON"):
            out[-1].no_time = True          # LoTW's DXCC report gives only the date
    return out


SAME_QSO_SECS = 120          # an imported QSO this close in time to one in the log is the same QSO


def _date_only(q: QSO) -> bool:
    """No real time: read from a file without TIME_ON (or imported that way before: no band, 00:00:00)."""
    return getattr(q, "no_time", False) or (q.band is None and q.time_utc.strftime("%H%M%S") == "000000")


def _same_qso(a: QSO, b: QSO) -> bool:
    """The same contact: same call and mode, and the same time (2 minutes), or the same
    UTC date when either side has no time. Bands must agree unless one side has none."""
    from ..core.models import mode_group
    if a.call.upper() != b.call.upper() or mode_group(a.mode) != mode_group(b.mode):
        return False
    if a.band and b.band and a.band != b.band:
        return False
    if _date_only(a) or _date_only(b):
        return a.time_utc.date() == b.time_utc.date()
    return abs((a.time_utc - b.time_utc).total_seconds()) <= SAME_QSO_SECS


def repair(old: QSO, new: QSO) -> bool:
    """Copy what the file knows and the log copy doesn't (band, DXCC). True if anything changed."""
    changed = False
    if old.band is None and new.band is not None:
        old.freq_khz = new.freq_khz
        changed = True
    if new.dxcc and old.dxcc != new.dxcc:
        old.dxcc = new.dxcc
        changed = True
    return changed


def filter_import(new: list[QSO], existing: list[QSO], engine=None, skip_same: bool = True,
                  skip_dupes: bool = False) -> tuple[list[QSO], int, int, list]:
    """Choose what to import. Returns (to import, skipped as already in the log,
    skipped as contest dupes, repairs). Repeats inside the file count too.

    repairs: (QSO in the log, the same QSO from the file) where the file knows more:
    the band (logs imported before band-only records were understood) or the DXCC
    entity (LoTW). Apply them with repair(old, new).

    skip_same:  the same contact is already in the log (see _same_qso): re-importing a
                file, a file that overlaps the log, or LoTW's date-only DXCC report.
    skip_dupes: the call was already worked where the contest's dupe rule says it
                only counts once (e.g. once per band).
    """
    by_call: dict[str, list] = {}
    dupe_keys: set = set()

    def remember(q: QSO):
        by_call.setdefault(q.call.upper(), []).append(q)
        if engine is not None and not q.is_dupe:
            k = engine._dupe_key(q)
            if k is not None:
                dupe_keys.add(k)

    for q in existing:
        remember(q)
    in_log = {id(q) for q in existing}
    keep, n_same, n_dupe, repairs = [], 0, 0, []
    for q in sorted(new, key=lambda x: x.time_utc):
        cands = [o for o in by_call.get(q.call.upper(), []) if _same_qso(o, q)]
        # prefer the copy that needs the repair, then the closest in time
        cands.sort(key=lambda o: (o.band is not None, abs((o.time_utc - q.time_utc).total_seconds())))
        old = cands[0] if cands else None
        if old is not None and id(old) in in_log and \
                ((old.band is None and q.band is not None) or (q.dxcc and old.dxcc != q.dxcc)):
            if not any(o is old for o, _ in repairs):
                repairs.append((old, q))
                continue
        if skip_same and old is not None:
            n_same += 1
            continue
        if skip_dupes and engine is not None:
            k = engine._dupe_key(q)
            if k is not None and k in dupe_keys:
                n_dupe += 1
                continue
        keep.append(q)
        remember(q)
    return keep, n_same, n_dupe, repairs
