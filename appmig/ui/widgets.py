"""Small reusable pieces shared across the pages."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme


class Avatar(QLabel):
    """A rounded initial badge, coloured deterministically from the app name."""

    def __init__(self, name: str, size: int = 38, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._letter = (name.strip()[:1] or "?").upper()
        self._color = QColor(theme.avatar_color(name))
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 10, 10)
        fill = QColor(self._color)
        fill.setAlpha(46)
        painter.fillPath(path, fill)

        font = QFont(self.font())
        font.setPointSizeF(self.height() * 0.42)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(self._color)
        painter.drawText(self.rect(), Qt.AlignCenter, self._letter)


class Badge(QLabel):
    """A small pill used for fidelity and connection state."""

    def __init__(self, text: str, color: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.set_state(text, color)

    def set_state(self, text: str, color: str) -> None:
        self.setText(text)
        self.setStyleSheet(
            f"color: {color};"
            f"background: rgba({_rgb(color)}, 0.14);"
            "border-radius: 6px;"
            "padding: 3px 8px;"
            "font-size: 10px;"
            "font-weight: 600;"
        )


class StatusDot(QLabel):
    """Connection indicator."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self._color = QColor(theme.DANGER)

    def set_online(self, online: bool) -> None:
        self._color = QColor(theme.SUCCESS if online else theme.DANGER)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self.width(), self.height())


class Card(QFrame):
    """A bordered container used for every list row."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        self.body = layout


def label(text: str, object_name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    if wrap:
        # A word-wrapping QLabel still reports the full unwrapped text in its
        # size hint, which would push the whole page wider than the window.
        # Ignoring the horizontal hint lets it take the width it is given.
        widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        widget.setMinimumWidth(1)
    return widget


def _rgb(hex_color: str) -> str:
    color = QColor(hex_color)
    return f"{color.red()}, {color.green()}, {color.blue()}"
