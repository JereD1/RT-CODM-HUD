from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QApplication


class OverlayWindow(QWidget):
    """Small always-on-top, click-through strip of colored dots showing
    each player's current alive/dead state — a lightweight stand-in for
    the Electron version's overlay.html preview window."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen.x() + 20, screen.y() + 20, 260, 60)
        self.team1_alive = [True] * 5
        self.team2_alive = [True] * 5

    def update_state(self, team1_alive, team2_alive):
        self.team1_alive = team1_alive
        self.team2_alive = team2_alive
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gap = 22
        for i, alive in enumerate(self.team1_alive):
            painter.setBrush(QColor(80, 220, 120) if alive else QColor(220, 60, 60))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(10 + i * gap, 10, 16, 16)
        for i, alive in enumerate(self.team2_alive):
            painter.setBrush(QColor(80, 220, 120) if alive else QColor(220, 60, 60))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(10 + i * gap, 34, 16, 16)