"""HamQTH.com callbook lookups (free account needed), for the other station's
grid square / location. Used for beam headings; the heading falls back to the
centre of the station's country when HamQTH has nothing.

API (v1 XML):  https://www.hamqth.com/xml.php?u=USER&p=PASS      -> session id (valid ~1 h)
               https://www.hamqth.com/xml.php?id=SID&callsign=CALL&prg=tttlog
Results are cached on disk, so a call is looked up once a month at most.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .geo import grid_to_latlon

URL = "https://www.hamqth.com/xml.php"
NS = "{https://www.hamqth.com}"
SESSION_S = 50 * 60            # HamQTH sessions last an hour; renew a bit early
CACHE_DAYS = 30                # found calls
MISS_DAYS = 3                  # calls HamQTH doesn't know
CALL_RE = re.compile(r"^(?:[A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}\d[A-Z0-9]*[A-Z](?:/[A-Z0-9]{1,4})?$")


class CallbookError(Exception):
    """Login failed (bad user/password) or HamQTH can't be reached."""


def looks_like_call(call: str) -> bool:
    return bool(CALL_RE.match(call.upper())) and len(call) >= 3


def _text(el, tag):
    """Find <tag> with or without the HamQTH namespace."""
    for t in (NS + tag, "{http://www.hamqth.com}" + tag, tag):
        found = el.find(".//" + t)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def parse_lookup(xml: bytes) -> tuple[dict | None, str]:
    """-> (record or None, error text). Record: call, grid, lat, lon, name, qth, state."""
    root = ET.fromstring(xml)
    err = _text(root, "error")
    if err:
        return None, err
    call = _text(root, "callsign")
    if not call:
        return None, "no result"
    rec = {"call": call.upper(), "grid": _text(root, "grid").upper(), "name": _text(root, "nick") or
           _text(root, "adr_name"), "qth": _text(root, "qth"), "state": _text(root, "us_state").upper()}
    try:
        lat, lon = float(_text(root, "latitude")), float(_text(root, "longitude"))
        if not (lat == 0 and lon == 0) and -90 <= lat <= 90 and -180 <= lon <= 180:
            rec["lat"], rec["lon"] = lat, lon
    except ValueError:
        pass
    return rec, ""


def location(rec: dict | None) -> tuple[tuple[float, float], str] | None:
    """Where to aim for a callbook record: its grid square first, then its lat/lon.
    -> ((lat, lon), what) or None."""
    if not rec:
        return None
    ll = grid_to_latlon(rec.get("grid", ""))
    if ll:
        return ll, rec["grid"]
    if "lat" in rec:
        return (rec["lat"], rec["lon"]), "lat/lon"
    return None


class HamQTH:
    def __init__(self, user: str, password: str, cache_file: Path | None = None, fetch=None):
        self.user, self.password = user.strip(), password
        self.cache_file = cache_file
        self._fetch = fetch or self._http
        self._sid, self._sid_at = "", 0.0
        self._lock = threading.Lock()
        self.cache: dict[str, dict] = {}
        if cache_file and cache_file.exists():
            try:
                self.cache = json.loads(cache_file.read_text())
            except (ValueError, OSError):
                self.cache = {}

    @staticmethod
    def _http(params: dict) -> bytes:
        req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "tttlog"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

    def _login(self) -> str:
        try:
            root = ET.fromstring(self._fetch({"u": self.user, "p": self.password}))
        except CallbookError:
            raise
        except Exception as e:                                # network, bad XML
            raise CallbookError(f"can't reach HamQTH: {e}") from e
        sid = _text(root, "session_id")
        if not sid:
            raise CallbookError(_text(root, "error") or "HamQTH login failed")
        self._sid, self._sid_at = sid, time.time()
        return sid

    def test_login(self) -> None:
        """Raise CallbookError unless the user name and password work."""
        with self._lock:
            self._login()

    def cached(self, call: str) -> dict | None:
        """A fresh cached answer: a record, {} for 'not in HamQTH', None if not cached."""
        hit = self.cache.get(call.upper())
        if not hit:
            return None
        days = CACHE_DAYS if hit.get("rec") else MISS_DAYS
        if time.time() - hit.get("t", 0) > days * 86400:
            return None
        return hit.get("rec") or {}

    def lookup(self, call: str) -> dict | None:
        """Record for a call, or None if HamQTH doesn't know it. May block (network):
        call it from a worker thread. Raises CallbookError on login/network trouble."""
        call = call.upper().strip()
        c = self.cached(call)
        if c is not None:
            return c or None
        with self._lock:
            for attempt in (1, 2):
                sid = self._sid if self._sid and time.time() - self._sid_at < SESSION_S else self._login()
                try:
                    data = self._fetch({"id": sid, "callsign": call, "prg": "tttlog"})
                    rec, err = parse_lookup(data)
                except CallbookError:
                    raise
                except Exception as e:
                    raise CallbookError(f"can't reach HamQTH: {e}") from e
                if err and ("session" in err.lower() or "expired" in err.lower()) and attempt == 1:
                    self._sid = ""                               # expired: log in again
                    continue
                break
            if err and "not found" not in err.lower() and err != "no result":
                raise CallbookError(err)
            self.cache[call] = {"t": time.time(), "rec": rec or {}}
            self._save()
            return rec

    def _save(self) -> None:
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.cache))
            tmp.replace(self.cache_file)
        except OSError:
            pass
