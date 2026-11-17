import os
import sys

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .ui.main_window import MainWindow


def _apply_display_size() -> None:
    """View ▸ Display size: scale the whole window (for small or very large screens).
    Qt reads this before the app starts, so changes take effect on restart."""
    if os.environ.get("QT_SCALE_FACTOR"):
        return                                   # the user set it themselves
    from PySide6.QtCore import QSettings
    try:
        pct = int(QSettings("N3TTT", "tttlog").value("ui_scale", 100) or 100)
    except (TypeError, ValueError):
        return
    if pct != 100 and 50 <= pct <= 200:
        os.environ["QT_SCALE_FACTOR"] = f"{pct / 100:g}"


def main() -> int:
    if "--version" in sys.argv:
        print(f"tttlog {__version__}")
        return 0
    _apply_display_size()
    app = QApplication(sys.argv)
    app.setApplicationName("tttlog")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("tttlog")            # Linux: match tttlog.desktop for the taskbar icon
    icon = Path(__file__).parent / "resources" / "tttlog.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    if "--smoke-test" in sys.argv:
        # Used by the build: start, check the window came up, quit.
        def check():
            from .contests.engine import list_contests, load_rules
            contests = [load_rules(c["id"])["name"] for c in list_contests()]
            ok = w.isVisible() and len(w.cty.entities()) > 300 and len(contests) >= 3
            print(f"smoke test: window={w.isVisible()} entities={len(w.cty.entities())} "
                  f"contests={contests} -> {'OK' if ok else 'FAIL'}")
            w.close()
            app.exit(0 if ok else 1)
        QTimer.singleShot(1500, check)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
