import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LosslessCutter")
    window = MainWindow()
    app.setWindowIcon(window.windowIcon())
    # Default launch size is 1920x1080 (not maximized), centered on
    # the screen and clamped to it on smaller displays.
    window.resize(1920, 1080)
    area = app.primaryScreen().availableGeometry()
    window.move(max(area.left(), area.left() + (area.width() - 1920) // 2),
                max(area.top(), area.top() + (area.height() - 1080) // 2))
    # Launch filling the screen WITH the title bar and window
    # controls (maximized); the 1920x1080 size above is the geometry
    # it restores to. F11 still toggles borderless fullscreen.
    # Start transparent and reveal only after the first paint has
    # gone through: shown directly, Windows fills the new window
    # white before Qt paints it, which flashes badly on a maximized
    # window whose preview is black.
    window.setWindowOpacity(0.0)
    window.showMaximized()
    app.processEvents()
    window.setWindowOpacity(1.0)
    # Safety net: if the first paint somehow lands after
    # processEvents, never leave the window invisible.
    QTimer.singleShot(250, lambda: window.setWindowOpacity(1.0))
    window.start_update_check()
    if len(sys.argv) > 1:
        window.load_file(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
