"""User settings: station profile + function-key macros (YAML in ~/.tttlog)."""
from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path

import yaml

from .contests.engine import Station

CONFIG_DIR = Path.home() / ".tttlog"
STATION_FILE = CONFIG_DIR / "station.yaml"
MACROS_FILE = CONFIG_DIR / "macros.yaml"
CLUSTER_FILE = CONFIG_DIR / "cluster.yaml"
COLORS_FILE = CONFIG_DIR / "colors.yaml"
NETWORK_FILE = CONFIG_DIR / "network.yaml"
NODE_ID_FILE = CONFIG_DIR / "node_id"
WSJTX_FILE = CONFIG_DIR / "wsjtx.yaml"
RIG_FILE = CONFIG_DIR / "radio.yaml"
KEYER_FILE = CONFIG_DIR / "keyer.yaml"

# Voice + CW keyer. Nothing is ever transmitted unless "allow_tx" is on.
DEFAULT_KEYER = {
    "allow_tx": False,
    "mic": "",                  # audio input to record messages from ("" = system default)
    "radio_out": "",            # audio output that goes to the radio (Flex DAX TX, rig USB codec)
    "ptt": "cat",               # cat | rts | dtr | vox (radio keys itself on audio)
    "cw": "cat",                # cat (radio sends the text) | dtr | rts (tttlog keys a serial line)
    "line_port": "",            # serial port for DTR/RTS keying / PTT (e.g. the FTDX10's Standard COM port)
    "wpm": 28,
    "cut": "nt",                # cut numbers in CW: none | nt (5NN) | ant | all (core/keyer.py)
    "cut_exch": False,          # also cut the exchange numbers (zone, serial), not just the RST
    "ptt_lead_ms": 120,         # PTT on -> audio starts
    "ptt_tail_ms": 150,         # audio ends -> PTT off
    "max_tx_secs": 90,          # hard stop: never stay keyed longer than this
}

# Radio (CAT). "control" off = tttlog only follows the radio and never sends it
# anything but read queries; on = band buttons, typed kHz and spots tune it.
DEFAULT_RIG = {
    "enabled": False,
    "dialect": "flex",          # flex | kenwood | yaesu (see tttlog/core/rig.py)
    "connection": "tcp",        # tcp | serial
    "host": "127.0.0.1",
    "port": 5002,               # SmartSDR for Mac's CAT port
    "serial_port": "",
    "baud": 38400,
    "poll_ms": 400,
    "control": False,
    "civ_model": "ic7300",      # Icom only: model (default CI-V address, data mode, CW)
    "civ_addr": None,           # Icom only: CI-V address; None = the model's default
}

# WSJT-X (and JTDX / MSHV, which speak the same protocol): tttlog listens for
# the UDP packet WSJT-X sends when you log a QSO there. Match WSJT-X's
# Settings > Reporting > UDP Server (default 127.0.0.1 port 2237).
DEFAULT_WSJTX = {
    "enabled": False,
    "address": "127.0.0.1",   # or a multicast group such as 224.0.0.1 to share with GridTracker/JTAlert
    "port": 2237,
}

# Local network (several tttlog computers sharing one log). Stations find each
# other with a UDP broadcast on udp_port and link over TCP on tcp_port.
DEFAULT_NETWORK = {
    "enabled": False,
    "station_name": "",       # "" = this computer's name, e.g. RUN1 / MULT / SHACK-PC
    "net_name": "TTTLOG",     # only stations with the same network name link up
    "tcp_port": 12071,
    "udp_port": 12070,
    "peers": [],              # extra stations to dial, "host" or "host:port" (when broadcast can't reach)
}

# Colors for the Needed window and the Spots window. "show" = the checkbox state.
DEFAULT_COLORS = {
    "needed_spotted": {"color": "#57cc99", "show": True},    # need it AND it's spotted now
    "needed":         {"color": "#ffb4a2", "show": True},    # need it, nobody spotting it
    "worked_spotted": {"color": "#bde0fe", "show": False},   # have it, but spotted again
    "worked":         {"color": "#e9ecef", "show": False},   # have it
    "spot_mult":      {"color": "#57cc99", "show": True},    # Spots window: new mult
    "spot_q":         {"color": "#fff3b0", "show": True},    # Spots window: new Q, no mult
    "spot_dupe":      {"color": "#9a9a9a", "show": False},   # Spots window: dupe / can't work
}

