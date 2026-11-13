"""Data-driven contest engine: loads a rules YAML and scores a log."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..core.cty import CtyDat
from ..core.models import QSO

RULES_DIR = Path(__file__).parent / "rules"


@dataclass
class Station:
    call: str
    operator: str = ""
    state: str = ""            # e.g. "DE"
    cq_zone: int = 5
    itu_zone: int = 8
    grid: str = ""
    name: str = ""
    address: list[str] = field(default_factory=list)
    club: str = ""
    email: str = ""


def list_contests() -> list[dict]:
    out = []
    for p in sorted(RULES_DIR.glob("*.yaml")):
        r = yaml.safe_load(p.read_text())
        out.append({"id": r["id"], "name": r["name"], "path": p})
    return out


def load_rules(contest_id: str) -> dict:
    for c in list_contests():
        if c["id"] == contest_id:
            return yaml.safe_load(c["path"].read_text())
    raise KeyError(f"No rules file for contest {contest_id!r}")


@dataclass
class Score:
    qsos: int = 0
    dupes: int = 0
    invalid: int = 0
    points: int = 0
    mults: int = 0
    by_band: dict = field(default_factory=dict)   # band -> {"qsos","points","mults"}
    mult_sets: dict = field(default_factory=dict)  # label -> set of (band, value)

    @property
    def total(self) -> int:
        return self.points * self.mults


class ContestEngine:
    def __init__(self, rules: dict, cty: CtyDat, station: Station):
        self.rules = rules
        self.cty = cty
        self.station = station
        me = cty.lookup(station.call)
        self.my_entity = me[0] if me else None
        self.rcvd_fields = [f for f in rules["exchange"]["rcvd"] if f["name"] != "rst"]
        self.sent_fields = [f for f in rules["exchange"]["sent"] if f["name"] != "rst"]

    # ---- exchange helpers ---------------------------------------------
    def sent_exchange(self) -> str:
        vals = []
        for f in self.sent_fields:
            src = f.get("from_station")
            vals.append(str(getattr(self.station, src)) if src else f.get("default", ""))
        return " ".join(vals)

    def default_rst(self) -> str:
        return next((f.get("default", "59") for f in self.rules["exchange"]["rcvd"]
                     if f["name"] == "rst"), "59")

    def parse_rcvd(self, exch: str) -> dict:
        toks = exch.upper().split()
        return {f["name"]: (toks[i] if i < len(toks) else "") for i, f in enumerate(self.rcvd_fields)}

    def validate_rcvd(self, exch: str) -> list[str]:
        """Return a list of error strings (empty == valid)."""
        errs = []
        vals = self.parse_rcvd(exch)
        for f in self.rcvd_fields:
            v = vals[f["name"]]
            if not v:
                errs.append(f"missing {f.get('label', f['name'])}")
            elif "pattern" in f and not re.match(f["pattern"], v):
                errs.append(f"bad {f.get('label', f['name'])}: {v}")
        return errs

    def prefill(self, call: str) -> str:
        """Suggested received exchange for a call (e.g. CQ zone from cty.dat)."""
        hit = self.cty.lookup(call)
        out = []
        for f in self.rcvd_fields:
            if f.get("prefill") == "cq_zone" and hit:
                out.append(str(hit[1]))
            else:
                out.append("")
        return " ".join(out).strip()

    # ---- dupes ----------------------------------------------------------
    def _dupe_key(self, q: QSO):
        rule = self.rules.get("dupe", "per_band")
        if rule == "once":
            return (q.call.upper(),)
        if rule == "per_band_mode":
            return (q.call.upper(), q.band, q.mode)
        return (q.call.upper(), q.band)

    def is_dupe(self, call: str, band: str, mode: str, log: list[QSO]) -> bool:
        rule = self.rules.get("dupe", "per_band")
        call = call.upper()
        for q in log:
            if q.is_dupe or q.call.upper() != call:
                continue
            if rule == "once":
                return True
            if q.band == band and (rule != "per_band_mode" or q.mode == mode):
                return True
        return False

    # ---- per-QSO scoring --------------------------------------------------
    def annotate(self, q: QSO, prior: list[QSO]) -> QSO:
        """Fill country/zone/points/is_dupe on q given the QSOs logged before it."""
        hit = self.cty.lookup(q.call)
        ent = hit[0] if hit else None
        q.country = ent.name if ent else "?"
        vals = self.parse_rcvd(q.exch_rcvd)
        if vals.get("cq_zone", "").isdigit():
            q.cq_zone = int(vals["cq_zone"])
        else:
            q.cq_zone = hit[1] if hit else None
        q.is_dupe = any(self._dupe_key(p) == self._dupe_key(q) for p in prior if not p.is_dupe)
        q.points = 0 if (q.is_dupe or not self.is_valid(q)) else self._points(ent)
        return q

    def is_valid(self, q: QSO) -> bool:
        if q.band not in self.rules["bands"]:
            return False
        excl = self.rules.get("valid_qso", {}).get("exclude_entities", [])
        return q.country not in excl

    def _points(self, ent) -> int:
        p = self.rules["points"]
        if p["type"] == "fixed":
            return int(p["value"])
        if p["type"] == "cqww":
            me = self.my_entity
            if ent is None or me is None:
                return 0
            if ent.name == me.name:
                return 0
            if ent.continent != me.continent:
                return 3
            return 2 if me.continent == "NA" else 1
        raise ValueError(f"unknown points type {p['type']}")

    def mult_values(self, q: QSO) -> list[tuple[str, tuple]]:
        """(label, key) pairs this QSO would count toward."""
        out = []
        for m in self.rules.get("mults", []):
            if m["type"] == "dxcc":
                v = q.country
            elif m["type"] == "cq_zone":
                v = q.cq_zone
            else:  # exchange field
                v = self.parse_rcvd(q.exch_rcvd).get(m["type"])
            if v in (None, "", "?"):
                continue
            key = (q.band, v) if m.get("scope", "per_band") == "per_band" else (v,)
            out.append((m.get("label", m["type"]), key))
        return out

    def is_new_mult(self, q: QSO, log: list[QSO]) -> list[str]:
        """Labels of mults this (annotated) QSO would add."""
        have = set()
        for p in log:
            if not p.is_dupe and self.is_valid(p):
                have.update(self.mult_values(p))
        return [lbl for lbl, key in self.mult_values(q) if (lbl, key) not in have]

    # ---- whole-log score -------------------------------------------------
    def score(self, log: list[QSO]) -> Score:
        s = Score()
        seen: set = set()
        for b in self.rules["bands"]:
            s.by_band[b] = {"qsos": 0, "points": 0, "mults": 0}
        for q in log:
            if q.is_dupe:
                s.dupes += 1
                continue
            if not self.is_valid(q):
                s.invalid += 1
                continue
            s.qsos += 1
            s.points += q.points
            bb = s.by_band.setdefault(q.band, {"qsos": 0, "points": 0, "mults": 0})
            bb["qsos"] += 1
            bb["points"] += q.points
            for lbl, key in self.mult_values(q):
                if (lbl, key) not in seen:
                    seen.add((lbl, key))
                    s.mult_sets.setdefault(lbl, set()).add(key)
                    if len(key) == 2:
                        bb["mults"] += 1
        s.mults = len(seen)
        return s

    def rescore(self, log: list[QSO]) -> list[QSO]:
        """Re-annotate every QSO in time order (after edits/deletes)."""
        done: list[QSO] = []
        for q in sorted(log, key=lambda x: (x.time_utc, x.id or 0)):
            self.annotate(q, done)
            done.append(q)
        return done
