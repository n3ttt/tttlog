"""Build a standalone tttlog app (no Python needed to run it).

    pip install pyinstaller
    python scripts/update_cty.py          # bundle the latest country file
    python scripts/build_app.py

Output: dist/tttlog/ (a folder with tttlog.exe on Windows, tttlog on Linux),
dist/tttlog.app + dist/tttlog-<version>-macos-<arch>.dmg on a Mac,
and dist/tttlog-<version>-<platform>.zip (.tar.gz on Linux, so
the program keeps its "executable" mark) ready to hand out. On Linux,
scripts/build_appimage.sh then turns the folder into a single AppImage.
PyInstaller can't cross-compile: build the Windows zip on Windows (the
GitHub workflow in .github/workflows/windows-build.yml does this).
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEP = ";" if os.name == "nt" else ":"


def version() -> str:
    ns: dict = {}
    exec((ROOT / "tttlog" / "__init__.py").read_text(), ns)
    return ns["__version__"]


def build_number() -> str:
    """Number of commits so far: the same on every platform, up by one each commit.
    (CI checks out the full history for this; TTTLOG_BUILD overrides it.)"""
    if os.environ.get("TTTLOG_BUILD"):
        return os.environ["TTTLOG_BUILD"]
    try:
        return subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "0"


def stamp_build() -> str:
    """Write tttlog/_build.py (not in git) so the built app knows its build number."""
    b = build_number()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = ""
    (ROOT / "tttlog" / "_build.py").write_text(f'BUILD = "{b}"\nCOMMIT = "{commit}"\n')
    return b


def file_version() -> str:
    """'0.1.0a3-b57': what goes in the download's file name."""
    return f"{version()}-b{build_number()}"


def main() -> int:
    stamp_build()
    cty = ROOT / "data" / "cty.dat"
    if not cty.exists():
        print("data/cty.dat missing: run  python scripts/update_cty.py  first", file=sys.stderr)
        return 1
    data = [(cty, "data"),
            (ROOT / "tttlog" / "contests" / "rules", "tttlog/contests/rules"),
            (ROOT / "tttlog" / "resources", "tttlog/resources"),
            (ROOT / "tests" / "fixtures" / "cty_sample.dat", "tests/fixtures")]
    scp = ROOT / "data" / "MASTER.SCP"
    if scp.exists():
        data.append((scp, "data"))
    entry = ROOT / "build" / "tttlog_entry.py"
    entry.parent.mkdir(exist_ok=True)
    entry.write_text("import sys\nfrom tttlog.__main__ import main\nsys.exit(main())\n")

    cmd = [sys.executable, "-m", "PyInstaller", str(entry),
           "--name", "tttlog", "--noconfirm", "--clean", "--onedir",
           "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"),
           "--specpath", str(ROOT / "build"),
           # only the Qt parts tttlog uses; keeps the download small
           "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
           "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
           "--exclude-module", "PySide6.Qt3DCore", "--exclude-module", "PySide6.QtPdf",
           "--exclude-module", "tkinter", "--hidden-import", "tttlog._build"]
    if os.name == "nt" or sys.platform == "darwin":
        cmd.append("--windowed")              # no console window behind the app
    for src, dest in data:
        cmd += ["--add-data", f"{src}{SEP}{dest}"]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    if sys.platform == "darwin":
        return build_mac_dmg()
    plat = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
    folder = ROOT / "dist" / "tttlog"
    (folder / "README-FIRST.txt").write_text((ROOT / "docs" / "TESTERS.md").read_text(encoding="utf-8"),
                                             encoding="utf-8")
    zip_base = ROOT / "dist" / f"tttlog-{file_version()}-{plat}"
    fmt = "gztar" if plat == "linux" else "zip"
    out = shutil.make_archive(str(zip_base), fmt, root_dir=folder.parent, base_dir=folder.name)
    print(f"Built {folder}\nArchive {out}")
    return 0


def build_mac_dmg() -> int:
    """dist/tttlog.app -> dist/tttlog-<version>-macos-<arch>.dmg (drag-to-Applications)."""
    ver = version()
    app = ROOT / "dist" / "tttlog.app"
    plist = app / "Contents" / "Info.plist"
    subprocess.run(["plutil", "-replace", "CFBundleShortVersionString", "-string", ver, str(plist)], check=True)
    subprocess.run(["plutil", "-replace", "CFBundleVersion", "-string", build_number(), str(plist)], check=True)
    subprocess.run(["plutil", "-replace", "CFBundleIdentifier", "-string", "com.n3ttt.tttlog", str(plist)],
                   check=True)
    # Recording voice-keyer messages: without this macOS refuses (or kills the app on) mic access.
    subprocess.run(["plutil", "-replace", "NSMicrophoneUsageDescription", "-string",
                    "tttlog records your voice-keyer messages (CQ, exchange, TU) from the microphone.",
                    str(plist)], check=True)
    # Ad-hoc signature: required on Apple Silicon; not a Developer ID, so first launch needs
    # System Settings > Privacy & Security > Open Anyway (see README).
    # A synced folder (iCloud Documents) tags files with Finder info that codesign rejects
    # ("resource fork, Finder information, or similar detritus not allowed"): clear it first.
    subprocess.run(["xattr", "-cr", str(app)], check=True)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    stage = ROOT / "build" / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    subprocess.run(["ditto", str(app), str(stage / "tttlog.app")], check=True)
    (stage / "Applications").symlink_to("/Applications")
    (stage / "README-FIRST.txt").write_text((ROOT / "docs" / "TESTERS-MAC.md").read_text(encoding="utf-8"),
                                            encoding="utf-8")
    dmg = ROOT / "dist" / f"tttlog-{file_version()}-macos-{arch}.dmg"
    dmg.unlink(missing_ok=True)
    # hdiutil sometimes fails with "Resource busy" on CI runners while something else briefly
    # holds the disk; it works on a retry.
    cmd = ["hdiutil", "create", "-volname", f"tttlog {ver}", "-srcfolder", str(stage),
           "-ov", "-format", "UDZO", str(dmg)]
    for attempt in range(1, 6):
        if subprocess.run(cmd).returncode == 0:
            break
        if attempt == 5:
            raise subprocess.CalledProcessError(1, cmd)
        print(f"hdiutil failed (attempt {attempt}); retrying in {attempt * 5}s")
        time.sleep(attempt * 5)
    print(f"Built {app}\nDisk image {dmg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
