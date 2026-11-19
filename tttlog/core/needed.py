"""The "what's still needed" grid: every possible mult × band, with its state.

States (one per cell):
  needed_spotted  not worked yet, and someone is spotting it right now
  needed          not worked yet, not spotted
  worked_spotted  already worked, but spotted again
  worked          already worked
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .cluster import Spot
from .models import QSO

STATES = ["needed_spotted", "needed", "worked_spotted", "worked"]
STATE_LABELS = {"needed_spotted": "Needed & spotted", "needed": "Needed",
                "worked_spotted": "Worked & spotted", "worked": "Worked"}

ALL = "All"     # column name for mults that count once per contest


@dataclass
class NeedRow:
    value: object                   # entity name, zone number, or exchange value
    title: str                      # what the row shows
    cells: dict[str, str] = field(default_factory=dict)          # column -> state
    spots: dict[str, list[Spot]] = field(default_factory=dict)   # column -> spots offering it


def mult_defs(engine) -> list[dict]:
    return list(engine.rules.get("mults", []))


def universe(engine, mdef: dict, qsos: list[QSO]) -> list[tuple[object, str]]:
    """(value, title) for every value this mult can take."""
    kind = mdef["type"]
    if kind == "dxcc":
        excl = set(engine.rules.get("valid_qso", {}).get("exclude_entities", []))
        return [(e.name, f"{e.prefix:<6} {e.name}  ({e.continent})")
                for e in engine.cty.entities() if e.name not in excl]
    if kind == "cq_zone":
        return [(z, f"Zone {z}") for z in range(1, 41)]
    if mdef.get("in"):                                   # sections, states, provinces...
        from .locations import values
        return [(v, v) for v in values(mdef["in"])]
    # exchange-field mults (states, sections...) have no fixed list: show what's been worked
    vals = sorted({v for lbl, key in _keys(engine, qsos) if lbl == mdef.get("label", kind)
                   for v in key[-1:]}, key=str)
    return [(v, str(v)) for v in vals]


def _keys(engine, qsos):
    out = set()
    for q in qsos:
        if not q.is_dupe and engine.is_valid(q):
            out.update(engine.mult_values(q))
    return out


def columns(engine, mdef: dict) -> list[str]:
    scope = mdef.get("scope", "per_band")
    if scope == "per_band":
        return list(engine.rules["bands"])
    if scope == "per_mode":                             # e.g. ARRL 10 m: CW and phone count apart
        from .models import mode_group
        return list(dict.fromkeys(mode_group(m) for m in engine.rules.get("modes", [])))
    return [ALL]


def need_grid(engine, mdef: dict, qsos: list[QSO], spots: list[Spot]) -> tuple[list[str], list[NeedRow]]:
    label = mdef.get("label", mdef["type"])
    per_band = mdef.get("scope", "per_band") in ("per_band", "per_mode")    # keyed (column, value)
    cols = columns(engine, mdef)
    worked = {key for lbl, key in _keys(engine, qsos) if lbl == label}

    spotted: dict[tuple, list[Spot]] = {}
    for s in spots:
        for lbl, key in s.keys:
            if lbl == label:
                spotted.setdefault(key, []).append(s)

    rows = []
    for value, title in universe(engine, mdef, qsos):
        row = NeedRow(value=value, title=title)
        for col in cols:
            key = (col, value) if per_band else (value,)
            sp = spotted.get(key, [])
            row.cells[col] = ("worked" if key in worked else "needed") + ("_spotted" if sp else "")
            if sp:
                row.spots[col] = sorted(sp, key=lambda s: s.time_utc, reverse=True)
        rows.append(row)
    return cols, rows


def counts(rows: list[NeedRow]) -> dict[str, int]:
    out = {s: 0 for s in STATES}
    for r in rows:
        for st in r.cells.values():
            out[st] += 1
    return out