# DX cluster (telnet). login "" means "use the station call".
DEFAULT_CLUSTER = {
    "host": "w3lpl.net",
    "port": 7373,
    "login": "",
    "max_age_min": 30,        # drop spots older than this
    "auto_connect": False,    # connect when tttlog starts
    "auto_spot_sp": False,    # spot each new S&P QSO (call + frequency) to the cluster
    "init_commands": [],      # sent once after login, e.g. ["set/skimmer", "sh/dx 30"]
    "cluster_type": "auto",   # auto | ar | cc | spider: which filter commands to send
    "spot_filter": {"spotters": "any", "zones": [], "skimmer": "all"},
    "auto_send_filter": False,  # send the filter to the cluster whenever it changes
    "share_cluster": True,    # let networked stations use my cluster connection
    "use_network_cluster": True,  # when I'm not connected, use a networked station's
    "show_buttons": True,
    "buttons": None,          # None = DEFAULT_CLUSTER_BUTTONS (edit: right-click the buttons)
}

# Cluster window command buttons (N1MM style: across the bottom, right-click to edit).
# Tokens: {MYCALL} {CALL} (the entry line's call, else the last QSO's) {FREQ} (kHz);
# {CONN} reconnects to the cluster; "|" sends several commands from one button.
DEFAULT_CLUSTER_BUTTONS = [
    {"label": "SH/DX", "command": "SH/DX 30"},
    {"label": "DX of call", "command": "SH/DX {CALL}"},
    {"label": "WWV", "command": "SH/WWV"},
    {"label": "Sun", "command": "SH/SUN"},
    {"label": "Filter?", "command": "SH/FILTER"},
    {"label": "Users", "command": "SH/USERS"},
    {"label": "Skimmer on", "command": "SET/SKIMMER"},
    {"label": "Skimmer off", "command": "SET/NOSKIMMER"},
    {"label": "Heading", "command": "SH/HEADING {CALL}"},
    {"label": "QRZ", "command": "SH/QRZ {CALL}"},
    {"label": "Reconnect", "command": "{CONN}"},
    {"label": "Bye", "command": "BYE"},
]


def cluster_buttons(cfg: dict) -> list[dict]:
    """The 12 buttons (saved ones, padded with blanks; defaults if never edited)."""
    rows = cfg.get("buttons") or DEFAULT_CLUSTER_BUTTONS
    rows = [{"label": str(r.get("label", "")), "command": str(r.get("command", ""))} for r in rows][:12]
    return rows + [{"label": "", "command": ""} for _ in range(12 - len(rows))]


def expand_cluster_command(command: str, mycall: str, call: str, freq_khz: float) -> list[str]:
    """A button's command -> the lines to send ({CONN} stays as its own item)."""
    text = (command.replace("{MYCALL}", mycall).replace("{CALL}", call)
            .replace("{FREQ}", f"{freq_khz:.1f}"))
    return [part.strip() for part in text.split("|") if part.strip()]

