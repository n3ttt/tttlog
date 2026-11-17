"""DX cluster: spot parsing, telnet cleanup, and the spot list.

Network I/O lives in the UI (Qt sockets, so nothing blocks the entry line);
everything here is plain Python and is unit-tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import QSO, band_from_khz

# "DX de W3LPL:     14025.0  DL1ABC       CQ up 1                    1234Z"
# DXSpider, AR-Cluster and CC Cluster all use this layout; the spotter may
# carry "-#" (skimmer) or "-1" style suffixes, and the time may be missing.
SPOT_RE = re.compile(
    r"^DX de\s+(?P<spotter>[A-Z0-9/#\-]+?)-?#?:?\s+"
    r"(?P<freq>\d+(?:\.\d+)?)\s+"
    r"(?P<call>[A-Z0-9/]+)\s*"
    r"(?P<comment>.*?)\s*"
    r"(?:(?P<time>\d{4})Z)?(?:\s+\S+)?\s*$",
    re.IGNORECASE)

# Skimmer (RBN) spots: spotter ends in "-#", or the comment carries the RBN report.
SKIMMER_SPOTTER_RE = re.compile(r"^DX de\s+[A-Z0-9/\-]*-#", re.IGNORECASE)
SKIMMER_COMMENT_RE = re.compile(r"\b\d+\s*dB\b.*\b\d+\s*(WPM|BPS)\b", re.IGNORECASE)

# Login prompts seen on common cluster software.
LOGIN_RE = re.compile(r"(login|call(sign)?|enter your call.*)\s*:?\s*>?\s*$", re.IGNORECASE)

IAC = 255

# Approximate start of the phone segment per band (kHz). Below = CW/digital.
# Contest phone activity sits a little lower than the US band plan on 160/80.
PHONE_START = {"160m": 1840, "80m": 3600, "60m": 0, "40m": 7125, "20m": 14150,
               "17m": 18110, "15m": 21200, "12m": 24930, "10m": 28300, "6m": 50100,
               "2m": 144100, "70cm": 432100}

DIGI_WORDS = ("FT8", "FT4", "RTTY", "PSK", "JT65", "JS8")
DIGI_MODES = {"FT8", "FT4", "RTTY", "PSK31", "JS8", "DIGI"}


def split_telnet(data: bytes) -> tuple[bytes, bytes]:
    """Remove telnet IAC sequences; return (clean bytes, incomplete tail).

    TCP can split a negotiation sequence across reads, so an unfinished one at
    the end is handed back to be prefixed to the next read instead of leaking
    control bytes into the text.
    """
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b != IAC:
            out.append(b); i += 1; continue
        if i + 1 >= n:                       # lone IAC: wait for the command byte
            return bytes(out), data[i:]
        cmd = data[i + 1]
        if cmd == IAC:                       # escaped 255
            out.append(IAC); i += 2
        elif cmd in (251, 252, 253, 254):    # WILL/WONT/DO/DONT <opt>
            if i + 2 >= n:                   # option byte not here yet
                return bytes(out), data[i:]
            i += 3
        elif cmd == 250:                     # SB ... IAC SE
            end = data.find(bytes([IAC, 240]), i + 2)
            if end < 0:                      # subnegotiation not finished yet
                return bytes(out), data[i:]
            i = end + 2
        else:
            i += 2
    return bytes(out), b""


def strip_telnet(data: bytes) -> bytes:
    """Remove telnet IAC sequences from a complete chunk of bytes."""
    return split_telnet(data)[0]


def spot_command(call: str, khz: float, comment: str = "") -> str:
    """The cluster command that spots a station. DXSpider, AR-Cluster and
    CC Cluster all accept  DX <kHz> <call> [comment]."""
    call = call.strip().upper()
    if not call or not re.fullmatch(r"[A-Z0-9/]+", call):
        raise ValueError(f"not a callsign: {call!r}")
    if band_from_khz(khz) is None:
        raise ValueError(f"{khz} kHz is outside the ham bands")
    return f"DX {khz:.1f} {call}" + (f" {comment.strip()}" if comment.strip() else "")


def guess_mode(khz: float, comment: str = "") -> str:
    """Best guess at a spot's mode: comment keywords first, then band plan."""
    c = comment.upper()
    for w in DIGI_WORDS:
        if w in c:
            return "DIGI"
    if re.search(r"\bCW\b", c):
        return "CW"
    if re.search(r"\b(SSB|USB|LSB|PH)\b", c):
        return "SSB"
    band = band_from_khz(khz)
    if band is None:
        return "?"
    return "SSB" if khz >= PHONE_START.get(band, 0) else "CW"


@dataclass
class Spot:
    call: str
    freq_khz: float
    spotter: str
    comment: str = ""
    time_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mode: str = ""
    # filled by SpotList.evaluate()
    status: str = ""          # MULT | Q | DUPE | INVALID
    mults: list[str] = field(default_factory=list)
    keys: list = field(default_factory=list)   # (label, key) mult values this spot carries
    country: str = ""
    skimmer: bool = False     # from a CW/RTTY skimmer (RBN), spotter shown as CALL-#
    spotter_zone: int | None = None
    spotter_cont: str = ""
    spotter_country: str = ""

    @property
    def band(self) -> str | None:
        return band_from_khz(self.freq_khz)


