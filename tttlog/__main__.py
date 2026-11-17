import sys


def main() -> int:
    if "--version" in sys.argv[1:]:
        from . import __version__
        print(f"tttlog {__version__}")
        return 0
    from PySide6.QtWidgets import QApplication

    from . import __version__
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("tttlog")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("N3TTT")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
