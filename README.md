# tttlog

A one-window amateur radio contest logger for **macOS, Windows, and Linux**.
Keyboard-first, with contest rules kept in files, and built so you never lose a QSO.

> Status: **v0.2.0.** Logging, dupe and multiplier checks, scoring, editable F-keys, ADIF/Cabrillo export, version info, and in-app updates all work.
> Rig control and the voice keyer come in M1. First live target: **ARRL DX SSB, March 6–7, 2027**.

## Install (macOS: the easy way)

1. Download the `.dmg` from **[Releases](https://github.com/n3ttt/tttlog/releases/latest)**.
   Pick `macos-arm64` for Apple Silicon (M1–M4) or `macos-x86_64` for Intel Macs.
2. Open the DMG and drag **tttlog** into **Applications**.
3. **First launch only:** the app isn't signed with an Apple Developer ID yet, so macOS will block it.
   Open it once, then go to **System Settings ▸ Privacy & Security**, scroll down, and click **Open Anyway**.
   After that it opens normally, and in-app updates won't ask again.

On first run the app downloads the country file (`cty.dat`) and `MASTER.SCP` by itself.

Windows (`.zip`) and Linux (`.tar.gz`) builds are on the same Releases page.

## Version & updates

- **Help ▸ About tttlog** shows the version (and the git commit when running from source). `tttlog --version` prints it too.
- tttlog checks GitHub once a day and offers updates. You can also check any time with **Help ▸ Check for updates…**
  - **Mac app:** downloads the new DMG, swaps the app, and reopens it.
  - **Running from source:** does `git pull` and reinstalls, then offers to restart.
  - **Windows/Linux:** downloads the new build to your Downloads folder.
- **Tools ▸ Update country files** refreshes `cty.dat` and `MASTER.SCP`. Do this before every contest.

## Run from source (developers)

```bash
git clone https://github.com/n3ttt/tttlog.git && cd tttlog
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m tttlog
```

## Making a release

Bump `__version__` in `tttlog/__init__.py`, commit, then:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

GitHub Actions runs the tests, builds the Mac (Apple Silicon + Intel), Windows, and Linux apps, and publishes the release.
Running copies will then offer the update.

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

Settings and downloaded data live in `~/.tttlog/` (`data/` holds cty.dat and MASTER.SCP). Logs are saved in `~/Documents/tttlog/`.
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
