"""Data-driven contest engine: loads a rules YAML and scores a log."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..core import locations
from ..core.cty import CtyDat
from ..core.models import QSO, mode_group

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
    license_class: str = ""    # US: Extra / Advanced / General / Technician / Novice; "" = no band limits
    section: str = ""          # ARRL/RAC section (Sweepstakes, Field Day, 160 m)
    ss_check: str = ""         # Sweepstakes check: two digits, the year first licensed
    ss_precedence: str = "A"   # Sweepstakes precedence: Q A B U M S
    cwops: str = ""            # CWops member number (CWT); blank sends your state
    fd_class: str = ""         # Field Day class, e.g. 1D, 2A
    county: str = ""           # QSO parties: your county, in that party's abbreviation (e.g. NDE)


def list_contests() -> list[dict]:
    out = []
    for p in sorted(RULES_DIR.glob("*.yaml")):
        r = yaml.safe_load(p.read_text())
        out.append({"id": r["id"], "name": r["name"], "path": p, "general": bool(r.get("general"))})
    return sorted(out, key=lambda c: not c["general"])      # General log first


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
    has_mults: bool = True                         # False (e.g. Field Day): score = points

    @property
    def total(self) -> int:
        return self.points * self.mults if self.has_mults else self.points


class ContestEngine:
    def __init__(self, rules: dict, cty: CtyDat, station: Station):
        # QSO parties: the same contest has different rules inside and outside the state
        # (in_state: / out_state: blocks), picked by the station profile's state.
        self.in_state = None
        qp = rules.get("qso_party")
        if qp:
            states = qp["state"] if isinstance(qp["state"], list) else [qp["state"]]
            self.in_state = (station.state or "").upper() in states
            rules = {**rules, **(rules.get("in_state" if self.in_state else "out_state") or {})}
        self.rules = rules
        self.cty = cty
        self.station = station
        me = cty.lookup(station.call)
        self.my_entity = me[0] if me else None
        self.rcvd_fields = [f for f in rules["exchange"]["rcvd"] if f["name"] != "rst"]
        self.sent_fields = [f for f in rules["exchange"]["sent"] if f["name"] != "rst"]

    # ---- exchange helpers ---------------------------------------------
    def next_serial(self, log: list[QSO] | None) -> int:
        """The serial number for the next QSO (QSOs in the log + 1)."""
        return len(log or []) + 1

    def sent_exchange(self, log: list[QSO] | None = None, for_log: bool = False) -> str:
        """What we send. A serial field is the next number; `air_only` fields (e.g. our own
        call in Sweepstakes) are sent but not logged (`for_log`)."""
        vals = []
        for f in self.sent_fields:
            if for_log and f.get("air_only"):
                continue
            if f.get("serial"):
                vals.append(str(self.next_serial(log)))
                continue
            src = f.get("from_station")
            if src:
                v = str(getattr(self.station, src, "") or "")
                if not v and f.get("or_station"):           # e.g. CWT: member number, else state
                    v = str(getattr(self.station, f["or_station"], "") or "")
                if not v and f.get("default"):              # e.g. QSO parties: DX
                    v = str(f["default"])
                if f.get("first_word") and v:               # NAQP / CWT: first name only
                    v = v.split()[0]
                v = v.upper()
                vals.append(v)
            else:
                vals.append(str(f.get("default", "")))
        return " ".join(v for v in vals if v != "")

    @property
    def uses_rst(self) -> bool:
        """False for contests without a signal report (Sweepstakes, NAQP, CWT, Field Day)."""
        return any(f["name"] == "rst" for f in self.rules["exchange"]["rcvd"])

    @property
    def is_general(self) -> bool:
        """General (everyday) log: no dupes, no points, free-text exchange."""
        return bool(self.rules.get("general"))

    def default_rst(self, mode: str | None = None) -> str:
        d = next((f.get("default", "59") for f in self.rules["exchange"]["rcvd"]
                  if f["name"] == "rst"), "59")
        if isinstance(d, dict):                    # per-mode defaults (599 on CW, 59 on phone)
            return str(d.get((mode or "").upper(), d.get("default", "59")))
        return str(d)

    def exchange_required(self) -> bool:
        return any(not f.get("optional") for f in self.rcvd_fields)

    def parse_rcvd(self, exch: str) -> dict:
        toks = exch.upper().split()
        out = {}
        for i, f in enumerate(self.rcvd_fields):
            if f.get("free"):                      # free text: takes the rest of the line
                out[f["name"]] = " ".join(toks[i:])
                break
            out[f["name"]] = toks[i] if i < len(toks) else ""
        return out

    @staticmethod
    def _parts(f: dict, v: str) -> list[str]:
        """A county-line value 'CAR/LEH' is two counties (fields marked county_line)."""
        return [x for x in v.split("/") if x] if f.get("county_line") and "/" in v else [v]

    def _ok_value(self, f: dict, v: str) -> bool:
        if f.get("county_line") and "/" in v:
            parts = self._parts(f, v)
            return len(parts) > 1 and all(self._ok_value({**f, "county_line": False}, x) for x in parts)
        """A field's value is fine if it matches its pattern or is in its list (either one,
        when a field has both: e.g. 10 m takes a state OR a serial number)."""
        checks = []
        if "pattern" in f:
            checks.append(bool(re.match(f["pattern"], v)))
        if "in" in f:
            checks.append(v in locations.values(f["in"]))
        return any(checks) if checks else True

    def _required(self, f: dict, call: str | None) -> bool:
        if f.get("optional"):
            return False
        only = f.get("required_if_entities")
        if only and call:
            hit = self.cty.lookup(call)
            return bool(hit) and hit[0].name in only
        return not only

    def validate_rcvd(self, exch: str, call: str | None = None) -> list[str]:
        """Return a list of error strings (empty == valid)."""
        errs = []
        vals = self.parse_rcvd(exch)
        for f in self.rcvd_fields:
            v = vals.get(f["name"], "")
            if not v:
                if self._required(f, call):
                    errs.append(f"missing {f.get('label', f['name'])}")
            elif not self._ok_value(f, v):
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
        key = self._dupe_key_base(q)
        wf = self.rules.get("dupe_with_field")          # QSO parties: a mobile in a new county is new
        if key is not None and wf:
            key = key + (self.parse_rcvd(q.exch_rcvd).get(wf, ""),)
        return key

    def _dupe_key_base(self, q: QSO):
        rule = self.rules.get("dupe", "per_band")
        if rule == "none":
            return None
        if rule == "once":
            return (q.call.upper(),)
        if rule == "per_band_mode":
            return (q.call.upper(), q.band, mode_group(q.mode))
        if rule == "per_mode":
            return (q.call.upper(), mode_group(q.mode))
        return (q.call.upper(), q.band)

    def is_dupe(self, call: str, band: str, mode: str, log: list[QSO]) -> bool:
        rule = self.rules.get("dupe", "per_band")
        if rule == "none":
            return False
        call = call.upper()
        for q in log:
            if q.is_dupe or q.call.upper() != call:
                continue
            if rule == "once":
                return True
            if rule == "per_mode":
                if mode_group(q.mode) == mode_group(mode):
                    return True
                continue
            if q.band == band and (rule != "per_band_mode" or mode_group(q.mode) == mode_group(mode)):
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
        key = self._dupe_key(q)
        q.is_dupe = key is not None and any(self._dupe_key(p) == key for p in prior if not p.is_dupe)
        q.points = 0 if (q.is_dupe or not self.is_valid(q)) else self._points(ent, q) * self._line_count(q)
        return q

    def is_valid(self, q: QSO) -> bool:
        if q.band not in self.rules["bands"]:
            return False
        vq = self.rules.get("valid_qso", {})
        if q.country in vq.get("exclude_entities", []):
            return False
        fi = vq.get("field_in")                          # QSO parties from outside: only in-state stations
        if fi:
            f = next((x for x in self.rcvd_fields if x["name"] == fi["field"]), {"name": fi["field"]})
            v = self.parse_rcvd(q.exch_rcvd).get(fi["field"], "")
            allowed = locations.values(fi["in"])
            if not v or not all(x in allowed for x in self._parts({**f, "county_line": True}, v)):
                return False
        return True

    def _line_count(self, q: QSO) -> int:
        """A county-line QSO counts once per county (the rules say log one QSO per county)."""
        vals = self.parse_rcvd(q.exch_rcvd)
        n = 1
        for f in self.rcvd_fields:
            if f.get("county_line"):
                n = max(n, len(self._parts(f, vals.get(f["name"], ""))))
        return n

    def _points(self, ent, q: QSO | None = None) -> int:
        p = self.rules["points"]
        if p["type"] == "none":
            return 0
        if p["type"] == "fixed":
            return int(p["value"])
        if p["type"] == "per_mode":                      # e.g. 10 m: CW 4, phone 2
            group = mode_group(q.mode if q else "")
            by = p["values"]
            return int(by.get(group, by.get("DIGI" if group not in ("CW", "SSB") else group, by.get("default", 1))))
        if p["type"] == "by_location":                   # e.g. 160 m: W/VE 2, DX 5
            home = p.get("home_entities", locations.W_VE)
            return int(p["home"] if ent is not None and ent.name in home else p["other"])
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
            hit = None
            if m.get("continent") or m.get("only_entities") or m.get("exclude_entities"):
                hit = self.cty.lookup(q.call)
                ent = hit[0] if hit else None
                if ent is None:
                    continue
                if m.get("continent") and ent.continent != m["continent"]:
                    continue
                if m.get("only_entities") and ent.name not in m["only_entities"]:
                    continue
                if ent.name in m.get("exclude_entities", []):
                    continue
            if m["type"] == "dxcc":
                v = q.country
            elif m["type"] == "cq_zone":
                v = q.cq_zone
            elif m["type"] == "call":                    # e.g. CWT: each call once
                v = q.call.upper()
            else:  # exchange field
                v = self.parse_rcvd(q.exch_rcvd).get(m["type"])
            if v in (None, "", "?"):
                continue
            vs = [x for x in str(v).split("/") if x] if isinstance(v, str) and "/" in v else [v]
            for v in vs:                                 # a county line counts each county
                if m.get("in") and v not in locations.values(m["in"]):
                    continue                             # e.g. NAQP: a state, not a DX prefix
                if m.get("take"):
                    v = v[:int(m["take"])]               # NEQP: NHHIL counts as the state NH
                scope = m.get("scope", "per_band")
                if scope == "per_band":
                    key = (q.band, v)
                elif scope == "per_mode":
                    key = (mode_group(q.mode), v)
                elif scope == "per_band_mode":
                    key = (q.band, mode_group(q.mode), v)
                else:
                    key = (v,)
                out.append((m.get("label", m["type"]), key))
        return out

    def worked_before(self, call: str, log: list[QSO]) -> list[QSO]:
        """Earlier QSOs with this call, newest first (general log banner)."""
        call = call.upper()
        return sorted((q for q in log if q.call.upper() == call),
                      key=lambda q: q.time_utc, reverse=True)

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
                    if len(key) == 2 and key[0] == q.band:          # a per-band mult
                        bb["mults"] += 1
                        bb.setdefault("by_mult", {})[lbl] = bb.get("by_mult", {}).get(lbl, 0) + 1
        s.mults = len(seen)
        s.has_mults = bool(self.rules.get("mults"))
        return s

    def rescore(self, log: list[QSO]) -> list[QSO]:
        """Re-annotate every QSO in time order (after edits/deletes)."""
        done: list[QSO] = []
        # uid breaks ties the same way on every networked station (row ids differ)
        for q in sorted(log, key=lambda x: (x.time_utc, x.uid, x.id or 0)):
            self.annotate(q, done)
            done.append(q)
        return done
