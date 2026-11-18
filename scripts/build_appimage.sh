#!/bin/sh
# Turn the PyInstaller folder (dist/tttlog, from scripts/build_app.py) into
# one Linux AppImage, and pack it with the installer script:
#   dist/tttlog-<version>-x86_64.AppImage
#   dist/tttlog-<version>-linux-x86_64.tar.gz   (AppImage + install-linux.sh + icon + .desktop)
# Needs appimagetool; set APPIMAGETOOL to its path (the CI job downloads it).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="$(python3 -c "import re,sys; print(re.search(r'__version__ = \"(.+?)\"', open(sys.argv[1]).read()).group(1))" "$ROOT/tttlog/__init__.py")"
# with the build number build_app.py stamped in tttlog/_build.py: 0.1.0a3-b57
BUILD="$(python3 -c "import re,sys; m=re.search(r'BUILD = \"(.+?)\"', open(sys.argv[1]).read()); print(m.group(1) if m else '')" "$ROOT/tttlog/_build.py" 2>/dev/null || true)"
[ -n "$BUILD" ] && VER="$VER-b$BUILD"
ARCH="$(uname -m)"
TOOL="${APPIMAGETOOL:-appimagetool}"
APPDIR="$ROOT/build/AppDir"
[ -x "$ROOT/dist/tttlog/tttlog" ] || { echo "dist/tttlog missing: run scripts/build_app.py first" >&2; exit 1; }

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$ROOT/dist/tttlog" "$APPDIR/usr/lib/tttlog"
cp "$ROOT/packaging/linux/AppRun" "$APPDIR/AppRun"; chmod +x "$APPDIR/AppRun"
cp "$ROOT/packaging/linux/tttlog.desktop" "$APPDIR/tttlog.desktop"
cp "$ROOT/packaging/linux/tttlog.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT/tttlog/resources/tttlog.svg" "$APPDIR/tttlog.svg"
cp "$ROOT/tttlog/resources/tttlog.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
# .DirIcon has to be a PNG (appimagetool rejects an SVG there)
"${PYTHON:-python3}" "$ROOT/scripts/svg_to_png.py" "$ROOT/tttlog/resources/tttlog.svg" "$APPDIR/.DirIcon" 256
cp "$APPDIR/.DirIcon" "$APPDIR/usr/share/icons/hicolor/256x256/apps/tttlog.png"

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
