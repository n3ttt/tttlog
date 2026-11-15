#!/bin/sh
# Turn the PyInstaller folder (dist/tttlog, from scripts/build_app.py) into
# one Linux AppImage, and pack it with the installer script:
#   dist/tttlog-<version>-x86_64.AppImage
#   dist/tttlog-<version>-linux-x86_64.tar.gz   (AppImage + install-linux.sh + icon + .desktop)
# Needs appimagetool; set APPIMAGETOOL to its path (the CI job downloads it).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(python3 -c "import re,sys; print(re.search(r'__version__ = \"(.+?)\"', open(sys.argv[1]).read()).group(1))" "$ROOT/tttlog/__init__.py")"
ARCH="$(uname -m)"
TOOL="${APPIMAGETOOL:-appimagetool}"
APPDIR="$ROOT/build/AppDir"
[ -x "$ROOT/dist/tttlog/tttlog" ] || { echo "dist/tttlog missing: run scripts/build_app.py first" >&2; exit 1; }

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp -a "$ROOT/dist/tttlog" "$APPDIR/usr/lib/tttlog"
cp "$ROOT/packaging/linux/AppRun" "$APPDIR/AppRun"; chmod +x "$APPDIR/AppRun"
cp "$ROOT/packaging/linux/tttlog.desktop" "$APPDIR/tttlog.desktop"
cp "$ROOT/packaging/linux/tttlog.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT/tttlog/resources/tttlog.svg" "$APPDIR/tttlog.svg"
cp "$ROOT/tttlog/resources/tttlog.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
ln -sf tttlog.svg "$APPDIR/.DirIcon"

IMG="$ROOT/dist/tttlog-$VER-$ARCH.AppImage"
ARCH="$ARCH" "$TOOL" --no-appstream "$APPDIR" "$IMG"
chmod +x "$IMG"

PKG="$ROOT/build/tttlog-$VER-linux-$ARCH"
rm -rf "$PKG"; mkdir -p "$PKG"
cp "$IMG" "$ROOT/packaging/linux/install-linux.sh" "$ROOT/packaging/linux/tttlog.desktop" \
   "$ROOT/tttlog/resources/tttlog.svg" "$PKG/"
cp "$ROOT/docs/TESTERS-LINUX.md" "$PKG/README-FIRST.txt"
tar -C "$ROOT/build" -czf "$ROOT/dist/tttlog-$VER-linux-$ARCH.tar.gz" "tttlog-$VER-linux-$ARCH"
echo "AppImage  $IMG"
echo "Package   $ROOT/dist/tttlog-$VER-linux-$ARCH.tar.gz"
