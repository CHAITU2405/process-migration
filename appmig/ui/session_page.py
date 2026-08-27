"""The live session: the remote window plus its controls and activity log."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from . import theme
from .viewer import RemoteViewer
from .widgets import Avatar, Badge, StatusDot, label


class SessionPage(QWidget):
    bringBackRequested = Signal()
    closeRemoteRequested = Signal()
    inputEvent = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.session_id = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(12)

        # -- header ------------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(12)
        self.avatar = Avatar("?", size=40)
        header.addWidget(self.avatar, 0, Qt.AlignVCenter)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = label("No active session", "PageTitle")
        titles.addWidget(self.title_label)

        subtitle_row = QHBoxLayout()
        subtitle_row.setSpacing(8)
        self.dot = StatusDot()
        subtitle_row.addWidget(self.dot)
        self.subtitle_label = label("Nothing has been transferred yet.", "PageSubtitle")
        subtitle_row.addWidget(self.subtitle_label)
        subtitle_row.addStretch(1)
        titles.addLayout(subtitle_row)
        header.addLayout(titles, 1)

        self.fidelity_badge = Badge("", theme.TEXT_FAINT)
        self.fidelity_badge.hide()
        header.addWidget(self.fidelity_badge, 0, Qt.AlignVCenter)

        self.close_button = QPushButton("Close on target")
        self.close_button.setObjectName("Danger")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.closeRemoteRequested)
        header.addWidget(self.close_button, 0, Qt.AlignVCenter)

        outer.addLayout(header)

        # -- transfer progress -------------------------------------------------
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)

        # -- remote window -----------------------------------------------------
        self.viewer = RemoteViewer()
        self.viewer.inputEvent.connect(self.inputEvent)
        outer.addWidget(self.viewer, 1)

        # -- footer ------------------------------------------------------------
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.stats_label = label("", "CardNote")
        footer.addWidget(self.stats_label)
        footer.addStretch(1)

        self.bring_back_button = QPushButton("Bring back to this laptop")
        self.bring_back_button.setCursor(Qt.PointingHandCursor)
        self.bring_back_button.setEnabled(False)
        self.bring_back_button.clicked.connect(self.bringBackRequested)
        footer.addWidget(self.bring_back_button)
        outer.addLayout(footer)

        outer.addWidget(label("ACTIVITY", "SectionLabel"))
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        outer.addWidget(self.log)

    # -- lifecycle ------------------------------------------------------------
    def begin_transfer(self, app_name: str, fidelity: str) -> None:
        self.title_label.setText(app_name)
        self.subtitle_label.setText("Capturing state and transferring...")
        self.dot.set_online(False)
        self.fidelity_badge.set_state(
            theme.FIDELITY_LABELS.get(fidelity, fidelity),
            theme.FIDELITY_COLORS.get(fidelity, theme.TEXT_FAINT),
        )
        self.fidelity_badge.show()
        self.viewer.clear("Waiting for the application to start on the target laptop...")
        self.progress.setRange(0, 0)
        self.progress.show()
        self.close_button.setEnabled(False)
        self.bring_back_button.setEnabled(False)
        self.stats_label.setText("")

        avatar_parent = self.avatar.parentWidget()
        new_avatar = Avatar(app_name, size=40, parent=avatar_parent)
        layout = self.layout().itemAt(0).layout()
        layout.replaceWidget(self.avatar, new_avatar)
        self.avatar.deleteLater()
        self.avatar = new_avatar
        self.avatar.show()

    def set_transfer_progress(self, received: int, total: int) -> None:
        if total <= 0:
            return
        self.progress.setRange(0, total)
        self.progress.setValue(received)

    def session_live(self, session_id: str, host: str) -> None:
        self.session_id = session_id
        self.progress.hide()
        self.dot.set_online(True)
        self.subtitle_label.setText(f"Running on {host}. Input is being forwarded.")
        self.close_button.setEnabled(True)
        self.bring_back_button.setEnabled(True)
        self.viewer.interactive = True
        self.viewer.clear("Connecting to the remote window...")

    def session_ended(self, message: str) -> None:
        self.session_id = ""
        self.progress.hide()
        self.dot.set_online(False)
        self.subtitle_label.setText(message)
        self.close_button.setEnabled(False)
        self.bring_back_button.setEnabled(False)
        self.viewer.interactive = False
        self.viewer.clear(message)

    def on_frame(self, meta: dict, jpeg: bytes) -> None:
        self.viewer.set_frame(meta, jpeg)
        self.stats_label.setText(
            f"{meta.get('sw', 0)} x {meta.get('sh', 0)}  ·  "
            f"frame {self.viewer.frames_received}  ·  {len(jpeg) / 1024:.0f} KB"
        )

    def append_log(self, text: str) -> None:
        self.log.appendPlainText(text)
