"""PyInstaller entry point (PyInstaller can't use a package's __main__ directly)."""
import sys

from tttlog.__main__ import main

sys.exit(main())
