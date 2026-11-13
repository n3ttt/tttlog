"""Cabrillo 3.0 export."""
from __future__ import annotations

from pathlib import Path

from ..contests.engine import ContestEngine
from ..core.models import CABRILLO_MODE, QSO


def qso_line(q: QSO, station_call: str) -> str:
    mode = CABRILLO_MODE.get(q.mode.upper(), "PH")
    freq = f"{int(round(q.freq_khz)):>5}"
    t = q.time_utc
    sent = f"{q.rst_sent:<3} {q.exch_sent:<6}"
    rcvd = f"{q.rst_rcvd:<3} {q.exch_rcvd:<6}"
    return (f"QSO: {freq} {mode} {t:%Y-%m-%d} {t:%H%M} "
            f"{station_call:<13} {sent} {q.call.upper():<13} {rcvd}").rstrip()


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
        f"LOCATION: {st.state}" if st.state else None,
        *(f"CATEGORY-{k}: {v}" for k, v in cat.items()),
        f"CLAIMED-SCORE: {score.total}",
        f"CLUB: {st.club}" if st.club else None,
        f"OPERATORS: {st.operator or st.call}",
        f"NAME: {st.name}" if st.name else None,
        *(f"ADDRESS: {a}" for a in st.address),
        f"EMAIL: {st.email}" if st.email else None,
        "CREATED-BY: tttlog",
        f"SOAPBOX: {soapbox}" if soapbox else None,
    ]
    n = 0
    for q in qsos:
        lines.append(qso_line(q, st.call))   # dupes included; log checkers zero them
        n += 1
    lines.append("END-OF-LOG:")
    Path(path).write_text("\n".join(l for l in lines if l is not None) + "\n", encoding="utf-8")
    return n
