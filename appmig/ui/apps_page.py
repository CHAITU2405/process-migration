"""Settings > Applications: what is running here, and what will survive a move."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..adapters.registry import adapter_for
from ..discovery.apps import AppInfo, list_running_apps
from . import theme
from .widgets import Avatar, Badge, Card, label

REFRESH_INTERVAL_MS = 4000


class AppRow(Card):
    transferRequested = Signal(object)

    def __init__(self, app: AppInfo, can_transfer: bool, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app
        adapter = adapter_for(app)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Avatar(app.display_name), 0, Qt.AlignTop)

        details = QVBoxLayout()
        details.setSpacing(3)

        heading = QHBoxLayout()
        heading.setSpacing(8)
        heading.addWidget(label(app.display_name, "CardTitle"))
        heading.addWidget(Badge(
            theme.FIDELITY_LABELS.get(adapter.fidelity, adapter.fidelity),
            theme.FIDELITY_COLORS.get(adapter.fidelity, theme.TEXT_FAINT),
        ))
        heading.addStretch(1)
        details.addLayout(heading)

        title = app.title if len(app.title) <= 70 else app.title[:67] + "..."
        details.addWidget(label(title, "CardMeta"))
        details.addWidget(label(
            f"PID {app.pid}  ·  {app.memory_mb:,.0f} MB  ·  {adapter.carries}",
            "CardNote", wrap=True,
        ))

        row.addLayout(details, 1)

        self.transfer_button = QPushButton("Transfer")
        self.transfer_button.setObjectName("Primary")
        self.transfer_button.setCursor(Qt.PointingHandCursor)
        self.transfer_button.setEnabled(can_transfer)
        self.transfer_button.setToolTip(
            "" if can_transfer else "Connect to a target laptop first."
        )
        self.transfer_button.clicked.connect(lambda: self.transferRequested.emit(self.app))
        row.addWidget(self.transfer_button, 0, Qt.AlignVCenter)

        self.body.addLayout(row)

    def set_can_transfer(self, can_transfer: bool) -> None:
        self.transfer_button.setEnabled(can_transfer)
        self.transfer_button.setToolTip(
            "" if can_transfer else "Connect to a target laptop first."
        )


class AppsPage(QWidget):
    transferRequested = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows: Dict[str, AppRow] = {}
        self._apps: List[AppInfo] = []
        self._can_transfer = False
        self._filter = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(6)

        outer.addWidget(label("Running applications", "PageTitle"))
        outer.addWidget(label(
            "Pick an application to move to the connected laptop. It closes here, "
            "restarts there, and its window comes back to this screen.",
            "PageSubtitle", wrap=True,
        ))

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 14, 0, 10)
        controls.setSpacing(10)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter applications...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_filter_changed)
        controls.addWidget(self.search, 1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("CardMeta")
        controls.addWidget(self.count_label)

        refresh = QPushButton("Refresh")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        outer.addLayout(controls)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # -- state ----------------------------------------------------------------
    def set_can_transfer(self, can_transfer: bool) -> None:
        self._can_transfer = can_transfer
        for row in self._rows.values():
            row.set_can_transfer(can_transfer)

    def _on_filter_changed(self, text: str) -> None:
        self._filter = text.strip().lower()
        self._rebuild()

    def refresh(self) -> None:
        try:
            self._apps = list_running_apps()
        except Exception:
            return
        self._rebuild()

    # -- rendering ------------------------------------------------------------
    def _rebuild(self) -> None:
        visible = [
            app for app in self._apps
            if not self._filter
            or self._filter in app.display_name.lower()
            or self._filter in app.title.lower()
            or self._filter in app.exe_name.lower()
        ]
        wanted = {app.key for app in visible}

        for key in list(self._rows):
            if key not in wanted:
                row = self._rows.pop(key)
                self.list_layout.removeWidget(row)
                row.deleteLater()

        for index, app in enumerate(visible):
            existing = self._rows.get(app.key)
            if existing is None:
                row = AppRow(app, self._can_transfer)
                row.transferRequested.connect(self.transferRequested)
                self._rows[app.key] = row
                self.list_layout.insertWidget(index, row)

        total = len(self._apps)
        shown = len(visible)
        self.count_label.setText(
            f"{shown} of {total} shown" if shown != total else f"{total} running"
        )