def parse_spot(line: str, now: datetime | None = None) -> Spot | None:
    """Parse one cluster line into a Spot, or None if it isn't a DX spot."""
    line = line.strip()
    if not line[:5].upper() == "DX DE":
        return None
    m = SPOT_RE.match(line)
    if not m:
        return None
    try:
        khz = float(m["freq"])
    except ValueError:
        return None
    if khz > 1_000_000:          # some nodes send Hz
        khz /= 1000
    now = now or datetime.now(timezone.utc)
    t = now.replace(second=0, microsecond=0)
    if m["time"]:
        hh, mm = int(m["time"][:2]), int(m["time"][2:])
        if hh < 24 and mm < 60:
            t = t.replace(hour=hh, minute=mm)
            if t > now + timedelta(minutes=5):       # spot from just before 0000Z
                t -= timedelta(days=1)
    comment = (m["comment"] or "").strip()
    skimmer = bool(SKIMMER_SPOTTER_RE.match(line) or SKIMMER_COMMENT_RE.search(comment))
    return Spot(call=m["call"].upper(), freq_khz=khz, spotter=m["spotter"].upper().rstrip("-#:"),
                comment=comment, time_utc=t, mode=guess_mode(khz, comment), skimmer=skimmer)


def spotter_base(spotter: str) -> str:
    """'W3LPL-2' / 'K1TTT-#' -> 'W3LPL' / 'K1TTT' (for the country lookup)."""
    return spotter.upper().split("-")[0].rstrip("#:")


class SpotList:
    """Latest spot per (call, band), aged out after max_age minutes."""

    def __init__(self, max_age_min: int = 30):
        self.max_age = timedelta(minutes=max_age_min)
        self._spots: dict[tuple, Spot] = {}
        self._spotter_cache: dict[str, object] = {}

    def add(self, s: Spot) -> None:
        if s.band is None:
            return
        self._spots[(s.call, s.band)] = s

    def prune(self, now: datetime) -> None:
        cutoff = now - self.max_age
        self._spots = {k: s for k, s in self._spots.items() if s.time_utc >= cutoff}

    def clear(self) -> None:
        self._spots.clear()

    def __len__(self) -> int:
        return len(self._spots)

    def spots(self) -> list[Spot]:
        """Newest first."""
        return sorted(self._spots.values(), key=lambda s: s.time_utc, reverse=True)

    def evaluate(self, engine, log: list[QSO], only: list[Spot] | None = None) -> None:
        """Mark spots as MULT / Q / DUPE / INVALID against the current log.

        `only` limits the work to newly arrived spots; otherwise all are redone
        (call that after every QSO, edit or delete).
        """
        modes = engine.rules.get("modes", [])
        cty = getattr(engine, "cty", None)
        have = set()
        for p in log:
            if not p.is_dupe and engine.is_valid(p):
                have.update(engine.mult_values(p))
        for s in (only if only is not None else self._spots.values()):
            mode = s.mode if s.mode in ("SSB", "CW") else (modes[0] if modes else "SSB")
            if s.mode == "DIGI" and DIGI_MODES & set(modes):
                mode = next(m for m in modes if m in DIGI_MODES)
            probe = engine.annotate(QSO(call=s.call, freq_khz=s.freq_khz, mode=mode), log)
            s.country = probe.country
            if cty is not None and s.spotter_zone is None:
                hit = self._spotter_cache.get(s.spotter)
                if hit is None:
                    hit = self._spotter_cache[s.spotter] = cty.lookup(spotter_base(s.spotter)) or False
                if hit:
                    s.spotter_zone, s.spotter_cont, s.spotter_country = hit[1], hit[0].continent, hit[0].name
            s.mults = []
            s.keys = engine.mult_values(probe)
            wrong_mode = s.mode not in ("?", "") and modes and mode not in modes
            if wrong_mode or not engine.is_valid(probe):
                s.status = "INVALID"
                s.keys = []                       # can't be worked, so it doesn't count as spotted
            elif probe.is_dupe:
                s.status = "DUPE"
            else:
                s.mults = [lbl for lbl, key in s.keys if (lbl, key) not in have]
                s.status = "MULT" if s.mults else "Q"


# ====================================================================== spot filters
# Kept in the cluster settings as {"spotters": ..., "zones": [...], "skimmer": ...}.
SPOTTER_CHOICES = {
    "any": "Spotters anywhere",
    "zone": "Spotters in my CQ zone",
    "cont": "Spotters on my continent",
    "country": "Spotters in my country",
    "zones": "Spotters in chosen CQ zones",
}
SKIMMER_CHOICES = {"all": "Skimmer + human spots", "no": "No skimmer spots", "only": "Skimmer spots only"}
DEFAULT_FILTER = {"spotters": "any", "zones": [], "skimmer": "all"}


