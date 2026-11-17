#!/bin/sh
# Installs tttlog for the current user (no root needed):
#   - copies the AppImage to ~/.local/bin/tttlog
#   - adds tttlog to the applications menu
# Run it from the folder you unpacked:   sh install-linux.sh
# Uninstall:                             sh install-linux.sh --uninstall
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

if [ "$1" = "--uninstall" ]; then
    rm -f "$BIN/tttlog" "$APPS/tttlog.desktop" "$ICONS/tttlog.svg"
    echo "tttlog removed. Your logs (Documents/tttlog) and settings (~/.tttlog) were kept."
    exit 0
fi

APPIMAGE="$(ls "$HERE"/tttlog-*.AppImage 2>/dev/null | head -n 1)"
if [ -z "$APPIMAGE" ]; then
    echo "No tttlog-*.AppImage next to this script." >&2
    exit 1
fi
mkdir -p "$BIN" "$APPS" "$ICONS"
cp "$APPIMAGE" "$BIN/tttlog"
chmod +x "$BIN/tttlog"
cp "$HERE/tttlog.svg" "$ICONS/tttlog.svg"
sed "s|^Exec=.*|Exec=$BIN/tttlog|" "$HERE/tttlog.desktop" > "$APPS/tttlog.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "Installed: $BIN/tttlog"
echo "Start it from your applications menu (tttlog), or run:  tttlog"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "(Add $BIN to your PATH to start it by name from a terminal.)";; esac
