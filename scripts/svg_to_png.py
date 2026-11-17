"""Render an SVG to a square PNG with Qt (used for the AppImage .DirIcon,
which must be a PNG).  Usage: python scripts/svg_to_png.py in.svg out.png [size]"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

src, dst = sys.argv[1], sys.argv[2]
size = int(sys.argv[3]) if len(sys.argv) > 3 else 256
app = QGuiApplication([])
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
r = QSvgRenderer(src)
if not r.isValid():
    sys.exit(f"bad svg: {src}")
p = QPainter(img); r.render(p); p.end()
if not img.save(dst, "PNG"):
    sys.exit(f"could not write {dst}")
