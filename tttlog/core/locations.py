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

# --- QSO party counties (from each party's official rules; check them before the party) ---

# Pennsylvania QSO Party: paqso.org county abbreviations (2026)
PA_COUNTIES = [
    "ADA", "ALL", "ARM", "BEA", "BED", "BER", "BLA", "BRA", "BUX", "BUT", "CMB", "CRN", "CAR", "CEN",
    "CHE", "CLA", "CLE", "CLI", "COL", "CRA", "CUM", "DAU", "DCO", "ELK", "ERI", "FAY", "FUL", "FOR",
    "FRA", "GRE", "HUN", "INN", "JEF", "JUN", "LAC", "LAN", "LAW", "LEB", "LEH", "LUZ", "LYC", "MCK",
    "MER", "MIF", "MOE", "MGY", "MTR", "NHA", "NUM", "PER", "PHI", "PIK", "POT", "SCH", "SNY", "SOM",
    "SUL", "SUS", "TIO", "UNI", "VEN", "WAR", "WAS", "WAY", "WES", "WYO", "YOR",
]

# New England QSO Party: neqp.org (rules updated 4/27/2026): state then county; CT uses
# its Regional Councils of Government since 2024
NEQP_COUNTIES = [
    "CTCAP", "CTGBR", "CTLCR", "CTNAU", "CTNOE", "CTNOW", "CTSOE", "CTSOC", "CTWES",
    "MEAND", "MEARO", "MECUM", "MEFRA", "MEHAN", "MEKEN", "MEKNO", "MELIN", "MEOXF", "MEPEN",
    "MEPIS", "MESAG", "MESOM", "MEWAL", "MEWAS", "MEYOR",
    "MABAR", "MABER", "MABRI", "MADUK", "MAESS", "MAFRA", "MAHMD", "MAHMP", "MAMID", "MANAN",
    "MANOR", "MAPLY", "MASUF", "MAWOR",
    "NHBEL", "NHCAR", "NHCHE", "NHCOO", "NHGRA", "NHHIL", "NHMER", "NHROC", "NHSTR", "NHSUL",
    "RIBRI", "RIKEN", "RINEW", "RIPRO", "RIWAS",
    "VTADD", "VTBEN", "VTCAL", "VTCHI", "VTESS", "VTFRA", "VTGRA", "VTLAM", "VTORA", "VTORL",
    "VTRUT", "VTWAS", "VTWNH", "VTWND",
]

# Delaware QSO Party: fsarc.org
DE_COUNTIES = ["NDE", "KDE", "SDE"]

# Maryland-DC QSO Party: rules revised 06 Aug 2024, table 1 (23 counties, Baltimore City, DC)
MDC_COUNTIES = [
    "ALY", "ANA", "BAL", "BCT", "CLV", "CLN", "CRL", "CEC", "CHS", "DRC", "FRD", "GAR", "HFD",
    "HWD", "KEN", "MON", "PGE", "QAN", "STM", "SMR", "TAL", "WAS", "WIC", "WRC", "WDC",
]

LISTS: dict[str, list[str]] = {
    "sections": ARRL_SECTIONS,
    "states": US_STATES,
    "states_dc": US_STATES + DC,
    "provinces": CA_PROVINCES,
    "states_provinces": US_STATES + DC + CA_PROVINCES,
    "states_provinces_nodc": US_STATES + CA_PROVINCES,
    "states_no_md": [x for x in US_STATES if x != "MD"],
    "dx": ["DX"],
    "pa_counties": PA_COUNTIES,
    "neqp_counties": NEQP_COUNTIES,
    "neqp_states": ["CT", "MA", "ME", "NH", "RI", "VT"],
    "de_counties": DE_COUNTIES,
    "mdc_counties": MDC_COUNTIES,
}

# Entities that count as "W/VE" (home) in ARRL domestic contests
W_VE = ["United States", "Canada", "Alaska", "Hawaii"]


def values(name) -> list[str]:
    """A named list (sections, states...), or several joined ([pa_counties, sections, dx]);
    KeyError if there's no such list."""
    if isinstance(name, (list, tuple)):
        out = []
        for n in name:
            out += LISTS[n]
        return out
    return LISTS[name]
