"""Local-network log sharing: the part that doesn't need sockets.

Every change to the log (log a QSO, edit, delete) becomes an *event* stamped
with the computer that made it (origin), that computer's running number (seq)
and the time. Each computer keeps every event it has seen, so:

* any two stations can catch each other up by swapping "what I have" vectors
  ({origin: highest seq I have without gaps}) and sending what's missing;
* a station that was offline, or joins late, gets the whole log;
* the same event arriving twice (two paths through the network) is ignored.

If two stations change the same QSO, the newest change wins (time, then
origin, then seq break ties the same way everywhere), so every station ends
up with the same log.

The socket side (discovery, TCP links) is in tttlog/ui/network.py.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone

from .db import Log
from .models import QSO

NET_SCHEMA = """
CREATE TABLE IF NOT EXISTS net_event (
    origin TEXT NOT NULL, seq INTEGER NOT NULL, ts TEXT NOT NULL,
    action TEXT NOT NULL, uid TEXT NOT NULL, data TEXT,
    PRIMARY KEY (origin, seq)
);
CREATE TABLE IF NOT EXISTS net_rev (
    uid TEXT PRIMARY KEY, ts TEXT NOT NULL, origin TEXT NOT NULL, seq INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _shared(q: QSO) -> dict:
    d = q.to_dict()
    d.pop("id", None)                 # row ids are local to each computer
    return d


class LogSync:
    """Wraps a Log so every change is recorded as a shareable event."""

    def __init__(self, log: Log, node_id: str, station_name: str = ""):
        self.log = log
        self.node_id = node_id
        self.station_name = station_name
        self.conn = log.conn
        self.conn.executescript(NET_SCHEMA)
        self.conn.commit()
        self._backfill()

    # -- local changes -----------------------------------------------------
    def _next_seq(self) -> int:
        r = self.conn.execute("SELECT MAX(seq) FROM net_event WHERE origin=?", (self.node_id,)).fetchone()
        return (r[0] or 0) + 1

    def _record(self, action: str, uid: str, data: dict | None, ts: str | None = None) -> dict:
        ev = {"o": self.node_id, "s": self._next_seq(), "t": ts or _now(), "a": action,
              "u": uid, "q": data}
        self._store(ev)
        self._set_rev(ev)
        self.log.commit()
        return ev

    def local_put(self, q: QSO) -> dict:
        """Log a new QSO or save an edit; returns the event to send to the others."""
        if not q.station_name:
            q.station_name = self.station_name
        if q.id is None:
            self.log.add(q)
        else:
            self.log.update(q)
        return self._record("put", q.uid, _shared(q))

    def local_delete(self, q: QSO) -> dict:
        if q.id is not None:
            self.log.delete(q.id)
        return self._record("del", q.uid, None)

    def _backfill(self) -> None:
        """QSOs logged before networking existed (or imported) get an event, so
        they're shared too. They keep their original logging time as the version."""
        rows = self.conn.execute(
            "SELECT q.id FROM qso q LEFT JOIN net_rev r ON r.uid = q.uid WHERE r.uid IS NULL").fetchall()
        if not rows:
            return
        by_id = {q.id: q for q in self.log.all()}
        for (rid,) in rows:
            q = by_id[rid]
            ev = {"o": self.node_id, "s": self._next_seq(), "t": q.time_utc.isoformat(),
                  "a": "put", "u": q.uid, "q": _shared(q)}
            self._store(ev)
            self._set_rev(ev)
        self.conn.commit()

    # -- remote changes ----------------------------------------------------
    def apply(self, ev: dict) -> tuple[bool, bool]:
        """Take in an event from another station.

        Returns (new, changed): new = we hadn't seen it (so pass it on),
        changed = the log changed (so rescore and redraw)."""
        if not self._valid(ev) or self._have(ev):
            return False, False
        self._store(ev)
        changed = False
        if self._newer_than_current(ev):
            self._set_rev(ev)
            cur = self.log.find_uid(ev["u"])
            if ev["a"] == "put":
                q = QSO.from_dict({**ev["q"], "uid": ev["u"]})
                if cur:
                    q.id = cur.id
                    self.log.update(q)
                else:
                    self.log.add(q)
                changed = True
            elif cur:                                  # delete
                self.log.delete(cur.id)
                changed = True
        self.log.commit()
        return True, changed

    @staticmethod
    def _valid(ev) -> bool:
        try:
            ok = (isinstance(ev["o"], str) and isinstance(ev["s"], int) and ev["s"] > 0
                  and isinstance(ev["t"], str) and ev["a"] in ("put", "del") and isinstance(ev["u"], str)
                  and len(ev["u"]) >= 8)
            if ok and ev["a"] == "put":
                QSO.from_dict({**ev["q"], "uid": ev["u"]})
            return ok
        except (KeyError, TypeError, ValueError):
            return False

    def _have(self, ev) -> bool:
        return self.conn.execute("SELECT 1 FROM net_event WHERE origin=? AND seq=?",
                                 (ev["o"], ev["s"])).fetchone() is not None

    def _newer_than_current(self, ev) -> bool:
        r = self.conn.execute("SELECT ts, origin, seq FROM net_rev WHERE uid=?", (ev["u"],)).fetchone()
        return r is None or (ev["t"], ev["o"], ev["s"]) > (r[0], r[1], r[2])

    def _store(self, ev) -> None:
        self.conn.execute("INSERT OR IGNORE INTO net_event VALUES (?,?,?,?,?,?)",
                          (ev["o"], ev["s"], ev["t"], ev["a"], ev["u"],
                           json.dumps(ev["q"]) if ev["q"] is not None else None))

    def _set_rev(self, ev) -> None:
        self.conn.execute("INSERT OR REPLACE INTO net_rev VALUES (?,?,?,?,?)",
                          (ev["u"], ev["t"], ev["o"], ev["s"], int(ev["a"] == "del")))

    # -- catching up -------------------------------------------------------
    def vector(self) -> dict[str, int]:
        """{origin: highest seq we have with no gaps below it}."""
        out: dict[str, int] = {}
        for origin, seq in self.conn.execute("SELECT origin, seq FROM net_event ORDER BY origin, seq"):
            if seq == out.get(origin, 0) + 1:
                out[origin] = seq
            else:
                out.setdefault(origin, 0)
        return out

    def events_after(self, vector: dict[str, int]) -> list[dict]:
        """Every event the holder of `vector` is missing, oldest first per origin."""
        out = []
        for o, s, t, a, u, data in self.conn.execute(
                "SELECT origin, seq, ts, action, uid, data FROM net_event ORDER BY origin, seq"):
            if s > int(vector.get(o, 0)):
                out.append({"o": o, "s": s, "t": t, "a": a, "u": u,
                            "q": json.loads(data) if data else None})
        return out

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM net_event").fetchone()[0]

    @contextmanager
    def bulk(self):
        """Apply many remote events quickly (one disk sync at the end, not per QSO)."""
        old = self.log.durable
        self.log.durable = False
        try:
            yield
        finally:
            self.log.durable = old
            self.log.flush_journal()
            self.log.commit()
