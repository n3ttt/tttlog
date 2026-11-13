tttlog alpha: how to install and try it (Windows)
=================================================

Thanks for testing! tttlog is an early (alpha) contest logger. It's safe to
try, but please don't rely on it as your only log in a real contest yet.
Nothing else needs to be installed: no Python, no extra downloads.


1. Install
----------
1. Unzip the file you were sent (right-click it > Extract All...).
   Put the "tttlog" folder somewhere you'll find it again, such as
   Documents or the Desktop.
2. Open the "tttlog" folder and double-click  tttlog.exe
   (Tip: right-click tttlog.exe > Send to > Desktop (create shortcut).)

Windows may say "Windows protected your PC". That's because this test
version isn't signed yet. Click "More info", then "Run anyway".
You only have to do this once.

To uninstall, delete the tttlog folder. Your logs and settings are kept
(see "Where your files are" below).


2. First run
------------
1. Config > Station profile: enter your call, state, and CQ zone.
2. File > New contest log: pick the contest. Logs go in
   Documents\tttlog unless you choose another folder.
3. Type a call, press Space to jump to the exchange, press Enter to log.
   Typing a frequency in kHz (for example 14250) + Enter changes frequency.
4. Optional DX cluster: Config > DX cluster (default w3lpl.net, port 7373,
   logs in with your call), then Cluster > Connect (Ctrl+K).
   Spotting (F11 or Ctrl+Shift+S) sends a real spot that everyone on the
   cluster sees, so only spot real QSOs.

Before a contest, use File > Update country file to get the latest
country list.

Windows: every pane has  –  (roll up),  ⧉  (pop out into its own window)
and  ×  (close; bring it back from the View menu). Drag panes to rearrange
them. Help > About shows the version and where files are kept.


3. Not in this version yet
--------------------------
- Radio (CAT) control and the voice/CW keyer: the frequency is typed in,
  and F-keys only show what would be sent.
- Only these contests: ARRL DX SSB (W/VE side), CQ WW SSB, CQ WW CW.


4. Where your files are
-----------------------
- Logs:      Documents\tttlog\*.db  (with a .journal backup next to each)
- Settings:  C:\Users\<you>\.tttlog\
- Export:    File > Export Cabrillo / Export ADIF


5. Reporting problems
---------------------
Please send:
- what you did, what you expected, and what happened instead
- Help > About (the version line and file locations)
- a screenshot if it's about how something looks
- if it's about scoring or a lost QSO, the .db and .journal files from
  Documents\tttlog

73 and thanks!
