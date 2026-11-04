"""Render the LosslessCutter icon (scissors + cut line) at all sizes and
pack them into icon.ico / icon.png in src/losslesscutter/."""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
)
from PySide6.QtWidgets import QApplication

SIZES = [16, 24, 32, 48, 64, 128, 256]
OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "losslesscutter"

INK = QColor("#eef1f4")
ACCENT = QColor("#e8590c")


def paint(size: int) -> QImage:
    s = float(size)
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    def pt(x, y):
        return QPointF(x * s, y * s)

    # Background: dark rounded square with a subtle vertical gradient.
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.0, QColor("#2e343d"))
    grad.setColorAt(1.0, QColor("#16191e"))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    r = 0.20 * s
    p.drawRoundedRect(QRectF(0.01 * s, 0.01 * s, 0.98 * s, 0.98 * s), r, r)

    # Dashed cut line behind the blade tips.
    pen = QPen(ACCENT, max(2.0, 0.02 * s))
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setDashPattern([2.2, 1.6])
    p.setPen(pen)
    p.drawLine(pt(0.845, 0.06), pt(0.845, 0.94))

    # Blades (filled polygons).
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    p.drawPolygon(QPolygonF([pt(0.44, 0.452), pt(0.895, 0.150),
                             pt(0.935, 0.222), pt(0.50, 0.515)]))
    p.drawPolygon(QPolygonF([pt(0.44, 0.548), pt(0.895, 0.850),
                             pt(0.935, 0.778), pt(0.50, 0.485)]))

    # Handle connectors + rings.
    pen = QPen(INK, 0.052 * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(pt(0.295, 0.365), pt(0.475, 0.50))
    p.drawLine(pt(0.295, 0.635), pt(0.475, 0.50))
    p.drawEllipse(QRectF(0.135 * s, 0.195 * s, 0.20 * s, 0.235 * s))
    p.drawEllipse(QRectF(0.135 * s, 0.570 * s, 0.20 * s, 0.235 * s))

    # Pivot screw.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT)
    p.drawEllipse(pt(0.478, 0.50), 0.034 * s, 0.034 * s)

    p.end()
    return img


def write_ico(pngs: list[tuple[int, bytes]], path: Path) -> None:
    count = len(pngs)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    data = b""
    for size, blob in pngs:
        dim = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    path.write_bytes(header + entries + data)


def main() -> int:
    app = QApplication(sys.argv)
    pngs = []
    for size in SIZES:
        img = paint(size)
        out = Path(f"/tmp/icon-{size}.png")
        img.save(str(out), "PNG")
        pngs.append((size, out.read_bytes()))
        if size == 256:
            img.save(str(OUT_DIR / "icon.png"), "PNG")
    write_ico(pngs, OUT_DIR / "icon.ico")
    print("wrote", OUT_DIR / "icon.ico", "and icon.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