@dataclass
class Home:
    """Where this station is, for 'my zone / continent / country'."""
    zone: int
    cont: str = ""
    country: str = ""       # cty.dat entity name, e.g. "United States"
    prefix: str = ""        # cty.dat primary prefix, e.g. "K"


def filter_zones(f: dict, home: Home) -> list[int]:
    if f.get("spotters") == "zone":
        return [home.zone]
    if f.get("spotters") == "zones":
        return [int(z) for z in f.get("zones", []) if str(z).isdigit()]
    return []


def spot_passes(s: Spot, f: dict, home: Home) -> bool:
    """Local filter: the same on any cluster, and on spots shared over the network.
    A spot whose spotter can't be placed is kept (better to see it than miss it)."""
    sk = f.get("skimmer", "all")
    if (sk == "no" and s.skimmer) or (sk == "only" and not s.skimmer):
        return False
    who = f.get("spotters", "any")
    if who == "any" or s.spotter_zone is None:
        return True
    if who in ("zone", "zones"):
        return s.spotter_zone in filter_zones(f, home)
    if who == "cont":
        return not home.cont or s.spotter_cont == home.cont
    if who == "country":
        return not home.country or s.spotter_country == home.country
    return True


def describe_filter(f: dict, home: Home) -> str:
    """Short text for the Spots window, '' when nothing is filtered."""
    parts = []
    who = f.get("spotters", "any")
    if who == "zone":
        parts.append(f"spotters in zone {home.zone}")
    elif who == "zones" and filter_zones(f, home):
        parts.append("spotters in zones " + ",".join(map(str, filter_zones(f, home))))
    elif who == "cont" and home.cont:
        parts.append(f"{home.cont} spotters")
    elif who == "country" and home.country:
        parts.append(f"{home.country} spotters")
    sk = f.get("skimmer", "all")
    if sk == "no":
        parts.append("no skimmers")
    elif sk == "only":
        parts.append("skimmers only")
    return ", ".join(parts)


# -------------------------------------------------- cluster-side filter commands
CLUSTER_KINDS = {"ar": "AR-Cluster", "cc": "CC Cluster", "spider": "DXSpider"}


def detect_cluster_kind(line: str) -> str:
    """Guess the node software from its login banner / prompt ('' if unknown)."""
    u = line.upper()
    if "AR-CLUSTER" in u or "AR CLUSTER" in u:
        return "ar"
    if "DXSPIDER" in u or "DX SPIDER" in u:
        return "spider"
    if "CC CLUSTER" in u or "CC-CLUSTER" in u or "CCCLUSTER" in u or "CC USER" in u:
        return "cc"
    return ""


def filter_commands(kind: str, f: dict, home: Home) -> tuple[list[str], list[str]]:
    """Commands that ask the cluster itself to send only what `f` lets through.

    Returns (commands, notes). Notes name the parts that cluster can't do, which
    the local filter still handles. Commands replace the earlier server filter.
    """
    who, sk = f.get("spotters", "any"), f.get("skimmer", "all")
    zones = filter_zones(f, home)
    cmds: list[str] = []
    notes: list[str] = []
    if kind == "ar":                      # AR-Cluster v6: one filter expression
        terms = []
        if zones:
            z = " or ".join(f"SpotterCqZone={n}" for n in zones)
            terms.append(f"({z})" if len(zones) > 1 else z)
        elif who == "cont" and home.cont:
            terms.append(f"SpotterCont={home.cont}")
        elif who == "country" and home.prefix:
            terms.append(f"SpotterCty={home.prefix}")
        if sk == "no":
            terms.append("not skimmer")
        elif sk == "only":
            terms.append("skimmer")
        cmds.append(("set dx filter " + " and ".join(terms)).strip())   # empty = clear
    elif kind == "spider":                # DXSpider: accept lines + skimmer switch
        cmds.append("clear/spots all")
        if zones:
            cmds.append("accept/spots by_zone " + ",".join(map(str, zones)))
        elif who == "country" and home.prefix:
            cmds.append(f"accept/spots by_dxcc {home.prefix}")
        elif who == "cont":
            notes.append("DXSpider has no spotter-continent filter: filtering here instead")
        cmds.append("unset/skimmer" if sk == "no" else "set/skimmer")
        if sk == "only":
            notes.append("DXSpider can't send skimmer spots only: filtering here instead")
    elif kind == "cc":                    # CC Cluster
        if who == "country" and home.prefix:
            cmds.append(f"set/filter doc/pass {home.prefix}")
        else:
            cmds.append("set/filter doc/off")
            if who in ("zone", "zones", "cont"):
                notes.append("CC Cluster filters spotters by country, not zone/continent: filtering here instead")
        cmds.append("set/noskimmer" if sk == "no" else "set/skimmer")
        if sk == "only":
            notes.append("CC Cluster can't send skimmer spots only: filtering here instead")
    else:
        notes.append("Unknown cluster type (Config ▸ DX cluster): filtering here only")
    return cmds, notes
