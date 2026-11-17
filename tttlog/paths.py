"""Where things live. Works the same from a source checkout or a packaged app."""
from __future__ import annotations

import sys
from pathlib import Path

USER_DIR = Path.home() / ".tttlog"            # settings, macros, wav files
DATA_DIR = USER_DIR / "data"                   # cty.dat, MASTER.SCP (downloaded)
LOG_DIR = Path.home() / "Documents" / "tttlog"

PKG_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = PKG_DIR / "resources"           # bundled fallbacks
RULES_DIR = PKG_DIR / "contests" / "rules"

FROZEN = getattr(sys, "frozen", False)         # True inside the PyInstaller .app/.exe
SOURCE_ROOT = None if FROZEN else PKG_DIR.parent
IS_GIT_CHECKOUT = bool(SOURCE_ROOT and (SOURCE_ROOT / ".git").exists())


def app_bundle() -> Path | None:
    """Path to the running tttlog.app on macOS (None otherwise)."""
    if FROZEN and sys.platform == "darwin":
        p = Path(sys.executable).resolve()
        for parent in p.parents:
            if parent.suffix == ".app":
                return parent
    return None
