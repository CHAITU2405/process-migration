"""Run the agent inside the controller process, driven from the UI.

This is what lets one window manage both roles. Either laptop can offer itself
as a target and drive a transfer to the other, without a second console window
or a second command to remember.

The agent still runs on its own thread; only its log and state reach Qt, via
signals.
"""
from __future__ import annotations

import socket
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .. import config
from .server import Agent


class EmbeddedAgent(QObject):
    """Start/stop the agent in-process and report what it is doing."""

    started = Signal(int)        # port
    stopped = Signal(str)        # reason
    logMessage = Signal(str)
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._agent: Optional[Agent] = None
        self._thread: Optional[threading.Thread] = None
        self._port = config.CONTROL_PORT

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def port(self) -> int:
        return self._port

    def start(self, name: Optional[str] = None,
              port: int = config.CONTROL_PORT) -> None:
        if self.is_running:
            return

        if _port_in_use(port):
            self.failed.emit(
                f"Port {port} is already in use. Another AppMigrate agent is "
                "probably running on this laptop."
            )
            return

        self._port = port
        self._agent = Agent(
            port=port,
            log=lambda message: self.logMessage.emit(message),
            name=name or socket.gethostname(),
        )
        self._thread = threading.Thread(
            target=self._run, name="embedded-agent", daemon=True)
        self._thread.start()
        self.started.emit(port)

    def _run(self) -> None:
        try:
            self._agent.serve_forever()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.stopped.emit("agent stopped")

    def stop(self) -> None:
        if self._agent is not None:
            self._agent.shutdown()
            self._agent = None
        self._thread = None


def _port_in_use(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("", port))
        return False
    except OSError:
        return True
    finally:
        sock.close()
