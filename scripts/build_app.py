"""Build a standalone tttlog app (no Python needed to run it).

    pip install pyinstaller
    python scripts/update_cty.py          # bundle the latest country file
    python scripts/build_app.py

Output: dist/tttlog/ (a folder with tttlog.exe on Windows, or tttlog on
macOS/Linux) and dist/tttlog-<version>-<platform>.zip (.tar.gz on Linux, so
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEP = ";" if os.name == "nt" else ":"


def version() -> str:
    ns: dict = {}
    exec((ROOT / "tttlog" / "__init__.py").read_text(), ns)
    return ns["__version__"]


def main() -> int:
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
           "--exclude-module", "tkinter"]
    if os.name == "nt" or sys.platform == "darwin":
        cmd.append("--windowed")              # no console window behind the app
    for src, dest in data:
        cmd += ["--add-data", f"{src}{SEP}{dest}"]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    plat = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
    folder = ROOT / "dist" / "tttlog"
    (folder / "README-FIRST.txt").write_text((ROOT / "docs" / "TESTERS.md").read_text(encoding="utf-8"),
                                             encoding="utf-8")
    zip_base = ROOT / "dist" / f"tttlog-{version()}-{plat}"
    fmt = "gztar" if plat == "linux" else "zip"
    out = shutil.make_archive(str(zip_base), fmt, root_dir=folder.parent, base_dir=folder.name)
    print(f"Built {folder}\nArchive {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
