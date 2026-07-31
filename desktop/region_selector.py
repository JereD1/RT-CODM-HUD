from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QApplication, QLabel, QPushButton

from config import (
    PLAYERS_PER_TEAM, QUICKSETUP_BOX_WIDTH, QUICKSETUP_BOX_HEIGHT,
    QUICKSETUP_GAP, QUICKSETUP_TOP_MARGIN,
)


def _virtual_desktop_rect() -> QRect:
    """Union of every connected screen's geometry, so overlays can span
    (and boxes can be dragged onto) any monitor, not just the primary."""
    rect = QRect()
    for screen in QApplication.screens():
        rect = rect.united(screen.geometry())
    return rect


class RegionSelector(QWidget):
    """Translucent, frameless, drag-to-select rectangle picker, spanning
    every connected monitor. Emits region_picked with real screen-space
    {left, top, width, height}, or cancelled on Esc / a too-small drag."""
    region_picked = Signal(dict)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(_virtual_desktop_rect())
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
        origin = self.geometry().topLeft()
        self.close()
        if rect.width() > 4 and rect.height() > 4:
            self.region_picked.emit({
                "left": origin.x() + rect.x(), "top": origin.y() + rect.y(),
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


_HANDLE = 14


class DraggableBox(QWidget):
    """One player's region box inside QuickRegionSetup — drag the body to
    move, drag the bottom-right corner to resize."""

    def __init__(self, parent, label_text: str, rect: QRect, color: QColor):
        super().__init__(parent)
        self.color = color
        self.setGeometry(rect)
        self._drag_offset = None
        self._resizing = False
        self._resize_start = None
        self._start_geom = None

        self.label = QLabel(label_text, self)
        self.label.setStyleSheet(
            "color: white; font-weight: bold; font-size: 11px; "
            "background: rgba(0,0,0,140); padding: 1px 4px;"
        )
        self.label.move(2, 2)
        self.label.adjustSize()
        self.setCursor(Qt.OpenHandCursor)

    def region(self, origin: QPoint) -> dict:
        g = self.geometry()
        return {"left": origin.x() + g.x(), "top": origin.y() + g.y(),
                "width": g.width(), "height": g.height()}

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        if pos.x() >= self.width() - _HANDLE and pos.y() >= self.height() - _HANDLE:
            self._resizing = True
            self._resize_start = event.globalPosition().toPoint()
            self._start_geom = self.geometry()
        else:
            self._resizing = False
            self._drag_offset = pos
        self.raise_()

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.globalPosition().toPoint() - self._resize_start
            new_w = max(24, self._start_geom.width() + delta.x())
            new_h = max(16, self._start_geom.height() + delta.y())
            self.resize(new_w, new_h)
        elif self._drag_offset is not None:
            new_pos = self.mapToParent(event.position().toPoint() - self._drag_offset)
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        self._resizing = False

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(self.color, 2))
        p.setBrush(QColor(self.color.red(), self.color.green(), self.color.blue(), 40))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.setBrush(self.color)
        p.drawRect(self.width() - _HANDLE, self.height() - _HANDLE, _HANDLE, _HANDLE)


class QuickRegionSetup(QWidget):
    """Draws all 10 player-region boxes at once over the whole virtual
    desktop. Operator nudges each onto its player's white stripe and
    confirms once, instead of picking 10 regions one at a time."""
    setup_complete = Signal(dict)   # {(team, player): region}
    cancelled = Signal()

    def __init__(self, existing: dict | None = None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(_virtual_desktop_rect())

        origin = self.geometry().topLeft()
        primary = QApplication.primaryScreen().geometry()
        left_color = QColor(80, 200, 255)
        right_color = QColor(255, 170, 80)

        self.boxes: dict[tuple[int, int], DraggableBox] = {}
        for p in range(PLAYERS_PER_TEAM):
            lx = primary.x() - origin.x() + 10
            ly = primary.y() - origin.y() + QUICKSETUP_TOP_MARGIN + p * (QUICKSETUP_BOX_HEIGHT + QUICKSETUP_GAP)
            self.boxes[(0, p)] = self._make_box(
                (existing or {}).get((0, p)), origin,
                QRect(lx, ly, QUICKSETUP_BOX_WIDTH, QUICKSETUP_BOX_HEIGHT), f"L{p+1}", left_color)

            rx = primary.x() - origin.x() + primary.width() - QUICKSETUP_BOX_WIDTH - 10
            self.boxes[(1, p)] = self._make_box(
                (existing or {}).get((1, p)), origin,
                QRect(rx, ly, QUICKSETUP_BOX_WIDTH, QUICKSETUP_BOX_HEIGHT), f"R{p+1}", right_color)

        self.confirm_btn = QPushButton("Confirm setup (Enter)", self)
        self.confirm_btn.setStyleSheet(
            "background:#22c55e; color:white; font-weight:bold; padding:8px 16px; border-radius:6px;")
        self.confirm_btn.clicked.connect(self._confirm)
        self.confirm_btn.adjustSize()
        self.confirm_btn.move(
            primary.x() - origin.x() + primary.width() // 2 - self.confirm_btn.width() // 2,
            primary.y() - origin.y() + primary.height() - 60)
        self.confirm_btn.raise_()

        self.hint_label = QLabel(
            "Drag each box onto its player's white stripe. Drag the bottom-right "
            "corner to resize. Enter to confirm, Esc to cancel.", self)
        self.hint_label.setStyleSheet(
            "color: white; background: rgba(0,0,0,160); padding: 6px 10px; font-size: 12px;")
        self.hint_label.adjustSize()
        self.hint_label.move(
            primary.x() - origin.x() + primary.width() // 2 - self.hint_label.width() // 2,
            primary.y() - origin.y() + 4)
        self.hint_label.raise_()

    def _make_box(self, existing_region, origin, default_rect, label, color) -> DraggableBox:
        rect = default_rect
        if existing_region:
            rect = QRect(existing_region["left"] - origin.x(), existing_region["top"] - origin.y(),
                         existing_region["width"], existing_region["height"])
        box = DraggableBox(self, label, rect, color)
        box.show()
        return box

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._confirm()

    def _confirm(self):
        origin = self.geometry().topLeft()
        regions = {key: box.region(origin) for key, box in self.boxes.items()}
        self.close()
        self.setup_complete.emit(regions)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))