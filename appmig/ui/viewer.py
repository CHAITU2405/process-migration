"""The remote window: pixels arrive from the agent, input goes back to it.

The widget letterboxes the incoming frame and maps every pointer coordinate back
into the source window's coordinate space, so clicks land where the user aimed
regardless of scaling.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QPoint, QRect, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

# Qt keys that do not already share a value with their Windows virtual key code.
_VK_MAP = {
    Qt.Key_Backspace: 0x08, Qt.Key_Tab: 0x09, Qt.Key_Return: 0x0D,
    Qt.Key_Enter: 0x0D, Qt.Key_Escape: 0x1B, Qt.Key_Space: 0x20,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_End: 0x23,
    Qt.Key_Home: 0x24, Qt.Key_Left: 0x25, Qt.Key_Up: 0x26,
    Qt.Key_Right: 0x27, Qt.Key_Down: 0x28, Qt.Key_Insert: 0x2D,
    Qt.Key_Delete: 0x2E, Qt.Key_Shift: 0x10, Qt.Key_Control: 0x11,
    Qt.Key_Alt: 0x12, Qt.Key_CapsLock: 0x14, Qt.Key_Meta: 0x5B,
}
for _index in range(12):
    _VK_MAP[Qt.Key_F1 + _index] = 0x70 + _index

_BUTTONS = {
    Qt.LeftButton: "left",
    Qt.RightButton: "right",
    Qt.MiddleButton: "middle",
}


class RemoteViewer(QWidget):
    """Displays the streamed window and emits input events for the link."""

    inputEvent = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(480, 320)

        self._pixmap: Optional[QPixmap] = None
        self._source_size = (0, 0)   # the real window size on the agent
        self._draw_rect = QRect()
        self._placeholder = "No session is being displayed."
        self.frames_received = 0
        self.interactive = True

    # -- incoming frames ------------------------------------------------------
    def set_frame(self, meta: dict, jpeg: bytes) -> None:
        image = QImage.fromData(jpeg, "JPEG")
        if image.isNull():
            return
        self._pixmap = QPixmap.fromImage(image)
        self._source_size = (int(meta.get("sw", image.width())),
                             int(meta.get("sh", image.height())))
        self.frames_received += 1
        self.update()

    def clear(self, message: str = "No session is being displayed.") -> None:
        self._pixmap = None
        self._placeholder = message
        self.frames_received = 0
        self.update()

    # -- painting -------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0b0d11"))

        if self._pixmap is None:
            painter.setPen(QColor(theme.TEXT_FAINT))
            painter.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
            return

        scaled = self._pixmap.size().scaled(self.size(), Qt.KeepAspectRatio)
        self._draw_rect = QRect(
            (self.width() - scaled.width()) // 2,
            (self.height() - scaled.height()) // 2,
            scaled.width(), scaled.height(),
        )
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self._draw_rect, self._pixmap)

    # -- coordinate mapping ---------------------------------------------------
    def _to_source(self, point: QPoint) -> Optional[tuple]:
        """Widget coordinates -> coordinates inside the agent's window."""
        if self._pixmap is None or not self._draw_rect.contains(point):
            return None
        source_width, source_height = self._source_size
        if source_width <= 0 or source_height <= 0:
            return None
        relative_x = (point.x() - self._draw_rect.x()) / self._draw_rect.width()
        relative_y = (point.y() - self._draw_rect.y()) / self._draw_rect.height()
        return int(relative_x * source_width), int(relative_y * source_height)

    def _emit(self, event: dict) -> None:
        if self.interactive:
            self.inputEvent.emit(event)

    # -- mouse ----------------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:
        point = self._to_source(event.position().toPoint())
        if point is not None:
            self._emit({"kind": "move", "x": point[0], "y": point[1]})

    def mousePressEvent(self, event) -> None:
        self.setFocus(Qt.MouseFocusReason)
        self._button(event, down=True)

    def mouseReleaseEvent(self, event) -> None:
        self._button(event, down=False)

    def _button(self, event, down: bool) -> None:
        button = _BUTTONS.get(event.button())
        point = self._to_source(event.position().toPoint())
        if button is None or point is None:
            return
        self._emit({"kind": "button", "button": button, "down": down,
                    "x": point[0], "y": point[1]})

    def wheelEvent(self, event) -> None:
        point = self._to_source(event.position().toPoint())
        if point is None:
            return
        self._emit({"kind": "wheel", "delta": event.angleDelta().y(),
                    "x": point[0], "y": point[1]})

    # -- keyboard -------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        text = event.text()
        modifiers = event.modifiers()
        chorded = bool(modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))

        # Printable characters go across as text so layouts and dead keys work.
        if text and text.isprintable() and not chorded:
            self._emit({"kind": "text", "text": text})
            return

        vk = self._virtual_key(event)
        if vk:
            self._emit({"kind": "key", "vk": vk, "down": True})

    def keyReleaseEvent(self, event) -> None:
        if event.isAutoRepeat():
            return
        vk = self._virtual_key(event)
        if vk:
            self._emit({"kind": "key", "vk": vk, "down": False})

    @staticmethod
    def _virtual_key(event) -> int:
        key = event.key()
        if key in _VK_MAP:
            return _VK_MAP[key]
        # Letters and digits already line up with their virtual key codes.
        if Qt.Key_0 <= key <= Qt.Key_9 or Qt.Key_A <= key <= Qt.Key_Z:
            return int(key)
        return 0
