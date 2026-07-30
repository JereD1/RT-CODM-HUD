from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QApplication


class RegionSelector(QWidget):
    """Translucent, frameless, full-screen drag-to-select rectangle picker.
    Emits region_picked with real screen-space {left, top, width, height},
    or cancelled on Esc / a too-small drag."""
    region_picked = Signal(dict)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self._origin = None
        self._current = None
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, event):
        self._origin = event.position().toPoint()
        self._current = self._origin

    def mouseMoveEvent(self, event):
        self._current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event):
        if self._origin is None:
            return
        rect = QRect(self._origin, self._current).normalized()
        self.close()
        if rect.width() > 4 and rect.height() > 4:
            self.region_picked.emit({
                "left": rect.x(), "top": rect.y(),
                "width": rect.width(), "height": rect.height(),
            })
        else:
            self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._origin and self._current:
            rect = QRect(self._origin, self._current).normalized()
            painter.setPen(QPen(QColor(80, 200, 255), 2))
            painter.fillRect(rect, QColor(80, 200, 255, 40))
            painter.drawRect(rect)