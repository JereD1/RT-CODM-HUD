import os
import sys
import ctypes

# Work in real screen pixels. With Windows display scaling (125%, 150%) Qt
# would otherwise measure the boxes you draw in scaled units while the
# capture reads real pixels, so it would watch the wrong part of the screen.
# Must be set before Qt starts.
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from config import ASSETS_DIR
from main_window import MainWindow

APP_NAME = "Realtime CODM HUD"
ICON_PATH = ASSETS_DIR / "app_icon.ico"


def main():
    # Windows groups taskbar icons by the underlying .exe (python.exe when
    # run via `python main.py`), not by what Qt sets — this tells Windows
    # to treat this process as its own distinct app so the taskbar icon
    # actually shows ours instead of the generic Python one.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"realtime codm hud.{APP_NAME.lower()}"
            )
        except AttributeError:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()