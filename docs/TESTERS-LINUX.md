tttlog alpha: how to install and try it (Linux)
===============================================

Thanks for testing! tttlog is an early (alpha) contest and general
logger. It's safe to try, but please don't rely on it as your only log in
a real contest yet. Nothing else needs to be installed: no Python.
Works on 64-bit Intel/AMD Linux with a desktop (Ubuntu 22.04 or newer,
Debian 12, Fedora, Mint, ...).


1. Install
----------
In the folder you unpacked, run:

    sh install-linux.sh

That puts tttlog in ~/.local/bin and adds it to your applications menu.
No root password needed. To remove it later:  sh install-linux.sh --uninstall

Or don't install at all: the .AppImage file is the whole program.
Make it runnable and double-click it (or run it from a terminal):

    chmod +x tttlog-*.AppImage
    ./tttlog-*.AppImage

If it says something about FUSE, run it like this instead:

    ./tttlog-*.AppImage --appimage-extract-and-run

(or install FUSE: on Ubuntu,  sudo apt install libfuse2 )


2. First run
------------
1. Config > Station profile: enter your call, state, and CQ zone.
2. File > New log: pick a contest, or "General log" for everyday QSOs.
   Logs go in ~/Documents/tttlog unless you choose another folder.
3. Type a call, press Space to jump to the exchange, press Enter to log.
   Typing a frequency in kHz (for example 14250) + Enter changes frequency.
   Typing OPON + Enter (or OPON K3ABC) changes who is operating.
   FT8/FT4: Config > WSJT-X, tick it, and set WSJT-X's Settings > Reporting >
   UDP Server to 127.0.0.1 port 2237. QSOs you log in WSJT-X go into tttlog.
4. Optional DX cluster: Config > DX cluster, then Cluster > Connect (Ctrl+K).
   Spotting (F11) sends a real spot everyone sees, so only spot real QSOs.
5. Several computers (multi-op): Config > Local network on each one, same
   network name, different station names, same contest. If your firewall
   blocks it, allow TCP 12071 and UDP 12070 on the local network.
   Ubuntu with ufw on:

       sudo ufw allow from 192.168.0.0/16 to any port 12071 proto tcp
       sudo ufw allow from 192.168.0.0/16 to any port 12070 proto udp


3. Not in this version yet
--------------------------
- Radio (CAT) control and the voice/CW keyer.
- Contests: ARRL DX SSB (W/VE side), CQ WW SSB, CQ WW CW, plus the General log.


4. Where your files are
-----------------------
- Logs:      ~/Documents/tttlog/*.db  (with a .journal backup next to each)
- Settings:  ~/.tttlog/
- Export:    File > Export Cabrillo / Export ADIF


5. Reporting problems
---------------------
Please send what you did, what you expected, what happened, Help > About,
your distro and desktop (for example "Ubuntu 24.04, GNOME, Wayland"), and a
screenshot if it's about how something looks. If it won't start, run it
from a terminal and send what it prints.

73 and thanks!
