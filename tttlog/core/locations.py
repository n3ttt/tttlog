"""Lists contest exchanges are checked against, and that some multipliers count:
ARRL/RAC sections, US states, Canadian provinces and territories.

Check these against the current contest rules before a contest: ARRL adds or renames
a section now and then.
"""
from __future__ import annotations

# ARRL and RAC sections (85), by division
ARRL_SECTIONS = [
    # Atlantic
    "DE", "EPA", "MDC", "NNJ", "NNY", "SNJ", "WNY", "WPA",
    # Central
    "IL", "IN", "WI",
    # Dakota
    "MN", "ND", "SD",
    # Delta
    "AR", "LA", "MS", "TN",
    # Great Lakes
    "KY", "MI", "OH",
    # Hudson
    "ENY", "NLI", "NYC",
    # Midwest
    "IA", "KS", "MO", "NE",
    # New England
    "CT", "EMA", "ME", "NH", "RI", "VT", "WMA",
    # Northwestern
    "AK", "EWA", "ID", "MT", "OR", "WWA",
    # Pacific
    "EB", "NV", "PAC", "SCV", "SF", "SJV", "SV",
    # Roanoke
    "NC", "SC", "VA", "WV",
    # Rocky Mountain
    "CO", "NM", "UT", "WY",
    # Southeastern
    "AL", "GA", "NFL", "PR", "SFL", "VI", "WCF",
    # Southwestern
    "AZ", "LAX", "ORG", "SB", "SDG",
    # West Gulf
    "NTX", "OK", "STX", "WTX",
    # Canada (RAC)
    "AB", "BC", "GH", "MAR", "MB", "NL", "NT", "ONE", "ONN", "ONS", "PE", "QC", "SK",
]

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY",
]
DC = ["DC"]
CA_PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]

LISTS: dict[str, list[str]] = {
    "sections": ARRL_SECTIONS,
    "states": US_STATES,
    "states_dc": US_STATES + DC,
    "provinces": CA_PROVINCES,
    "states_provinces": US_STATES + DC + CA_PROVINCES,
    "states_provinces_nodc": US_STATES + CA_PROVINCES,
}

# Entities that count as "W/VE" (home) in ARRL domestic contests
W_VE = ["United States", "Canada", "Alaska", "Hawaii"]


def values(name: str) -> list[str]:
    """A named list (sections, states...); KeyError if there's no such list."""
    return LISTS[name]
