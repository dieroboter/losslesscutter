import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LosslessCutter")
    window = MainWindow()
    app.setWindowIcon(window.windowIcon())
    window.showMaximized()
    window.start_update_check()
    if len(sys.argv) > 1:
        window.load_file(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
