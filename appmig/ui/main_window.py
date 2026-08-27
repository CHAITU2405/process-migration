"""The controller window: laptop 1."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import config, migrate
from ..adapters.registry import adapter_for
from ..discovery.apps import AppInfo
from ..discovery.peers import PeerWatcher
from . import theme
from .apps_page import AppsPage
from .connection_page import ConnectionPage
from .link import AgentLink
from .session_page import SessionPage
from .widgets import StatusDot, label

PAGE_APPS, PAGE_CONNECTION, PAGE_SESSION = 0, 1, 2


class CaptureWorker(QObject):
    """Runs the close-and-capture sequence off the GUI thread."""

    finished = Signal(object)     # migrate.CaptureResult
    failed = Signal(str, bool)    # message, was_it_a_refused_close
    progress = Signal(str)

    def run(self, app: AppInfo) -> None:
        threading.Thread(target=self._run, args=(app,),
                         name="capture", daemon=True).start()

    def _run(self, app: AppInfo) -> None:
        try:
            result = migrate.capture_and_close(app, log=self.progress.emit)
        except migrate.AppWouldNotClose as exc:
            self.failed.emit(str(exc), True)
        except Exception as exc:
            self.failed.emit(str(exc), False)
        else:
            self.finished.emit(result)


class MainWindow(QWidget):
    # PeerWatcher calls back from its own socket thread. Widgets may only be
    # touched on the GUI thread, so the callback does nothing but emit this and
    # let Qt queue the delivery.
    peersChanged = Signal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.APP_NAME} — Controller")
        self.resize(1180, 780)

        self.link = AgentLink(self)
        self.capture_worker = CaptureWorker(self)
        self.pending: Optional[migrate.CaptureResult] = None
        self.active_rollback: Optional[Path] = None
        self.active_session = ""

        self._build_ui()
        self._wire_signals()

        self.peer_watcher = PeerWatcher(on_change=self._on_peers_changed)
        self.peer_watcher.start()

    # -- layout ---------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # sidebar
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 12)
        side_layout.setSpacing(0)

        side_layout.addWidget(label(config.APP_NAME, "SidebarTitle"))
        side_layout.addWidget(label("Move an app, keep the screen", "SidebarSubtitle"))

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, text in enumerate(("Applications", "Connection", "Live session")):
            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _c, i=index: self.stack.setCurrentIndex(i))
            self.nav_group.addButton(button, index)
            side_layout.addWidget(button)
        self.nav_group.button(PAGE_APPS).setChecked(True)

        side_layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(18, 0, 18, 0)
        footer.setSpacing(8)
        self.side_dot = StatusDot()
        footer.addWidget(self.side_dot)
        self.side_status = label("Not connected", "CardNote")
        footer.addWidget(self.side_status, 1)
        side_layout.addLayout(footer)

        root.addWidget(sidebar)

        # pages
        self.stack = QStackedWidget()
        self.apps_page = AppsPage()
        self.connection_page = ConnectionPage()
        self.session_page = SessionPage()
        for page in (self.apps_page, self.connection_page, self.session_page):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

    def _wire_signals(self) -> None:
        self.stack.currentChanged.connect(
            lambda i: self.nav_group.button(i).setChecked(True))

        self.peersChanged.connect(self.connection_page.set_peers)
        self.apps_page.transferRequested.connect(self._on_transfer_requested)
        self.connection_page.connectRequested.connect(self._on_connect_requested)
        self.connection_page.disconnectRequested.connect(
            lambda: self.link.disconnect_from("disconnected by user"))

        self.session_page.inputEvent.connect(self._on_input_event)
        self.session_page.closeRemoteRequested.connect(self._on_close_remote)
        self.session_page.bringBackRequested.connect(self._on_bring_back)

        self.link.connected.connect(self._on_connected)
        self.link.disconnected.connect(self._on_disconnected)
        self.link.errorOccurred.connect(self._on_error)
        self.link.transferProgress.connect(self._on_transfer_progress)
        self.link.restoreResult.connect(self._on_restore_result)
        self.link.frameReceived.connect(self._on_frame)
        self.link.sessionGone.connect(self._on_session_gone)

        self.capture_worker.progress.connect(self.session_page.append_log)
        self.capture_worker.finished.connect(self._on_capture_finished)
        self.capture_worker.failed.connect(self._on_capture_failed)

    # -- connection -----------------------------------------------------------
    def _on_peers_changed(self, peers) -> None:
        """Called on the discovery thread. Hand off to the GUI thread."""
        self.peersChanged.emit(list(peers))

    def _on_connect_requested(self, host: str, port: int) -> None:
        self.connection_page.set_status(False, f"Connecting to {host}...")
        self.link.connect_to(host, port)

    def _on_connected(self, info: dict) -> None:
        name = info.get("name", self.link.peer_host)
        text = f"Connected to {name} ({self.link.peer_host})"
        self.connection_page.set_status(True, text)
        self.connection_page.set_active_peer(
            f"{self.link.peer_host}:{self.link.peer_port}", name)
        self.side_dot.set_online(True)
        self.side_status.setText(name)
        self.apps_page.set_can_transfer(True)
        self.session_page.append_log(text)

    def _on_disconnected(self, reason: str) -> None:
        self.connection_page.set_status(False, f"Not connected — {reason}")
        self.connection_page.set_active_peer("", "")
        self.side_dot.set_online(False)
        self.side_status.setText("Not connected")
        self.apps_page.set_can_transfer(False)
        if self.active_session:
            self.session_page.session_ended(f"Connection lost — {reason}")
            self.active_session = ""

    def _on_error(self, message: str) -> None:
        self.session_page.append_log(f"Error: {message}")
        self.connection_page.set_status(False, message)

    # -- transfer -------------------------------------------------------------
    def _on_transfer_requested(self, app: AppInfo) -> None:
        if not self.link.is_connected:
            QMessageBox.information(
                self, "No target laptop",
                "Connect to a target laptop on the Connection page first.")
            return

        adapter = adapter_for(app)
        detail = (
            f"<b>{app.display_name}</b> will close on this laptop and restart on "
            f"<b>{self.link.peer_name}</b>.<br><br>"
            f"<b>What carries across:</b> {adapter.carries}<br>"
            f"<b>Fidelity:</b> {theme.FIDELITY_LABELS.get(adapter.fidelity)}<br><br>"
        )
        if adapter.fidelity == "fresh":
            detail += (
                "This application has no session format we can read, so it will "
                "start clean. Save your work before continuing.<br><br>"
            )
        detail += (
            "The captured state is kept on this laptop until the target confirms "
            "the app is running, so a failed transfer can be undone."
        )

        box = QMessageBox(self)
        box.setWindowTitle("Transfer application")
        box.setTextFormat(Qt.RichText)
        box.setText(detail)
        box.setIcon(QMessageBox.Question)
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        box.button(QMessageBox.Ok).setText("Close here and transfer")
        if box.exec() != QMessageBox.Ok:
            return

        self.stack.setCurrentIndex(PAGE_SESSION)
        self.session_page.begin_transfer(app.display_name, adapter.fidelity)
        self.session_page.append_log(f"Transferring {app.display_name} to {self.link.peer_name}")
        self.capture_worker.run(app)

    def _on_capture_finished(self, result: migrate.CaptureResult) -> None:
        self.pending = result
        self.active_rollback = result.rollback_path
        for note in result.warnings:
            self.session_page.append_log(f"  · {note}")
        self.session_page.append_log(
            f"Sending {result.size_mb:.2f} MB to {self.link.peer_name}...")
        self.link.send_bundle(
            result.session_id,
            {"app_name": result.state.app_name, "adapter": result.adapter.id},
            result.blob,
        )

    def _on_capture_failed(self, message: str, refused_close: bool) -> None:
        self.session_page.session_ended("Transfer cancelled.")
        self.session_page.append_log(f"Failed: {message}")
        QMessageBox.warning(
            self, "Application did not close" if refused_close else "Capture failed",
            message)
        self.stack.setCurrentIndex(PAGE_APPS)
        self.apps_page.refresh()

    def _on_transfer_progress(self, session_id: str, received: int, total: int) -> None:
        self.session_page.set_transfer_progress(received, total)

    def _on_restore_result(self, payload: dict) -> None:
        if payload.get("ok"):
            self.active_session = payload.get("session", "")
            self.session_page.session_live(self.active_session, self.link.peer_name)
            self.session_page.append_log(
                f"Running on {self.link.peer_name} as pid {payload.get('pid')}")
            for warning in payload.get("warnings", []):
                self.session_page.append_log(f"  ! {warning}")
            migrate.discard_rollback(self.active_rollback)
            self.active_rollback = None
            self.pending = None
            self.apps_page.refresh()
            return

        error = payload.get("error", "unknown error")
        self.session_page.append_log(f"Restore failed: {error}")
        self.session_page.session_ended("Restore failed on the target laptop.")
        self._offer_rollback(error)

    def _offer_rollback(self, error: str) -> None:
        if self.pending is None:
            QMessageBox.critical(self, "Restore failed", error)
            return
        answer = QMessageBox.critical(
            self, "Restore failed",
            f"{error}\n\nThe captured state is still held on this laptop. "
            f"Bring {self.pending.state.app_name} back up here?",
            QMessageBox.No | QMessageBox.Yes, QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self._restore_here()

    def _restore_here(self) -> None:
        if self.pending is None:
            return
        try:
            migrate.restore_locally(self.pending.blob, log=self.session_page.append_log)
        except Exception as exc:
            QMessageBox.critical(
                self, "Could not restore",
                f"{exc}\n\nThe state bundle is saved at:\n{self.pending.rollback_path}")
            return
        migrate.discard_rollback(self.active_rollback)
        self.active_rollback = None
        self.pending = None
        self.stack.setCurrentIndex(PAGE_APPS)
        self.apps_page.refresh()

    # -- live session ---------------------------------------------------------
    def _on_input_event(self, event: dict) -> None:
        if self.active_session:
            self.link.send_input(self.active_session, event)

    def _on_frame(self, session_id: str, meta: dict, jpeg: bytes) -> None:
        if session_id == self.active_session:
            self.session_page.on_frame(meta, jpeg)

    def _on_close_remote(self) -> None:
        if not self.active_session:
            return
        answer = QMessageBox.question(
            self, "Close on target",
            "Close the application on the target laptop? Anything unsaved there "
            "will be handled by the application's own prompts, which you will not "
            "see from here.",
            QMessageBox.No | QMessageBox.Yes, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.link.kill_session(self.active_session)

    def _on_bring_back(self) -> None:
        QMessageBox.information(
            self, "Bring back",
            "Return transfers are not implemented yet. To move the session back, "
            "run the controller on the other laptop and transfer from there.\n\n"
            "Closing the app on the target will end this session.")

    def _on_session_gone(self, session_id: str) -> None:
        if session_id != self.active_session:
            return
        self.active_session = ""
        self.session_page.session_ended("The application closed on the target laptop.")

    # -- shutdown -------------------------------------------------------------
    def closeEvent(self, event) -> None:
        self.peer_watcher.stop()
        self.link.disconnect_from("controller closing")
        super().closeEvent(event)
