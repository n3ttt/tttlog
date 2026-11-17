"""Version checks, app self-update, and data-file downloads.

Releases come from GitHub (n3ttt/tttlog). Three install types are handled:
  * macOS .app       -> download the DMG, swap the app bundle, relaunch
  * git checkout     -> `git pull` + `pip install -e .`, then restart
  * Windows / Linux  -> download the release asset and open its folder
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import REPO, __version__
from .paths import DATA_DIR, FROZEN, IS_GIT_CHECKOUT, SOURCE_ROOT, app_bundle

API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = {"User-Agent": f"tttlog/{__version__}", "Accept": "application/vnd.github+json"}

DATA_FILES = {
    "cty.dat": "https://www.country-files.com/cty/cty.dat",
    "MASTER.SCP": "https://www.supercheckpartial.com/MASTER.SCP",
}


# ------------------------------------------------------------------ versions
def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - min(len(nums), 3))


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def git_commit() -> str:
    if not IS_GIT_CHECKOUT:
        return ""
    try:
        return subprocess.check_output(["git", "-C", str(SOURCE_ROOT), "rev-parse", "--short", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def version_string() -> str:
    c = git_commit()
    kind = "app" if FROZEN else ("source " + c if c else "source")
    return f"{__version__} ({kind})"


# ------------------------------------------------------------------ release lookup
@dataclass
class Release:
    version: str
    notes: str
    url: str                  # release web page
    asset_url: str | None     # download for this platform
    asset_name: str | None


def platform_asset_suffix() -> str:
    if sys.platform == "darwin":
        return "macos-arm64.dmg" if platform.machine() == "arm64" else "macos-x86_64.dmg"
    if sys.platform.startswith("win"):
        return "windows.zip"
    return "linux.tar.gz"


def fetch_latest(timeout: float = 10) -> Release | None:
    req = urllib.request.Request(API_LATEST, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception:
        return None
    suffix = platform_asset_suffix()
    asset = next((a for a in data.get("assets", []) if a["name"].endswith(suffix)), None)
    return Release(version=data.get("tag_name", "").lstrip("v"), notes=data.get("body") or "",
                   url=data.get("html_url", ""),
                   asset_url=asset["browser_download_url"] if asset else None,
                   asset_name=asset["name"] if asset else None)


def download(url: str, dest: Path, progress=None) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done, total)
    tmp.replace(dest)
    return dest


# ------------------------------------------------------------------ data files
def update_data_files() -> list[str]:
    """Download cty.dat + MASTER.SCP. Returns human-readable status lines."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for name, url in DATA_FILES.items():
        try:
            p = download(url, DATA_DIR / name)
            out.append(f"{name}: updated ({p.stat().st_size:,} bytes)")
        except Exception as e:
            out.append(f"{name}: FAILED ({e})")
    return out


# ------------------------------------------------------------------ install
def install_kind() -> str:
    if app_bundle():
        return "mac-app"
    if IS_GIT_CHECKOUT:
        return "git"
    if FROZEN:
        return "frozen"
    return "pip"


def update_git_checkout() -> str:
    """git pull + reinstall deps. Returns log text. Raises on failure."""
    log = subprocess.check_output(["git", "-C", str(SOURCE_ROOT), "pull", "--ff-only"],
                                  text=True, stderr=subprocess.STDOUT)
    log += subprocess.check_output([sys.executable, "-m", "pip", "install", "-q", "-e", str(SOURCE_ROOT)],
                                   text=True, stderr=subprocess.STDOUT)
    return log


def stage_mac_update(dmg: Path) -> None:
    """Swap the running .app with the one in `dmg` after we quit, then relaunch.

    Spawns a detached shell script that waits for this process to exit.
    """
    bundle = app_bundle()
    if not bundle:
        raise RuntimeError("not running from a .app bundle")
    mnt = Path(tempfile.mkdtemp(prefix="tttlog-dmg-"))
    q = shlex.quote
    script = f"""#!/bin/bash
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done
hdiutil attach -nobrowse -quiet -mountpoint {q(str(mnt))} {q(str(dmg))} || exit 1
NEW=$(ls -d {q(str(mnt))}/*.app | head -1)
rm -rf {q(str(bundle))}.old
mv {q(str(bundle))} {q(str(bundle))}.old && ditto "$NEW" {q(str(bundle))} && rm -rf {q(str(bundle))}.old \
  || mv {q(str(bundle))}.old {q(str(bundle))}
hdiutil detach -quiet {q(str(mnt))}
xattr -dr com.apple.quarantine {q(str(bundle))} 2>/dev/null
rm -f {q(str(dmg))}
open {q(str(bundle))}
"""
    sh = Path(tempfile.mkstemp(prefix="tttlog-update-", suffix=".sh")[1])
    sh.write_text(script)
    sh.chmod(0o755)
    subprocess.Popen(["/bin/bash", str(sh)], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def restart_app() -> None:
    """Relaunch the current program (source installs)."""
    subprocess.Popen([sys.executable, "-m", "tttlog"], start_new_session=True)
