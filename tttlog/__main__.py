import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import __version__
from .ui.main_window import MainWindow


def main() -> int:
    if "--version" in sys.argv:
        print(f"tttlog {__version__}")
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("tttlog")
    app.setApplicationVersion(__version__)
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
