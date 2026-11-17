"""User settings: station profile + function-key macros (YAML in ~/.tttlog)."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import yaml

from .contests.engine import Station

from .paths import USER_DIR as CONFIG_DIR
STATION_FILE = CONFIG_DIR / "station.yaml"
MACROS_FILE = CONFIG_DIR / "macros.yaml"

# Macro text: {MYCALL} {CALL} {EXCH} {RST} {STATE} {ZONE} are substituted.
# SSB: text is shown + the WAV file (in ~/.tttlog/wav/<MYCALL>/) is played by
# the voice keyer (milestone M1). CW: text is sent by the keyer.
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
            {"key": "F11", "label": "Spare", "text": "", "wav": ""},
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
            {"key": "F11", "label": "Spare", "text": "", "wav": ""},
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
            {"key": "F11", "label": "Spare", "text": ""},
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
            {"key": "F11", "label": "Spare", "text": ""},
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
    return DEFAULT_MACROS


def save_macros(m: dict) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    MACROS_FILE.write_text(yaml.safe_dump(m, sort_keys=False))


def expand(text: str, station: Station, call: str, exch: str, rst: str = "59") -> str:
    return (text.replace("{MYCALL}", station.call).replace("{CALL}", call)
            .replace("{EXCH}", exch).replace("{RST}", rst)
            .replace("{STATE}", station.state).replace("{ZONE}", str(station.cq_zone)))
