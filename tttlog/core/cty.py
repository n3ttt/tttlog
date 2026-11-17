"""Callsign -> DXCC entity / CQ zone lookup from AD1C's cty.dat.

Get the current file with `python scripts/update_cty.py` (downloads from
country-files.com into data/cty.dat).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"     # shipped with the app / repo
USER_DATA_DIR = Path.home() / ".tttlog" / "data"            # newer files the user downloaded
CTY_URL = "https://www.country-files.com/cty/cty.dat"


def data_file(name: str) -> Path:
    """The user's copy of a data file if they have one, else the shipped one."""
    user = USER_DATA_DIR / name
    return user if user.exists() else DATA_DIR / name


def download_cty(timeout: float = 30) -> Path:
    """Fetch the latest cty.dat into the user data folder; returns its path."""
    import urllib.request
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(CTY_URL, timeout=timeout) as r:
        data = r.read()
    CtyDat.check(data)                       # don't replace a good file with an error page
    dest = USER_DATA_DIR / "cty.dat"
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest

# Suffixes after a slash that do NOT change the entity
_IGNORE_SUFFIXES = {"P", "M", "MM", "AM", "QRP", "A", "B", "LH", "R"}


@dataclass(frozen=True)
class Entity:
    name: str
    prefix: str          # primary prefix, e.g. "DL", "K", "VE"
    cq_zone: int
    itu_zone: int
    continent: str
    lat: float
    lon: float


_OVERRIDE = re.compile(r"\((\d+)\)|\[(\d+)\]|<[^>]*>|\{(\w+)\}|~[^~]*~")


class CtyDat:
    def __init__(self, path: str | Path | None = None):
        path = Path(path) if path else data_file("cty.dat")
        self.exact: dict[str, tuple[Entity, int | None]] = {}
        self.prefixes: dict[str, tuple[Entity, int | None]] = {}
        self._parse(path.read_text(encoding="latin-1"))

    def _parse(self, text: str) -> None:
        entity: Entity | None = None
        buf = ""
        for line in text.splitlines():
            if not line.strip():
                continue
            if not line[0].isspace():                      # header line
                f = [x.strip() for x in line.split(":")]
                try:
                    entity = Entity(name=f[0], cq_zone=int(f[1]), itu_zone=int(f[2]),
                                    continent=f[3], lat=float(f[4]), lon=-float(f[5]),
                                    prefix=f[7].lstrip("*"))
                except (IndexError, ValueError):             # not a cty.dat line: skip it
                    entity = None
                buf = ""
                continue
            if entity is None:
                continue
            buf += line.strip()
            if buf.endswith(";"):
                for alias in buf.rstrip(";").split(","):
                    alias = alias.strip()
                    if not alias:
                        continue
                    m = re.search(r"\((\d+)\)", alias)
                    cq = int(m.group(1)) if m else None
                    bare = _OVERRIDE.sub("", alias)
                    if bare.startswith("="):
                        self.exact[bare[1:].upper()] = (entity, cq)
                    else:
                        self.prefixes[bare.upper()] = (entity, cq)
                buf = ""

    @staticmethod
    def check(data: bytes) -> None:
        """Raise ValueError unless data looks like a real cty.dat."""
        text = data.decode("latin-1", "replace")
        if len(data) < 20_000 or "United States" not in text or ";" not in text:
            raise ValueError("downloaded file doesn't look like cty.dat")

    def entities(self) -> list[Entity]:
        """Every DXCC entity in the file, sorted by primary prefix."""
        seen = {e.name: e for e, _ in list(self.prefixes.values()) + list(self.exact.values())}
        return sorted(seen.values(), key=lambda e: (e.prefix, e.name))

    @staticmethod
    def _effective(call: str) -> str:
        call = call.upper().strip()
        if "/" not in call:
            return call
        parts = [p for p in call.split("/") if p and p not in _IGNORE_SUFFIXES]
        if not parts:
            return call.split("/")[0]
        if len(parts) == 1:
            return parts[0]
        # e.g. DL/N3TTT or N3TTT/KH6 -> the shorter piece is the location prefix
        return min(parts, key=len)

    def lookup(self, call: str) -> tuple[Entity, int] | None:
        """Return (entity, cq_zone) or None."""
        raw = call.upper().strip()
        if raw in self.exact:
            e, cq = self.exact[raw]
            return e, cq or e.cq_zone
        key = self._effective(raw)
        if key in self.exact:
            e, cq = self.exact[key]
            return e, cq or e.cq_zone
        for n in range(len(key), 0, -1):
            hit = self.prefixes.get(key[:n])
            if hit:
                e, cq = hit
                return e, cq or e.cq_zone
        return None
