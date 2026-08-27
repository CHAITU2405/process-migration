"""Settings > Connection: which laptops are reachable, and which one is active."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import config
from ..discovery.peers import Peer, local_addresses
from . import theme
from .widgets import Avatar, Badge, Card, StatusDot, label


class PeerRow(Card):
    connectRequested = Signal(object)
    disconnectRequested = Signal(object)

    def __init__(self, peer: Peer, active: bool, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.peer = peer

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Avatar(peer.name), 0, Qt.AlignTop)

        details = QVBoxLayout()
        details.setSpacing(3)

        heading = QHBoxLayout()
        heading.setSpacing(8)
        heading.addWidget(label(peer.name, "CardTitle"))
        if active:
            heading.addWidget(Badge("Connected", theme.SUCCESS))
        elif peer.manual:
            heading.addWidget(Badge("Manual", theme.TEXT_FAINT))
        else:
            heading.addWidget(Badge("Discovered", theme.ACCENT))
        heading.addStretch(1)
        details.addLayout(heading)

        details.addWidget(label(f"{peer.host}:{peer.port}", "CardMeta"))
        if peer.version:
            details.addWidget(label(f"Agent {peer.version}", "CardNote"))

        row.addLayout(details, 1)

        if active:
            button = QPushButton("Disconnect")
            button.setObjectName("Danger")
            button.clicked.connect(lambda: self.disconnectRequested.emit(self.peer))
        else:
            button = QPushButton("Connect")
            button.setObjectName("Primary")
            button.clicked.connect(lambda: self.connectRequested.emit(self.peer))
        button.setCursor(Qt.PointingHandCursor)
        row.addWidget(button, 0, Qt.AlignVCenter)

        self.body.addLayout(row)


class ConnectionPage(QWidget):
    connectRequested = Signal(str, int)
    disconnectRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows: Dict[str, PeerRow] = {}
        self._peers: List[Peer] = []
        self._active_key = ""
        self._active_name = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(6)

        outer.addWidget(label("Target laptops", "PageTitle"))
        outer.addWidget(label(
            "Agents announce themselves on the local link. A Thunderbolt or USB4 "
            "cable between the two machines shows up here just like Ethernet does.",
            "PageSubtitle", wrap=True,
        ))

        status = QHBoxLayout()
        status.setContentsMargins(0, 16, 0, 4)
        status.setSpacing(8)
        self.dot = StatusDot()
        status.addWidget(self.dot)
        self.status_label = label("Not connected", "CardMeta")
        status.addWidget(self.status_label)
        status.addStretch(1)
        outer.addLayout(status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setContentsMargins(0, 8, 8, 0)
        self.list_layout.setSpacing(8)
        self.empty_label = label(
            "No agents found yet. Start the agent on the other laptop, or add it "
            "by address below.", "CardNote", wrap=True)
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        outer.addWidget(label("ADD BY ADDRESS", "SectionLabel"))
        manual = QHBoxLayout()
        manual.setSpacing(8)
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("192.168.1.42")
        self.host_input.returnPressed.connect(self._on_manual_connect)
        manual.addWidget(self.host_input, 1)

        self.port_input = QLineEdit(str(config.CONTROL_PORT))
        self.port_input.setFixedWidth(80)
        manual.addWidget(self.port_input)

        connect_button = QPushButton("Connect")
        connect_button.setObjectName("Primary")
        connect_button.setCursor(Qt.PointingHandCursor)
        connect_button.clicked.connect(self._on_manual_connect)
        manual.addWidget(connect_button)
        outer.addLayout(manual)

        addresses = local_addresses()
        if addresses:
            outer.addWidget(label(
                "This laptop is reachable at: " + ",  ".join(addresses),
                "CardNote", wrap=True))

    # -- state ----------------------------------------------------------------
    def set_status(self, online: bool, text: str) -> None:
        self.dot.set_online(online)
        self.status_label.setText(text)

    def set_active_peer(self, key: str, name: str = "") -> None:
        """Mark the connected agent.

        Address alone is not enough: an agent beacons from its LAN address but
        may be reached on a different one (loopback, a second interface, a
        Thunderbolt link), so the agent name is matched too.
        """
        self._active_key = key
        self._active_name = name
        self._rebuild()

    def set_peers(self, peers: List[Peer]) -> None:
        self._peers = peers
        self._rebuild()

    def _on_manual_connect(self) -> None:
        host = self.host_input.text().strip()
        if not host:
            return
        try:
            port = int(self.port_input.text().strip() or config.CONTROL_PORT)
        except ValueError:
            port = config.CONTROL_PORT
        self.connectRequested.emit(host, port)

    # -- rendering ------------------------------------------------------------
    def _rebuild(self) -> None:
        for key in list(self._rows):
            row = self._rows.pop(key)
            self.list_layout.removeWidget(row)
            row.deleteLater()

        self.empty_label.setVisible(not self._peers)

        for index, peer in enumerate(self._peers):
            active = peer.key == self._active_key or (
                bool(self._active_name) and peer.name == self._active_name)
            row = PeerRow(peer, active=active)
            row.connectRequested.connect(
                lambda p: self.connectRequested.emit(p.host, p.port))
            row.disconnectRequested.connect(lambda _p: self.disconnectRequested.emit())
            self._rows[peer.key] = row
            self.list_layout.insertWidget(index + 1, row)
