import sys
import ctypes

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