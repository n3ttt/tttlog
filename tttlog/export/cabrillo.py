"""Cabrillo 3.0 export."""
from __future__ import annotations

from pathlib import Path

from ..contests.engine import ContestEngine
from ..core.models import CABRILLO_MODE, QSO


def qso_line(q: QSO, station_call: str, rst: bool = True) -> str:
    mode = CABRILLO_MODE.get(q.mode.upper(), "PH")
    freq = f"{int(round(q.freq_khz)):>5}"
    t = q.time_utc
    if rst:
        sent = f"{q.rst_sent:<3} {q.exch_sent:<6}"
        rcvd = f"{q.rst_rcvd:<3} {q.exch_rcvd:<6}"
    else:                                     # Sweepstakes, NAQP, CWT, Field Day: no signal report
        sent = f"{q.exch_sent:<10}"
        rcvd = f"{q.exch_rcvd:<10}"
    return (f"QSO: {freq} {mode} {t:%Y-%m-%d} {t:%H%M} "
            f"{station_call:<13} {sent} {q.call.upper():<13} {rcvd}").rstrip()


def operators(qsos: list[QSO], st) -> str:
    """Everyone who logged a QSO (multi-op), else the station's operator."""
    ops: list[str] = []
    for q in qsos:
        if q.operator and q.operator not in ops:
            ops.append(q.operator)
    return " ".join(ops) or st.operator or st.call


def export_cabrillo(qsos: list[QSO], engine: ContestEngine, path: str | Path,
                    category: dict | None = None, soapbox: str = "") -> int:
    st = engine.station
    cat = {"OPERATOR": "SINGLE-OP", "ASSISTED": "NON-ASSISTED", "BAND": "ALL",
           "MODE": "SSB", "POWER": "HIGH", "STATION": "FIXED", "TRANSMITTER": "ONE"}
    cat.update(category or {})
    score = engine.score(qsos)
    lines = [
        "START-OF-LOG: 3.0",
        f"CONTEST: {engine.rules['cabrillo_contest']}",
        f"CALLSIGN: {st.call}",
        (f"LOCATION: {st.section}" if engine.rules.get("location") == "section" and st.section
         else f"LOCATION: {st.state}" if st.state else None),
        *(f"CATEGORY-{k}: {v}" for k, v in cat.items()),
        f"CLAIMED-SCORE: {score.total}",
        f"CLUB: {st.club}" if st.club else None,
        f"OPERATORS: {operators(qsos, st)}",
        f"NAME: {st.name}" if st.name else None,
        *(f"ADDRESS: {a}" for a in st.address),
        f"EMAIL: {st.email}" if st.email else None,
        "CREATED-BY: tttlog",
        f"SOAPBOX: {soapbox}" if soapbox else None,
    ]
    n = 0
    for q in qsos:
        lines.append(qso_line(q, st.call, engine.uses_rst))   # dupes included; log checkers zero them
        n += 1
    lines.append("END-OF-LOG:")
    Path(path).write_text("\n".join(l for l in lines if l is not None) + "\n", encoding="utf-8")
    return n
