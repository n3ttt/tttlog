"""Build a standalone app with PyInstaller.

    pip install -e ".[build]"
    python scripts/build.py

Output in dist/:
  macOS   -> tttlog.app + tttlog-<ver>-macos-<arch>.dmg
  Windows -> tttlog-<ver>-windows.zip
  Linux   -> tttlog-<ver>-linux.tar.gz
"""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tttlog import __version__  # noqa: E402

SEP = ";" if sys.platform.startswith("win") else ":"
DIST = ROOT / "dist"


def run(*cmd):
    print("+", " ".join(map(str, cmd)))
    subprocess.check_call(list(map(str, cmd)), cwd=ROOT)


def main():
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", "tttlog",
            "--add-data", f"tttlog/contests/rules{SEP}tttlog/contests/rules",
            "--add-data", f"tttlog/resources{SEP}tttlog/resources",
            "--exclude-module", "tkinter"]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "com.n3ttt.tttlog"]
    run(*args, "scripts/tttlog_app.py")

    if sys.platform == "darwin":
        plist = DIST / "tttlog.app" / "Contents" / "Info.plist"
        run("plutil", "-replace", "CFBundleShortVersionString", "-string", __version__, plist)
        run("plutil", "-replace", "CFBundleVersion", "-string", __version__, plist)
        run("codesign", "--force", "--deep", "--sign", "-", DIST / "tttlog.app")   # ad-hoc sign
        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        dmg = DIST / f"tttlog-{__version__}-macos-{arch}.dmg"
        stage = DIST / "dmg"
        stage.mkdir()
        run("ditto", DIST / "tttlog.app", stage / "tttlog.app")
        (stage / "Applications").symlink_to("/Applications")
        run("hdiutil", "create", "-volname", f"tttlog {__version__}", "-srcfolder", stage,
            "-ov", "-format", "UDZO", dmg)
        print("Built", dmg)
    elif sys.platform.startswith("win"):
        out = shutil.make_archive(str(DIST / f"tttlog-{__version__}-windows"), "zip", DIST, "tttlog")
        print("Built", out)
    else:
        out = shutil.make_archive(str(DIST / f"tttlog-{__version__}-linux"), "gztar", DIST, "tttlog")
        print("Built", out)


if __name__ == "__main__":
    main()
