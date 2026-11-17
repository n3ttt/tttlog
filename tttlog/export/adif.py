"""ADIF 3.1 export / import."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ..core.models import QSO

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
    text = Path(path).read_text(encoding="utf-8", errors="replace")
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
            rcvd = " ".join(fields[k] for k in ("NAME", "QTH", "COMMENT") if fields.get(k))
        out.append(QSO(
            call=fields["CALL"], freq_khz=float(fields.get("FREQ", "0") or 0) * 1000,
            mode=mode, rst_sent=fields.get("RST_SENT", ""), rst_rcvd=fields.get("RST_RCVD", ""),
            exch_sent=fields.get("STX_STRING", ""), exch_rcvd=rcvd,
            time_utc=when, station_call=fields.get("STATION_CALLSIGN", ""),
            operator=fields.get("OPERATOR", ""), contest_id=fields.get("CONTEST_ID", "")))
    return out
