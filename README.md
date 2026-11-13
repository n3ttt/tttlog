# tttlog

A one-window amateur radio contest logger for **macOS, Windows, and Linux**.
Keyboard-first, with contest rules kept in files, and built so you never lose a QSO.

> Status: **v0.1, milestone M0.** Logging, dupe and multiplier checks, scoring, editable F-keys, and ADIF/Cabrillo export all work.
> Rig control and the voice keyer come in M1. First live target: **ARRL DX SSB, March 6–7, 2027**.

## Quick start (macOS)

```bash
brew install python@3.12 git            # skip if already installed
git clone https://github.com/n3ttt/<repo>.git
cd <repo>
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/update_cty.py            # latest country file (run before every contest)
python -m tttlog                        # or just: tttlog
```

Windows and Linux use the same steps (Windows: `.venv\Scripts\activate`).

Optional: put a `MASTER.SCP` file in `data/` to get Super Check Partial suggestions.

## Operating

| Key | Action |
|---|---|
| Type call → **Space** | Jump to exchange (fills in the CQ zone when the contest uses one) |
| **Enter** | ESM: empty call → F1 · call but no exchange → F2 · complete → log + F3 (Run) |
| Type `14250` in Call → Enter | Change frequency (until rig control lands) |
| **F1–F12** | Macros; the set changes with mode (SSB/CW) and Run/S&P |
| **Ctrl+R** | Toggle Run / S&P |
| **Ctrl+F** | Set frequency |
| **Esc** | Wipe the entry line |
| Double-click a log row | Edit QSO |
| **Ctrl+D** | Delete the selected QSO |

The banner under the entry line goes red for a **DUPE**, green for a **NEW MULT**, and yellow for **not valid / bad exchange**.
Panes (Log, Score, Check Partial) can be docked, floated, or hidden. The layout is remembered.

## Contests

Each contest is one YAML file in `tttlog/contests/rules/`. Add a new file to add a contest; nothing needs recompiling.

Included: `ARRL-DX-SSB` (W/VE side), `CQ-WW-SSB`, `CQ-WW-CW`.

## Your settings

Settings live in `~/.tttlog/`:
- `station.yaml`: call, state, zones, club, and Cabrillo header info (Config ▸ Station profile)
- `macros.yaml`: F-keys (Config ▸ Function-key macros)

## Safety

Every QSO is written to an fsync'd `.journal` file next to the `.db` *before* the database commit.
If the database is ever damaged, `Log.recover_from_journal()` rebuilds it.

## Roadmap

- **M1 (Dec):** rig control (Hamlib rigctld + native Yaesu CAT for FTDX-10), voice keyer (WAV through the radio's USB audio + CAT PTT)
- **M2 (Jan):** DX cluster + bandmap, N1MM-format UDP broadcast (World Radio League, etc.), online scoreboard posting
- **M3 (Feb):** Windows/Linux builds, a full dry run
- Later: SO2R, multi-op networking, more contests

## License

GPL-3.0-or-later. See `LICENSE`.
