"""Check GitHub Releases for a newer tttlog and install it.

Install types:
  * macOS .app      -> download the DMG, swap the app bundle after quitting, reopen
  * git checkout    -> `git pull --ff-only` + `pip install -e .`, then restart
  * Windows / Linux -> download the release file to ~/Downloads and show it
Pre-releases (alphas) count: until 1.0 every release is an alpha.
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

from . import __version__

REPO = "n3ttt/tttlog"
API_RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
UA = {"User-Agent": f"tttlog/{__version__}", "Accept": "application/vnd.github+json"}

FROZEN = getattr(sys, "frozen", False)
SOURCE_ROOT = None if FROZEN else Path(__file__).resolve().parents[1]
IS_GIT_CHECKOUT = bool(SOURCE_ROOT and (SOURCE_ROOT / ".git").exists())

_PRE = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}


# ------------------------------------------------------------------ versions
def parse_version(v: str) -> tuple:
    """'0.1.0a3' -> (0, 1, 0, 0, 3); '1.2' -> (1, 2, 0, 9, 0). Finals sort after pre-releases."""
    v = v.strip().lstrip("vV")
    m = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?[-.]?(?:(a|alpha|b|beta|rc)\.?(\d+)?)?", v, re.I)
    if not m:
        return (0, 0, 0, 0, 0)
    major, minor, patch, pre, pre_n = m.groups()
    rank = _PRE[pre.lower()] if pre else 9
    return (int(major), int(minor or 0), int(patch or 0), rank, int(pre_n or 0))


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


def build_number() -> str:
    """Goes up with every commit: the number of commits in the history. A built app
    has it stamped in tttlog/_build.py (scripts/build_app.py); from source, ask git."""
    try:
        from . import _build
        return str(_build.BUILD)
    except ImportError:
        pass
    if not IS_GIT_CHECKOUT:
        return ""
    try:
        return subprocess.check_output(["git", "-C", str(SOURCE_ROOT), "rev-list", "--count", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def display_version() -> str:
    """'0.1.0a3 build 57' (the release version, plus the build number when known)."""
    b = build_number()
    return f"{__version__} build {b}" if b else __version__


def version_string() -> str:
    """'0.1.0a3 build 57 (Mac app)' / '0.1.0a3 build 57 (source, abc1234)'."""
    if FROZEN:
        kind = {"darwin": "Mac app", "win32": "Windows app"}.get(sys.platform, "Linux app")
    else:
        c = git_commit()
        kind = f"source, {c}" if c else "source"
    return f"{display_version()} ({kind})"


# ------------------------------------------------------------------ releases
@dataclass
class Release:
    version: str
    notes: str
    url: str                   # release web page
    asset_url: str | None      # download for this computer
    asset_name: str | None


def _sysctl(name: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True,
                              timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def mac_is_apple_silicon() -> bool:
    """True on an Apple Silicon Mac, even when this copy is the Intel build running
    under Rosetta (where platform.machine() says x86_64)."""
    return sys.platform == "darwin" and (platform.machine() == "arm64" or _sysctl("hw.optional.arm64") == "1")


def running_under_rosetta() -> bool:
    """The Intel build running on an Apple Silicon Mac."""
    return sys.platform == "darwin" and _sysctl("sysctl.proc_translated") == "1"


def platform_asset_suffix() -> str:
    if sys.platform == "darwin":
        return "macos-arm64.dmg" if mac_is_apple_silicon() else "macos-x86_64.dmg"
    if sys.platform.startswith("win"):
        return "windows.zip"
    return "linux-x86_64.tar.gz"


def pick_latest(releases: list[dict], suffix: str | None = None) -> Release | None:
    suffix = suffix or platform_asset_suffix()
    best = None
    for r in releases:
        if r.get("draft"):
            continue
        ver = (r.get("tag_name") or "").lstrip("vV")
        if not ver:
            continue
        if best is None or parse_version(ver) > parse_version(best["tag_name"].lstrip("vV")):
            best = r
    if not best:
        return None
    asset = next((a for a in best.get("assets", []) if a["name"].endswith(suffix)), None)
    return Release(version=best["tag_name"].lstrip("vV"), notes=best.get("body") or "",
                   url=best.get("html_url", ""),
                   asset_url=asset["browser_download_url"] if asset else None,
                   asset_name=asset["name"] if asset else None)


def fetch_latest(timeout: float = 10) -> Release | None:
    req = urllib.request.Request(API_RELEASES, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return pick_latest(json.load(r))


def download(url: str, dest: Path, progress=None) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    tmp = dest.with_name(dest.name + ".part")
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


# ------------------------------------------------------------------ install
def app_bundle() -> Path | None:
    """The running tttlog.app on macOS, else None."""
    if FROZEN and sys.platform == "darwin":
        for parent in Path(sys.executable).resolve().parents:
            if parent.suffix == ".app":
                return parent
    return None


def install_kind() -> str:
    if app_bundle():
        return "mac-app"
    if IS_GIT_CHECKOUT:
        return "git"
    return "download"


def update_git_checkout() -> str:
    """git pull + reinstall. Returns the output; raises CalledProcessError on failure."""
    out = subprocess.check_output(["git", "-C", str(SOURCE_ROOT), "pull", "--ff-only"],
                                  text=True, stderr=subprocess.STDOUT)
    out += subprocess.check_output([sys.executable, "-m", "pip", "install", "-q", "-e", str(SOURCE_ROOT)],
                                   text=True, stderr=subprocess.STDOUT)
    return out


def stage_mac_update(dmg: Path) -> None:
    """After this process exits: replace the .app with the one inside `dmg`, then reopen it.

    Runs a small detached shell script. If the copy fails, the old app is put back.
    """
    bundle = app_bundle()
    if not bundle:
        raise RuntimeError("not running from tttlog.app")
    q = shlex.quote
    app, mnt = q(str(bundle)), q(tempfile.mkdtemp(prefix="tttlog-dmg-"))
    script = f"""#!/bin/bash
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done
hdiutil attach -nobrowse -quiet -mountpoint {mnt} {q(str(dmg))} || exit 1
NEW=$(ls -d {mnt}/*.app | head -1)
rm -rf {app}.old
if mv {app} {app}.old && ditto "$NEW" {app}; then rm -rf {app}.old; else rm -rf {app}; mv {app}.old {app}; fi
hdiutil detach -quiet {mnt}
xattr -dr com.apple.quarantine {app} 2>/dev/null
rm -f {q(str(dmg))}
open {app}
"""
    fd, sh = tempfile.mkstemp(prefix="tttlog-update-", suffix=".sh")
    os.write(fd, script.encode())
    os.close(fd)
    os.chmod(sh, 0o755)
    subprocess.Popen(["/bin/bash", sh], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def restart_from_source() -> None:
    subprocess.Popen([sys.executable, "-m", "tttlog"], start_new_session=True)