# Macro text: {MYCALL} {CALL} {EXCH} {RST} {STATE} {ZONE} are substituted.
# Action tokens: {CLEAR} wipes the entry line; {SPOT} spots the last QSO
# (call + frequency) to the DX cluster.
# SSB: text is shown + the WAV file (in ~/.tttlog/wav/<MYCALL>/) is played by
# the voice keyer (Ctrl+Shift+F-key records it). CW: the text is sent by the keyer.
DEFAULT_MACROS = {
    "SSB": {
        "RUN": [
            {"key": "F1", "label": "CQ", "text": "CQ contest {MYCALL} {MYCALL}", "wav": "cq.wav"},
            {"key": "F2", "label": "Exch", "text": "59 {EXCH}", "wav": "exch.wav"},
            {"key": "F3", "label": "TU", "text": "Thanks {MYCALL}", "wav": "tu.wav"},
            {"key": "F4", "label": "MyCall", "text": "{MYCALL}", "wav": "mycall.wav"},
            {"key": "F5", "label": "His Call", "text": "{CALL}", "wav": ""},
            {"key": "F6", "label": "Repeat", "text": "59 {EXCH} {EXCH}", "wav": "exch2.wav"},
            {"key": "F7", "label": "?", "text": "Again?", "wav": "agn.wav"},
            {"key": "F8", "label": "AGN", "text": "Please repeat", "wav": "agn.wav"},
            {"key": "F9", "label": "Nr?", "text": "Your power?", "wav": "pwr.wav"},
            {"key": "F10", "label": "Spare", "text": "", "wav": ""},
            {"key": "F11", "label": "Spot", "text": "{SPOT}", "wav": ""},
            {"key": "F12", "label": "Wipe", "text": "{CLEAR}", "wav": ""},
        ],
        "SP": [
            {"key": "F1", "label": "MyCall", "text": "{MYCALL}", "wav": "mycall.wav"},
            {"key": "F2", "label": "Exch", "text": "59 {EXCH}", "wav": "exch.wav"},
            {"key": "F3", "label": "TU", "text": "Thanks", "wav": "tu_sp.wav"},
            {"key": "F4", "label": "MyCall", "text": "{MYCALL}", "wav": "mycall.wav"},
            {"key": "F5", "label": "His Call", "text": "{CALL}", "wav": ""},
            {"key": "F6", "label": "Repeat", "text": "59 {EXCH} {EXCH}", "wav": "exch2.wav"},
            {"key": "F7", "label": "?", "text": "Again?", "wav": "agn.wav"},
            {"key": "F8", "label": "AGN", "text": "Please repeat", "wav": "agn.wav"},
            {"key": "F9", "label": "Spare", "text": "", "wav": ""},
            {"key": "F10", "label": "Spare", "text": "", "wav": ""},
            {"key": "F11", "label": "Spot", "text": "{SPOT}", "wav": ""},
            {"key": "F12", "label": "Wipe", "text": "{CLEAR}", "wav": ""},
        ],
    },
    "CW": {
        "RUN": [
            {"key": "F1", "label": "CQ", "text": "CQ TEST {MYCALL} {MYCALL}"},
            {"key": "F2", "label": "Exch", "text": "{RST} {EXCH}"},
            {"key": "F3", "label": "TU", "text": "TU {MYCALL}"},
            {"key": "F4", "label": "MyCall", "text": "{MYCALL}"},
            {"key": "F5", "label": "His Call", "text": "{CALL}"},
            {"key": "F6", "label": "Repeat", "text": "{EXCH} {EXCH}"},
            {"key": "F7", "label": "?", "text": "?"},
            {"key": "F8", "label": "AGN", "text": "AGN"},
            {"key": "F9", "label": "Nr?", "text": "NR?"},
            {"key": "F10", "label": "Spare", "text": ""},
            {"key": "F11", "label": "Spot", "text": "{SPOT}"},
            {"key": "F12", "label": "Wipe", "text": "{CLEAR}"},
        ],
        "SP": [
            {"key": "F1", "label": "MyCall", "text": "{MYCALL}"},
            {"key": "F2", "label": "Exch", "text": "{RST} {EXCH}"},
            {"key": "F3", "label": "TU", "text": "TU"},
            {"key": "F4", "label": "MyCall", "text": "{MYCALL}"},
            {"key": "F5", "label": "His Call", "text": "{CALL}"},
            {"key": "F6", "label": "Repeat", "text": "{EXCH} {EXCH}"},
            {"key": "F7", "label": "?", "text": "?"},
            {"key": "F8", "label": "AGN", "text": "AGN"},
            {"key": "F9", "label": "Spare", "text": ""},
            {"key": "F10", "label": "Spare", "text": ""},
            {"key": "F11", "label": "Spot", "text": "{SPOT}"},
            {"key": "F12", "label": "Wipe", "text": "{CLEAR}"},
        ],
    },
}


def load_station() -> Station:
    if STATION_FILE.exists():
        return Station(**(yaml.safe_load(STATION_FILE.read_text()) or {}))
    return Station(call="N0CALL")


def save_station(st: Station) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    STATION_FILE.write_text(yaml.safe_dump(asdict(st), sort_keys=False))


def load_macros() -> dict:
    if MACROS_FILE.exists():
        return yaml.safe_load(MACROS_FILE.read_text())
    return copy.deepcopy(DEFAULT_MACROS)           # a copy: edits must never change the defaults


def save_macros(m: dict) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    MACROS_FILE.write_text(yaml.safe_dump(m, sort_keys=False))


def load_cluster() -> dict:
    cfg = dict(DEFAULT_CLUSTER)
    if CLUSTER_FILE.exists():
        cfg.update(yaml.safe_load(CLUSTER_FILE.read_text()) or {})
    return cfg


def save_cluster(cfg: dict) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    CLUSTER_FILE.write_text(yaml.safe_dump(cfg, sort_keys=False))


def load_network() -> dict:
    cfg = dict(DEFAULT_NETWORK)
    if NETWORK_FILE.exists():
        cfg.update(yaml.safe_load(NETWORK_FILE.read_text()) or {})
    if not cfg.get("station_name"):
        import socket
        cfg["station_name"] = (socket.gethostname().split(".")[0] or "STATION").upper()[:16]
    return cfg


