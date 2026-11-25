"""Log storage: SQLite + append-only journal.

Every QSO write goes to the journal (fsync'd JSON line) *before* the DB commit,
so a crash mid-contest can always be recovered with `Log.recover_from_journal()`.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .models import QSO, new_uid

SCHEMA = """
CREATE TABLE IF NOT EXISTS qso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time_utc TEXT NOT NULL,
    call TEXT NOT NULL,
    freq_khz REAL NOT NULL,
    band TEXT,
    mode TEXT NOT NULL,
    rst_sent TEXT, rst_rcvd TEXT,
    exch_sent TEXT, exch_rcvd TEXT,
    station_call TEXT, operator TEXT, contest_id TEXT,
    country TEXT, cq_zone INTEGER, points INTEGER, is_dupe INTEGER,
    uid TEXT, station_name TEXT, dxcc INTEGER
);
CREATE INDEX IF NOT EXISTS idx_call_band ON qso(call, band);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

FIELDS = ["time_utc", "call", "freq_khz", "band", "mode", "rst_sent", "rst_rcvd",
          "exch_sent", "exch_rcvd", "station_call", "operator", "contest_id",
          "country", "cq_zone", "points", "is_dupe", "uid", "station_name", "dxcc"]


class Log:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.journal_path = self.path.with_suffix(".journal")
        self.durable = True        # False while taking in a batch from the network: sync once at the end
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Bring logs made by older versions up to date (adds the network columns)."""
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(qso)")}
        for col, kind in (("uid", "TEXT"), ("station_name", "TEXT"), ("dxcc", "INTEGER")):
            if col not in have:
                self.conn.execute(f"ALTER TABLE qso ADD COLUMN {col} {kind}")
        for (rid,) in self.conn.execute("SELECT id FROM qso WHERE uid IS NULL OR uid=''").fetchall():
            self.conn.execute("UPDATE qso SET uid=? WHERE id=?", (new_uid(), rid))
        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_uid ON qso(uid)")

    # ---- journal -------------------------------------------------------
    def _journal(self, action: str, payload: dict) -> None:
        with open(self.journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"action": action, **payload}) + "\n")
            f.flush()
            if self.durable:
                os.fsync(f.fileno())

    def flush_journal(self) -> None:
        if self.journal_path.exists():
            with open(self.journal_path, "a", encoding="utf-8") as f:
                os.fsync(f.fileno())

    def commit(self) -> None:
        """Commit now, unless a network batch is in progress (it commits at the end)."""
        if self.durable:
            self.conn.commit()

    # ---- CRUD ----------------------------------------------------------
    def _row(self, q: QSO) -> list:
        return [q.time_utc.isoformat(), q.call.upper(), q.freq_khz, q.band, q.mode,
                q.rst_sent, q.rst_rcvd, q.exch_sent, q.exch_rcvd, q.station_call,
                q.operator, q.contest_id, q.country, q.cq_zone, q.points, int(q.is_dupe),
                q.uid, q.station_name, q.dxcc]

    def add(self, q: QSO) -> QSO:
        if not q.uid:
            q.uid = new_uid()
        cur = self.conn.execute(
            f"INSERT INTO qso ({','.join(FIELDS)}) VALUES ({','.join('?' * len(FIELDS))})",
            self._row(q))
        q.id = cur.lastrowid
        self._journal("add", q.to_dict())   # journal (with id) before commit
        self.commit()
        return q

    def update(self, q: QSO) -> None:
        assert q.id is not None
        self._journal("update", q.to_dict())
        sets = ",".join(f"{f}=?" for f in FIELDS)
        self.conn.execute(f"UPDATE qso SET {sets} WHERE id=?", self._row(q) + [q.id])
        self.commit()

    def delete(self, qso_id: int) -> None:
        self._journal("delete", {"id": qso_id})
        self.conn.execute("DELETE FROM qso WHERE id=?", (qso_id,))
        self.commit()

    def find_uid(self, uid: str) -> QSO | None:
        r = self.conn.execute("SELECT * FROM qso WHERE uid=?", (uid,)).fetchone()
        return self._from_row(r) if r else None

    def all(self) -> list[QSO]:
        rows = self.conn.execute("SELECT * FROM qso ORDER BY time_utc, id").fetchall()
        return [self._from_row(r) for r in rows]

    @staticmethod
    def _from_row(r: sqlite3.Row) -> QSO:
        from datetime import datetime
        return QSO(id=r["id"], time_utc=datetime.fromisoformat(r["time_utc"]),
                   call=r["call"], freq_khz=r["freq_khz"], mode=r["mode"],
                   rst_sent=r["rst_sent"], rst_rcvd=r["rst_rcvd"],
                   exch_sent=r["exch_sent"], exch_rcvd=r["exch_rcvd"],
                   station_call=r["station_call"], operator=r["operator"],
                   contest_id=r["contest_id"], country=r["country"] or "",
                   cq_zone=r["cq_zone"], points=r["points"] or 0,
                   is_dupe=bool(r["is_dupe"]), uid=r["uid"] or "",
                   station_name=r["station_name"] or "", dxcc=r["dxcc"])

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        self.conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def close(self) -> None:
        self.conn.close()

    # ---- recovery ------------------------------------------------------
    @classmethod
    def recover_from_journal(cls, journal: str | Path, new_db: str | Path) -> "Log":
        """Rebuild a fresh database purely from a journal file."""
        log = cls(new_db)
        log.journal_path = Path(new_db).with_suffix(".recovered.journal")
        live: dict[str, QSO] = {}
        order: list[str] = []
        for line in Path(journal).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            action = ev.pop("action")
            if action == "add":
                q = QSO.from_dict(ev)
                key = str(q.id)
                live[key] = q
                order.append(key)
            elif action == "update":
                live[str(ev["id"])] = QSO.from_dict(ev)
            elif action == "delete":
                live.pop(str(ev["id"]), None)
        for key in order:
            if key in live:
                q = live[key]
                q.id = None
                if q.uid and log.find_uid(q.uid):     # duplicated in the journal
                    continue
                log.add(q)
        return log
