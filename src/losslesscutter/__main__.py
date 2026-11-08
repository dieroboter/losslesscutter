import sys

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
    window.showMaximized()
    window.start_update_check()
    if len(sys.argv) > 1:
        window.load_file(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