def save_network(cfg: dict) -> None:
    NETWORK_FILE.parent.mkdir(parents=True, exist_ok=True)
    NETWORK_FILE.write_text(yaml.safe_dump(cfg, sort_keys=False))


def load_wsjtx() -> dict:
    cfg = dict(DEFAULT_WSJTX)
    if WSJTX_FILE.exists():
        cfg.update(yaml.safe_load(WSJTX_FILE.read_text()) or {})
    return cfg


def save_wsjtx(cfg: dict) -> None:
    WSJTX_FILE.parent.mkdir(parents=True, exist_ok=True)
    WSJTX_FILE.write_text(yaml.safe_dump(cfg, sort_keys=False))


def load_rig() -> dict:
    cfg = dict(DEFAULT_RIG)
    if RIG_FILE.exists():
        cfg.update(yaml.safe_load(RIG_FILE.read_text()) or {})
    return cfg


def save_rig(cfg: dict) -> None:
    RIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    RIG_FILE.write_text(yaml.safe_dump(cfg, sort_keys=False))


def node_id() -> str:
    """A permanent id for this tttlog install (tells networked stations apart)."""
    try:
        v = NODE_ID_FILE.read_text().strip()
        if len(v) >= 8:
            return v
    except OSError:
        pass
    import uuid
    v = uuid.uuid4().hex
    NODE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    NODE_ID_FILE.write_text(v)
    return v


def load_colors() -> dict:
    out = {k: dict(v) for k, v in DEFAULT_COLORS.items()}
    if COLORS_FILE.exists():
        for k, v in (yaml.safe_load(COLORS_FILE.read_text()) or {}).items():
            if k in out and isinstance(v, dict):
                out[k].update(v)
    return out


def save_colors(c: dict) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    COLORS_FILE.write_text(yaml.safe_dump(c, sort_keys=False))


def expand(text: str, station: Station, call: str, exch: str, rst: str = "59",
           zone: str | None = None) -> str:
    return (text.replace("{MYCALL}", station.call).replace("{CALL}", call)
            .replace("{EXCH}", exch).replace("{RST}", rst)
            .replace("{STATE}", station.state).replace("{ZONE}", str(station.cq_zone) if zone is None else zone))


def load_keyer() -> dict:
    cfg = dict(DEFAULT_KEYER)
    if KEYER_FILE.exists():
        cfg.update(yaml.safe_load(KEYER_FILE.read_text()) or {})
    return cfg


def save_keyer(cfg: dict) -> None:
    KEYER_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYER_FILE.write_text(yaml.safe_dump(cfg, sort_keys=False))


# N1MM-compatible UDP (core/n1mm.py): RadioInfo for band decoders / GH Everyware band
# following, and rotor commands (GH Everyware, N1MM-compatible rotor programs).
N1MM_FILE = CONFIG_DIR / "n1mm.yaml"
DEFAULT_N1MM = {
    "radio": False,                       # send RadioInfo
    "radio_targets": "127.0.0.1:12060",   # host:port, several with spaces
    "rotor": False,                       # send rotor turn / stop (Alt+J, Alt+L, Ctrl+Alt+J)
    "rotor_targets": "127.0.0.1:12040",
    "rotor_name": "",                     # blank = every rotor that's ticked in GH Everyware
    "bidirectional": False,
}


def load_n1mm() -> dict:
    cfg = dict(DEFAULT_N1MM)
    if N1MM_FILE.exists():
        cfg.update(yaml.safe_load(N1MM_FILE.read_text()) or {})
    return cfg


def save_n1mm(cfg: dict) -> None:
    N1MM_FILE.parent.mkdir(parents=True, exist_ok=True)
    N1MM_FILE.write_text(yaml.safe_dump(cfg, sort_keys=False))


# HamQTH callbook (free account at hamqth.com): the other station's grid square,
# for beam headings. Kept in its own file, readable only by you.
CALLBOOK_FILE = CONFIG_DIR / "callbook.yaml"
DEFAULT_CALLBOOK = {"enabled": False, "user": "", "password": ""}


def load_callbook() -> dict:
    cfg = dict(DEFAULT_CALLBOOK)
    if CALLBOOK_FILE.exists():
        cfg.update(yaml.safe_load(CALLBOOK_FILE.read_text()) or {})
    return cfg


def save_callbook(cfg: dict) -> None:
    CALLBOOK_FILE.parent.mkdir(parents=True, exist_ok=True)
    CALLBOOK_FILE.write_text(yaml.safe_dump(cfg, sort_keys=False))
    try:
        CALLBOOK_FILE.chmod(0o600)          # the password is in here
    except OSError:
        pass
