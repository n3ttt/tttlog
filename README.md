# tttlog

A one-window amateur radio contest logger for **macOS, Windows, and Linux**.
Keyboard-first, with contest rules kept in files, and built so you never lose a QSO.

> Status: **v0.1, milestone M0.** Logging, dupe and multiplier checks, scoring, editable F-keys, and ADIF/Cabrillo export all work.
> Rig control, the voice keyer and CW keying are in (M1) and still being tried on real radios. First live target: **ARRL DX SSB, March 6–7, 2027**.

## Install on a Mac (no Python needed)

1. Download the `.dmg` from **[Releases](https://github.com/n3ttt/tttlog/releases)**: `macos-arm64` for Apple Silicon (M1–M4), `macos-x86_64` for Intel.
2. Open it and drag **tttlog** into **Applications**.
3. **First launch only:** macOS blocks apps without an Apple Developer ID. Open tttlog once, then go to **System Settings ▸ Privacy & Security**, scroll down, and click **Open Anyway**.

## Version & updates

- **Help ▸ About tttlog** shows the version (and the git commit when running from source). `tttlog --version` prints it too.
- tttlog checks GitHub once a day. **Help ▸ Check for updates…** checks right away.
  - **Mac app:** **Update now** downloads the new DMG, replaces the app, and reopens it.
  - **From source (git clone):** does `git pull` + reinstall, then offers to restart.
  - **Windows / Linux:** downloads the new build to Downloads.

### Making a release
Bump `__version__` in `tttlog/__init__.py` and commit to `main`. Then on GitHub: **Releases ▸ Draft a new release**, tag `v<version>` (e.g. `v0.1.0a3`), tick **Set as a pre-release** for alphas, and **Publish**.
The **Release** workflow tests and builds Mac (both chips), Windows, and Linux, and attaches them to the release (about 15 minutes).

## Run from source (macOS)

```bash
brew install python@3.12 git            # skip if already installed
git clone https://github.com/n3ttt/tttlog.git
cd tttlog
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

Every pull request and push to `main` builds a Windows zip on GitHub (Actions ▸ "Windows build" ▸ the run ▸ Artifacts ▸ `tttlog-<version>-windows.zip`, one zip to extract). Released versions are on the [Releases](https://github.com/n3ttt/tttlog/releases) page.
Testers unzip it and double-click `tttlog.exe`. The zip includes `README-FIRST.txt` ([docs/TESTERS.md](docs/TESTERS.md)) with first-run steps and how to report bugs.
To build one yourself on Windows: `pip install pyinstaller`, `python scripts/update_cty.py`, then `python scripts/build_app.py`. The zip lands in `dist/`.
Linux works the same way (Actions ▸ "Linux build" ▸ Artifacts ▸ `tttlog-<version>-linux-x86_64.tar.gz`): a `.tar.gz` with one `tttlog-<version>-x86_64.AppImage` (the whole program in one file) and `install-linux.sh`, which adds it to the applications menu without root. Instructions: [docs/TESTERS-LINUX.md](docs/TESTERS-LINUX.md).
To build it on Linux: `python scripts/build_app.py`, then `APPIMAGETOOL=/path/to/appimagetool sh scripts/build_appimage.sh`.
The same `build_app.py` builds a macOS version on a Mac.

## Operating

| Key | Action |
|---|---|
| Type call → **Space** | Jump to exchange (fills in the CQ zone when the contest uses one) |
| **Enter** | ESM: empty call → F1 · call but no exchange → F2 · complete → log + F3 (Run) |
| Type `14250` in Call → Enter | Change frequency (until rig control lands) |
| **F1–F12** | Macros; the set changes with mode (SSB/CW) and Run/S&P. SSB plays the key's recording, CW sends the text (see Voice & CW keyer) |
| **Ctrl+Shift+F1–F12** | Record that key's voice message (press again or Esc to stop) |
| Right-click an F-key button | Edit that key (label, text, voice file), record or play its message, or edit all keys |
| **PgUp / PgDn** | CW speed ±2 wpm |
| **Ctrl+R** | Toggle Run / S&P |
| **Ctrl+F** | Set frequency |
| **Esc** | Stop sending (or recording); when nothing is being sent, wipe the entry line |
| Double-click a log row | Edit QSO |
| **Ctrl+D** | Delete the selected QSO |

| **Ctrl+K** | Connect / disconnect the DX cluster |
| **F11** / **Ctrl+Shift+S** | Spot the last QSO (call + frequency) to the cluster |
| **Ctrl+G** | Go to the newest needed spot (mults first, then Qs) |
| **Ctrl+Shift+N / M / A** | Spots filter: mults + Qs / mults only / everything |
| **Ctrl+Shift+J** | Spotters: anywhere → my CQ zone → my continent |
| **Ctrl+Shift+K** | Skimmer spots: all → none → skimmers only |
| **Ctrl+Shift+L** | Send the spot filter to the cluster |
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

Panes don't have to fill the window. Drag the inner edge of the left or right column (Log, Spots, Rate, Needed...) to make it smaller, and the window keeps an empty area in the middle. Drag the edge back to close the gap. To go back to panes always filling the window, untick View ▸ Leave empty space.

## Rate pane

Shows the rate over the last 10 and last 100 QSOs (per hour, measured to now), the QSO counts for the last 60 and last 15 minutes, and the best 60-minute run so far.
The table below lists each clock hour: QSOs per band, the total, and the new mults worked that hour. Dupes and QSOs that don't count are left out.

## DX cluster

Config ▸ DX cluster… sets the telnet host and port (default `w3lpl.net:7373`), the login call (blank uses your station call), how long to keep spots, auto-connect on start, and commands to send after login (for example `set/skimmer; sh/dx 30`).
If the link drops, tttlog reconnects every 30 seconds.

The cluster has two windows:

- **Spots**: the stations you can work. Tick which kinds to show (**Mults**, **Qs**, **Dupes / can't work**) and click a swatch to pick its color.
- **Telnet**: the raw cluster text, the Connect button, a box for typing cluster commands (↑ / ↓ bring back earlier ones), and 12 command buttons across the bottom, as in N1MM. You can close or minimize it; the connection keeps running and Spots keeps filling.

**Command buttons:** SH/DX (last 30), DX of call, WWV, Sun, Filter?, Users, Skimmer on / off, Heading, QRZ, Reconnect, Bye. Right-click a button (or the cluster text) to edit them or hide them. Each button has a label and a command; in the command, `{MYCALL}` is your call, `{CALL}` the call in the entry line (or your last QSO's), `{FREQ}` your frequency in kHz, and `{CONN}` reconnects. Put `|` between commands to send several from one button (`SH/DX 30 | SH/WWV`). Commands differ a little between cluster programs (AR-Cluster, CC Cluster, DXSpider), so change any your cluster doesn't know. The buttons are saved in `cluster.yaml`.

Each spot is checked against your log and the contest rules:

- **MULT** (green): working this station adds a multiplier on that band. The Need column says which mult.
- **Q**: a new QSO that counts, but adds no mult.
- **DUPE** / **INVALID**: already worked on that band, or not allowed in this contest (wrong band, wrong mode such as a CW-segment or FT8 spot in a phone contest, or a station you can't work, such as W/VE in ARRL DX).

Spots are re-checked after every QSO, edit, and delete, so a mult disappears from the list as soon as you work it.
The band filter (all bands / current band) and the search box narrow the list further. The status line shows how many mults and Qs are available right now.
Double-clicking a spot jumps to it. (Rig control in M1 will also tune the radio.)

**Spotter and skimmer filter:** the **Filter** button in the Spots window (or Ctrl+Shift+J / Ctrl+Shift+K) picks which spots you see:
- spotters anywhere, in your CQ zone, on your continent, in your country, or in CQ zones you choose (e.g. 3,4,5);
- skimmer (RBN, `CALL-#`) and human spots, no skimmer spots, or skimmer spots only.

The filter works here, on any cluster and on spots shared over the network. The button shows **Filter ●** while one is on, and the status line counts what's hidden. Spots whose spotter can't be placed are kept.
**Send this filter to the cluster** (Ctrl+Shift+L) also asks the node itself to send less, so a busy skimmer feed doesn't flood the line. tttlog works out the node software from its login banner, or you can set it in Config ▸ DX cluster:

| Cluster | My zone, no skimmers |
|---|---|
| AR-Cluster (W3LPL, K1TTT) | `set dx filter SpotterCqZone=5 and not skimmer` |
| DXSpider | `clear/spots all`, `accept/spots by_zone 5`, `unset/skimmer` |
| CC Cluster (VE7CC) | `set/noskimmer` (CC filters spotters by country only; zone and continent stay local) |

Tick **Keep the cluster's filter matched** in the Filter menu to send it every time you change the filter. Cluster ▸ Show the cluster's filter sends `sh/filter`.

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

Operators: type **OPON** + Enter in the call field (or **OPON K3ABC**, or Operating ▸ Operator on…, Ctrl+Shift+O) when someone sits down. New QSOs from that computer are logged under that operator, the top bar shows **OP K3ABC**, and the Network pane shows it to the other stations. The OPON operator is kept per computer; without OPON the operator from the station profile is used. The **Rate** pane lists each operator's QSOs, share, last-10 rate, last-60 count and best 60. Pick an operator under **Rates for** (or double-click their row) to see just their rates and hours. The Cabrillo OPERATORS line lists everyone who logged a QSO.

**Same contest check:** stations on different contests (or with no log open) still link, so talk, status, and the shared cluster keep working, but **their logs are not shared**. Both stations get an orange warning, for example *MULT is logging CQ-WW-SSB, you're on ARRL-DX-SSB*. The Network pane shows that station in red with **log not shared**. As soon as both open the same contest they relink and swap whatever is missing.

**One cluster connection for the shack:** only one computer needs to log in to the DX cluster. With **Share my cluster connection** on (Config ▸ DX cluster, on by default), its cluster text goes to the other stations. A station that isn't connected itself shows **Using RUN1's cluster connection** in its Telnet window and fills its Spots window from it. Commands typed there, spots (F11, auto-spot), and **Send filter to cluster** go out through the connected station's login. Each station keeps its own Spots filter. If more than one computer is connected, the others use the one with the lowest ID. A station can still connect itself (Ctrl+K), and then uses its own connection.

The network name keeps separate groups apart; it isn't a password. Use it only on a network you trust.

## Band buttons

The **Bands** column on the left has a button for each band in the open log's contest; the lit one is the band you're on. Clicking a band takes you back to where you last were on it in the same kind of mode (CW, SSB, digital...), or the first time to a usual spot (for example 14025 CW, 14250 SSB, 14074 FT8). For now this sets tttlog's frequency; with radio control it will tune the radio.

## Radio (CAT)

Config ▸ Radio… connects to the radio:
- **FlexRadio** through SmartSDR: on a Mac, SmartSDR for Mac's CAT port (Network, 127.0.0.1, port 5002); on Windows, a TCP port from SmartSDR CAT.
- **Kenwood / Elecraft** (Kenwood command set), over the network or a serial/USB port.
- **Yaesu** FTDX10 / FTDX101 / FT-710 / FT-991A over the radio's USB (Enhanced COM) port at its CAT RATE.

tttlog follows the radio: the frequency, band button and mode track the dial, and every QSO is logged on the radio's real frequency. The top bar shows **● Radio** (green when the radio answers).

By default tttlog **only reads** the radio and never changes it. In that mode, band buttons and typed frequencies are refused with a reminder to tune the radio, so a QSO can't be logged on a frequency the radio isn't on. Tick **Let tttlog tune the radio** to have band buttons, typed kHz, clicked spots and mode changes tune it. Digital modes show on the radio as DIGU / DATA-USB; tttlog keeps whichever of FT8 / FT4 you picked.

## US license privileges (band limits)

Set **US license class** in Config ▸ Station profile (Extra, Advanced, General, Technician, Novice; leave it at None for no limits). tttlog then uses the FCC Part 97 privileges for that class, HF through 70 cm:
- A red **⚠ Outside General privileges: 20m phone is 14225–14350 kHz** banner whenever the radio or tttlog is somewhere you can't transmit in the current mode. It counts the whole signal: LSB needs 3 kHz below the dial, USB and data 3 kHz above, so 3802 LSB is "too close to the edge" for a General.
- **Band buttons** land inside your privileges (a General's 20m SSB button goes to 14226 at the lowest), and say so if the class has none for that mode on that band.
- The **voice and CW keyer won't transmit** outside your privileges.
- **Spots** you can't work are struck through, with the reason in the tooltip.

In a multi-op, each operator can have their own class: after **OPON**, set it in Operating ▸ Operator's license class (remembered on this computer). An operator without one uses the station's class.

## Voice & CW keyer

Config ▸ Voice & CW keyer… sets it up. Nothing is ever transmitted until you tick **Allow tttlog to transmit**.

**Recording (no other program needed):** press **Ctrl+Shift+F1** (etc.) in SSB, speak, and press it again or **Esc**. Or use the list of messages in Config ▸ Voice & CW keyer: pick one, **● Record**, **■ Stop**, **▶ Play here** to listen on this computer. Recordings are WAV files in `~/.tttlog/wav/<your call>/`, named in Config ▸ Function-key macros (WAV column); a key with no file gets one when you first record it. Up to 30 seconds each.

**Sending:** in SSB (and AM/FM), F-keys key the radio (PTT), play the recording to the radio's audio input, and unkey. In CW they send the macro text. **Esc** stops at once. A hard time limit (90 s, or the message length plus a few seconds) unkeys the radio if anything ever sticks, and closing tttlog releases PTT.

| Setting | FlexRadio (SmartSDR) | Yaesu FTDX10 | Kenwood / Elecraft |
|---|---|---|---|
| Audio to the radio | the DAX TX device; turn on DAX for the transmit slice | USB Audio CODEC; radio menu SSB MOD SOURCE = REAR | the radio's USB audio |
| PTT | Radio CAT command (`ZZTX1;`) | Radio CAT command (`TX1;`) | Radio CAT command (`TX1;`) |
| CW | Radio sends the text (`KY`) | DTR on the Standard COM port (radio menu PC KEYING = DTR); CAT can't send text | Radio sends the text (`KY`) |

**Cut numbers (CW):** by default the RST goes out as **5NN** instead of 599. In Config ▸ Voice & CW keyer pick None, 9 → N and 0 → T, 1 → A as well, or the full set (1 A, 2 U, 3 V, 5 E, 7 B, 8 D, 9 N, 0 T). Tick **Also in the exchange** to cut the zone or serial number too (zone 5 → E, serial 001 → TTA). The RST's first digit always stays a number, and callsigns are never cut. Only what's sent changes; the log keeps 599.

PTT can also be RTS or DTR on a keying serial port, or none (VOX). CW can also be a keyed DTR/RTS line on any radio (a USB keying interface, for example). The CW speed is set in the dialog and with PgUp/PgDn.

## WSJT-X (FT8 / FT4)

tttlog can log the QSOs you log in WSJT-X (or JTDX / MSHV). It only listens; it doesn't control WSJT-X.
1. In tttlog: Config ▸ WSJT-X…, tick **Log QSOs from WSJT-X**. The defaults (127.0.0.1, port 2237) match WSJT-X's.
2. In WSJT-X: File ▸ Settings ▸ Reporting ▸ **UDP Server** = 127.0.0.1, port 2237.

When you click **Log QSO** in WSJT-X, the QSO goes into the open tttlog log with its frequency, mode, reports and time, and to the other networked stations. In a general log the grid and name go in the notes. The top bar shows **● WSJT-X** while WSJT-X is heard (○ when it's quiet or closed). The same QSO sent twice is logged once.

If GridTracker or JTAlert already uses port 2237, set WSJT-X and every listening program (tttlog too) to a multicast address such as **224.0.0.1** so they all get each QSO.

## Contests

Each contest is one YAML file in `tttlog/contests/rules/`. Add a new file to add a contest; nothing needs recompiling.

Included: `GENERAL` (everyday log), `ARRL-DX-SSB` (W/VE side), `CQ-WW-SSB`, `CQ-WW-CW`.

## Your settings

Settings live in `~/.tttlog/`:
- `station.yaml`: call, state, zones, club, US license class, and Cabrillo header info (Config ▸ Station profile)
- `macros.yaml`: F-keys (Config ▸ Function-key macros). Besides the text fields, `{CLEAR}` wipes the entry line and `{SPOT}` spots the last QSO, so you can put Spot on any key.
- `cluster.yaml`: DX cluster host, login, and options (Config ▸ DX cluster)
- `colors.yaml`: colors and checkboxes for the Needed and Spots windows
- `keyer.yaml`: voice & CW keyer (Config ▸ Voice & CW keyer); recordings are in `wav/<your call>/`
- `network.yaml`: local network settings (Config ▸ Local network); `node_id` tells this install apart from the other stations

## Safety

Every QSO is written to an fsync'd `.journal` file next to the `.db` *before* the database commit.
If the database is ever damaged, `Log.recover_from_journal()` rebuilds it.

## Roadmap

- **M1 (Dec):** rig control — done: Flex (SmartSDR CAT), Kenwood/Elecraft, Yaesu CAT (FTDX10 still to try on the radio); voice keyer (record in tttlog, play through the radio's audio + PTT) and CW (CAT KY or DTR/RTS keying) — to try on the radios
- **M2 (Jan):** DX cluster + bandmap, N1MM-format UDP broadcast (World Radio League, etc.), online scoreboard posting
- **M3 (Feb):** Windows/Linux builds, a full dry run
- Later: SO2R, more contests

## License

GPL-3.0-or-later. See `LICENSE`.
