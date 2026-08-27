"""Connection: offer this laptop as a target, and pick one to send to."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from .. import config, security
from ..discovery import tailscale as ts
from ..discovery.peers import local_addresses
from . import theme
from .targets import SOURCE_LOCAL, SOURCE_MANUAL, SOURCE_TAILSCALE, Target
from .widgets import Avatar, Badge, Card, StatusDot, label

_SOURCE_BADGES = {
    SOURCE_LOCAL: ("Local link", theme.SUCCESS),
    SOURCE_TAILSCALE: ("Tailscale", theme.ACCENT),
    SOURCE_MANUAL: ("Manual", theme.TEXT_FAINT),
}


class ThisLaptopCard(Card):
    """Turn this machine into a target, and show the code needed to pair with it."""

    toggleRequested = Signal(bool)     # want_running
    rotateRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._running = False

        header = QHBoxLayout()
        header.setSpacing(10)
        self.dot = StatusDot()
        header.addWidget(self.dot, 0, Qt.AlignVCenter)
        header.addWidget(label("This laptop", "CardTitle"))
        self.state_badge = Badge("Not receiving", theme.TEXT_FAINT)
        header.addWidget(self.state_badge)
        header.addStretch(1)

        self.toggle_button = QPushButton("Start receiving")
        self.toggle_button.setObjectName("Primary")
        self.toggle_button.setCursor(Qt.PointingHandCursor)
        self.toggle_button.clicked.connect(
            lambda: self.toggleRequested.emit(not self._running))
        header.addWidget(self.toggle_button)
        self.body.addLayout(header)

        self.body.addWidget(label(
            "Turn this on to let the other laptop send applications here. "
            "Leave it off if this machine is only the one you sit at.",
            "CardNote", wrap=True))

        # -- pairing code ------------------------------------------------------
        code_row = QHBoxLayout()
        code_row.setSpacing(8)
        code_row.addWidget(label("PAIRING CODE", "SectionLabel"))
        self.code_label = label(security.format_code(security.local_code()), "CardTitle")
        self.code_label.setStyleSheet(
            f"font-family: Consolas, monospace; letter-spacing: 2px; color: {theme.ACCENT};")
        code_row.addWidget(self.code_label)

        copy_button = QPushButton("Copy")
        copy_button.setCursor(Qt.PointingHandCursor)
        copy_button.clicked.connect(self._copy_code)
        code_row.addWidget(copy_button)

        rotate_button = QPushButton("New code")
        rotate_button.setCursor(Qt.PointingHandCursor)
        rotate_button.clicked.connect(self.rotateRequested)
        code_row.addWidget(rotate_button)
        code_row.addStretch(1)
        self.body.addLayout(code_row)

        self.body.addWidget(label(
            "Enter this on the other laptop the first time it connects. It is "
            "required for anything but a connection from this same machine, "
            "because an agent launches applications and receives keystrokes.",
            "CardNote", wrap=True))

        self.address_label = label("", "CardNote", wrap=True)
        self.body.addWidget(self.address_label)
        self.refresh_addresses()

    def _copy_code(self) -> None:
        QApplication.clipboard().setText(security.local_code())

    def refresh_code(self) -> None:
        self.code_label.setText(security.format_code(security.local_code()))

    def refresh_addresses(self) -> None:
        parts = []
        tailscale_ip = ""
        state = ts.status()
        if state.running and state.self_ip:
            tailscale_ip = state.self_ip
            suffix = f", {state.self_host}" if state.self_host else ""
            parts.append(f"{tailscale_ip} (Tailscale{suffix})")

        # The Tailscale adapter also shows up in the interface list, so skip it
        # there rather than naming the same address twice.
        for entry in local_addresses():
            if tailscale_ip and entry.startswith(tailscale_ip):
                continue
            parts.append(entry)

        self.address_label.setText(
            "Reachable at: " + ",  ".join(parts) if parts else "No addresses found.")

    def set_running(self, running: bool, port: int = config.CONTROL_PORT) -> None:
        self._running = running
        self.dot.set_online(running)
        if running:
            self.state_badge.set_state(f"Receiving on {port}", theme.SUCCESS)
            self.toggle_button.setText("Stop receiving")
            self.toggle_button.setObjectName("Danger")
        else:
            self.state_badge.set_state("Not receiving", theme.TEXT_FAINT)
            self.toggle_button.setText("Start receiving")
            self.toggle_button.setObjectName("Primary")
        # Re-apply the stylesheet so the changed objectName takes effect.
        self.toggle_button.style().unpolish(self.toggle_button)
        self.toggle_button.style().polish(self.toggle_button)


class TargetRow(Card):
    connectRequested = Signal(object)
    disconnectRequested = Signal(object)

    def __init__(self, target: Target, active: bool, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.target = target

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Avatar(target.name), 0, Qt.AlignTop)

        details = QVBoxLayout()
        details.setSpacing(3)

        heading = QHBoxLayout()
        heading.setSpacing(8)
        heading.addWidget(label(target.name, "CardTitle"))

        text, colour = _SOURCE_BADGES.get(target.source, ("Unknown", theme.TEXT_FAINT))
        heading.addWidget(Badge(text, colour))

        if active:
            heading.addWidget(Badge("Connected", theme.SUCCESS))
        elif target.source == SOURCE_TAILSCALE and target.online:
            if target.link == "direct":
                heading.addWidget(Badge("Direct", theme.SUCCESS))
            elif target.link == "relay":
                heading.addWidget(Badge("Relayed", theme.WARNING))
        heading.addStretch(1)
        details.addLayout(heading)

        details.addWidget(label(f"{target.host}:{target.port}", "CardMeta"))
        details.addWidget(label(target.status_text, "CardNote", wrap=True))
        row.addLayout(details, 1)

        if active:
            button = QPushButton("Disconnect")
            button.setObjectName("Danger")
            button.clicked.connect(lambda: self.disconnectRequested.emit(self.target))
        else:
            button = QPushButton("Connect")
            button.setObjectName("Primary")
            button.setEnabled(target.connectable)
            button.clicked.connect(lambda: self.connectRequested.emit(self.target))
        button.setCursor(Qt.PointingHandCursor)
        row.addWidget(button, 0, Qt.AlignVCenter)

        self.body.addLayout(row)


class ConnectionPage(QWidget):
    connectRequested = Signal(str, int, str)   # host, port, code ("" = use remembered)
    disconnectRequested = Signal()
    agentToggleRequested = Signal(bool)
    rotateCodeRequested = Signal()
    refreshTailscaleRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows: Dict[str, TargetRow] = {}
        self._targets: List[Target] = []
        self._active_key = ""
        self._active_name = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(6)

        outer.addWidget(label("Connection", "PageTitle"))
        outer.addWidget(label(
            "Either laptop can receive. Targets on the local link are found by "
            "broadcast; targets across your tailnet come from Tailscale.",
            "PageSubtitle", wrap=True))

        self.this_laptop = ThisLaptopCard()
        self.this_laptop.toggleRequested.connect(self.agentToggleRequested)
        self.this_laptop.rotateRequested.connect(self.rotateCodeRequested)
        outer.addWidget(self.this_laptop)

        status = QHBoxLayout()
        status.setContentsMargins(0, 12, 0, 2)
        status.setSpacing(8)
        self.dot = StatusDot()
        status.addWidget(self.dot)
        self.status_label = label("Not connected to any target", "CardMeta")
        status.addWidget(self.status_label)
        status.addStretch(1)

        self.tailscale_label = label("", "CardNote")
        status.addWidget(self.tailscale_label)
        refresh = QPushButton("Refresh")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refreshTailscaleRequested)
        status.addWidget(refresh)
        outer.addLayout(status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setContentsMargins(0, 8, 8, 0)
        self.list_layout.setSpacing(8)
        self.empty_label = label(
            "No targets yet. Start receiving on the other laptop, or add it by "
            "address below.", "CardNote", wrap=True)
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        outer.addWidget(label("ADD BY ADDRESS", "SectionLabel"))
        manual = QHBoxLayout()
        manual.setSpacing(8)
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("100.67.211.4  or  192.168.1.42")
        self.host_input.returnPressed.connect(self._on_manual_connect)
        manual.addWidget(self.host_input, 2)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("pairing code")
        self.code_input.setMaxLength(12)
        self.code_input.returnPressed.connect(self._on_manual_connect)
        manual.addWidget(self.code_input, 1)

        self.port_input = QLineEdit(str(config.CONTROL_PORT))
        self.port_input.setFixedWidth(74)
        manual.addWidget(self.port_input)

        connect_button = QPushButton("Connect")
        connect_button.setObjectName("Primary")
        connect_button.setCursor(Qt.PointingHandCursor)
        connect_button.clicked.connect(self._on_manual_connect)
        manual.addWidget(connect_button)
        outer.addLayout(manual)

    # -- state ----------------------------------------------------------------
    def set_status(self, online: bool, text: str) -> None:
        self.dot.set_online(online)
        self.status_label.setText(text)

    def set_active_peer(self, key: str, name: str = "") -> None:
        self._active_key = key
        self._active_name = name
        self._rebuild()

    def set_targets(self, targets: List[Target]) -> None:
        self._targets = targets
        self._rebuild()

    def set_tailscale_state(self, running: bool, message: str) -> None:
        if running:
            self.tailscale_label.setText("Tailscale connected")
            self.tailscale_label.setStyleSheet(f"color: {theme.SUCCESS};")
        else:
            self.tailscale_label.setText(message or "Tailscale unavailable")
            self.tailscale_label.setStyleSheet(f"color: {theme.TEXT_FAINT};")

    def set_agent_running(self, running: bool, port: int = config.CONTROL_PORT) -> None:
        self.this_laptop.set_running(running, port)

    def refresh_code(self) -> None:
        self.this_laptop.refresh_code()

    def _on_manual_connect(self) -> None:
        host = self.host_input.text().strip()
        if not host:
            return
        try:
            port = int(self.port_input.text().strip() or config.CONTROL_PORT)
        except ValueError:
            port = config.CONTROL_PORT
        self.connectRequested.emit(host, port, self.code_input.text().strip())

    # -- rendering ------------------------------------------------------------
    def _rebuild(self) -> None:
        for key in list(self._rows):
            row = self._rows.pop(key)
            self.list_layout.removeWidget(row)
            row.deleteLater()

        self.empty_label.setVisible(not self._targets)

        for index, target in enumerate(self._targets):
            active = target.key == self._active_key or (
                bool(self._active_name) and target.name == self._active_name)
            row = TargetRow(target, active=active)
            row.connectRequested.connect(
                lambda t: self.connectRequested.emit(t.host, t.port, ""))
            row.disconnectRequested.connect(lambda _t: self.disconnectRequested.emit())
            self._rows[target.key] = row
            self.list_layout.insertWidget(index + 1, row)
