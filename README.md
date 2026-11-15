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
python3.12 -m venv ~/.venvs/tttlog && ln -s ~/.venvs/tttlog .venv   # see note below
source .venv/bin/activate
pip install -e ".[dev]"
python scripts/update_cty.py            # latest country file (run before every contest)
python -m tttlog                        # or just: tttlog
```

> **Mac with iCloud Drive syncing Documents:** keep the venv outside the synced folder (as above).
> iCloud marks files inside a synced `.venv` as hidden, and Qt then can't find its platform plugin ("Could not find the Qt platform plugin cocoa").

Windows and Linux use the same steps (Windows: `.venv\Scripts\activate`).

Optional: put a `MASTER.SCP` file in `data/` to get Super Check Partial suggestions.

## Alpha testers (no Python needed)

Every pull request and push to `main` builds a Windows zip on GitHub (Actions ▸ "Windows build" ▸ the run ▸ Artifacts ▸ `tttlog-windows`).
Testers unzip it and double-click `tttlog.exe`. The zip includes `README-FIRST.txt` ([docs/TESTERS.md](docs/TESTERS.md)) with first-run steps and how to report bugs.
To build one yourself on Windows: `pip install pyinstaller`, `python scripts/update_cty.py`, then `python scripts/build_app.py`. The zip lands in `dist/`.
The same script builds a macOS or Linux version on those systems.

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

| **Ctrl+K** | Connect / disconnect the DX cluster |
| **F11** / **Ctrl+Shift+S** | Spot the last QSO (call + frequency) to the cluster |
| **Ctrl+G** | Go to the newest needed spot (mults first, then Qs) |
| **Ctrl+Shift+N / M / A** | Spots filter: mults + Qs / mults only / everything |
| **Ctrl+Shift+H / R** | Minimize (roll up) all panes / restore them |
| **Ctrl+Shift+F** | Search spots (call, country, or comment) |
| Double-click a spot | QSY, switch to S&P, put the call in the entry line |

(On a Mac, Ctrl is ⌘.)

The banner under the entry line goes red for a **DUPE**, green for a **NEW MULT**, and yellow for **not valid / bad exchange**.
## Windows (panes)

Log, Score, Check Partial, Rate, Needed, Spots, and Telnet are panes. Each title bar has three buttons:

- **–** minimizes the pane: it rolls up to just its title bar. Click **+** to bring it back.
- **⧉** pops the pane out into its own window, which has the normal minimize, zoom, and close buttons. **⇲** (or double-clicking the title bar) docks it back.
- **×** closes it. Reopen it from the View menu.

View ▸ Minimize all panes, Restore all panes, and Dock all pop-out windows act on every pane at once. You can also drag panes to rearrange them or stack them as tabs. The layout is remembered.

## Rate pane

Shows the rate over the last 10 and last 100 QSOs (per hour, measured to now), the QSO counts for the last 60 and last 15 minutes, and the best 60-minute run so far.
The table below lists each clock hour: QSOs per band, the total, and the new mults worked that hour. Dupes and QSOs that don't count are left out.

## DX cluster

Config ▸ DX cluster… sets the telnet host and port (default `w3lpl.net:7373`), the login call (blank uses your station call), how long to keep spots, auto-connect on start, and commands to send after login (for example `set/skimmer; sh/dx 30`).
If the link drops, tttlog reconnects every 30 seconds.

The cluster has two windows:

- **Spots**: the stations you can work. Tick which kinds to show (**Mults**, **Qs**, **Dupes / can't work**) and click a swatch to pick its color.
- **Telnet**: the raw cluster text, the Connect button, and a box for typing cluster commands. You can close or minimize it; the connection keeps running and Spots keeps filling.

Each spot is checked against your log and the contest rules:

- **MULT** (green): working this station adds a multiplier on that band. The Need column says which mult.
- **Q**: a new QSO that counts, but adds no mult.
- **DUPE** / **INVALID**: already worked on that band, or not allowed in this contest (wrong band, wrong mode such as a CW-segment or FT8 spot in a phone contest, or a station you can't work, such as W/VE in ARRL DX).

Spots are re-checked after every QSO, edit, and delete, so a mult disappears from the list as soon as you work it.
The band filter (all bands / current band) and the search box narrow the list further. The status line shows how many mults and Qs are available right now.
Double-clicking a spot jumps to it. (Rig control in M1 will also tune the radio.)

**Spotting:** **F11 Spot** (on every F-key page), the **Spot last QSO** button, or Cluster ▸ Spot last QSO (Ctrl+Shift+S) sends `DX <kHz> <call>` for your most recent QSO, with no comment.
Turn on **Cluster ▸ Auto-spot S&P QSOs** (also in Config ▸ DX cluster) to spot every new S&P QSO as you log it. Run QSOs, dupes, and stations you've already spotted on that band this session are skipped.
Check your contest category before spotting: many contests don't allow spotting in some categories, and self-spotting is never allowed.

## Needed window

A grid of every possible mult (every DXCC entity, or CQ zones 1–40) against each contest band. Each cell is in one of four states, each with a checkbox and a color you can change:

| State | Meaning | Default |
|---|---|---|
| **Needed & spotted** ● | not worked on that band, and spotted right now | green |
| **Needed** | not worked on that band, not spotted | salmon |
| **Worked & spotted** ✓● | already have it, but it's being spotted | light blue |
| **Worked** ✓ | already have it | grey |

Unticking a state hides those cells, and hides any row left with nothing to show. Ticking only **Needed & spotted** gives a short list of mults you can go work now.
The drop-down switches between mult types (for example Zones and Countries in CQWW), and the search box filters by prefix, country, or zone. Double-click a spotted cell to go to the newest spot for it.
Colors and checkbox choices are saved in `~/.tttlog/colors.yaml`.

## General log

File ▸ New log ▸ **General log** is for everyday QSOs outside contests. It's one log file (`general_log.db`) you keep adding to.
- No dupes: work anyone again. The banner says **Worked 2× — last 2026-11-01 20m SSB HANS…** instead.
- A new country shows **NEW ONE**, and the Spots and Needed windows treat new countries as the "mults". The score line shows QSOs and DXCC count.
- The Rcvd box is free text (name, QTH, notes) and can be left empty: type the call and press Enter to log.
- Modes: SSB, CW, FT8, FT4, RTTY, AM, FM (Operating ▸ Mode, or type the mode in the call box and press Enter). The RST default follows the mode (59 / 599 / -10).
- Bands: 160m–6m plus 2m and 70cm.
- Export ADIF puts the notes in COMMENT for LoTW / QRZ / Club Log; Cabrillo is only for contests.

## Local network (multi-op / several computers)

Several tttlog computers in the shack can share one log. Set it up on each computer with Config ▸ Local network:
1. Tick **Share the log**, give each computer its own station name (RUN1, MULT, …), and use the same network name on all of them.
2. Open a log for the same contest on each computer (an empty new log is fine: it fills in from the others).

Stations find each other with a UDP broadcast (port 12070) and link over TCP (port 12071). If they can't find each other (different subnet, a VM behind NAT, broadcasts blocked), list the other computers under **Other stations by address**, for example `192.168.1.20`. On Windows, allow tttlog through the firewall on Private networks when asked.

What's shared:
- Every QSO, edit, and delete, as it happens. Dupes and mults count across all stations; the banner says **DUPE on 20m (worked by RUN1)**. The Log pane's **Stn** column shows who logged each QSO.
- Each station keeps a full copy. A station that drops out (or a PC that reboots) catches up when it's back, and QSOs logged while it was cut off go to the others too. If two stations edit the same QSO while cut off, the newer edit wins on every station.
- The **Network** pane lists each station's operator, band, frequency, mode, Run/S&P, and QSO count. A station on your band and mode is highlighted, and a clock more than a minute off is flagged. The box at the bottom sends talk messages to all stations.

The network name keeps separate groups apart; it isn't a password. Use it only on a network you trust.

## Contests

Each contest is one YAML file in `tttlog/contests/rules/`. Add a new file to add a contest; nothing needs recompiling.

Included: `GENERAL` (everyday log), `ARRL-DX-SSB` (W/VE side), `CQ-WW-SSB`, `CQ-WW-CW`.

## Your settings

Settings live in `~/.tttlog/`:
- `station.yaml`: call, state, zones, club, and Cabrillo header info (Config ▸ Station profile)
- `macros.yaml`: F-keys (Config ▸ Function-key macros). Besides the text fields, `{CLEAR}` wipes the entry line and `{SPOT}` spots the last QSO, so you can put Spot on any key.
- `cluster.yaml`: DX cluster host, login, and options (Config ▸ DX cluster)
- `colors.yaml`: colors and checkboxes for the Needed and Spots windows
- `network.yaml`: local network settings (Config ▸ Local network); `node_id` tells this install apart from the other stations

## Safety

Every QSO is written to an fsync'd `.journal` file next to the `.db` *before* the database commit.
If the database is ever damaged, `Log.recover_from_journal()` rebuilds it.

## Roadmap

- **M1 (Dec):** rig control (Hamlib rigctld + native Yaesu CAT for FTDX-10), voice keyer (WAV through the radio's USB audio + CAT PTT)
- **M2 (Jan):** DX cluster + bandmap, N1MM-format UDP broadcast (World Radio League, etc.), online scoreboard posting
- **M3 (Feb):** Windows/Linux builds, a full dry run
- Later: SO2R, more contests

## License

GPL-3.0-or-later. See `LICENSE`.
