"""Controller-side network link, wrapped in Qt signals.

Socket work happens on plain worker threads; results reach the GUI through
signals, which Qt queues onto the main thread for us. Nothing here touches
widgets directly.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .. import config, security
from ..protocol import channel as chan
from ..protocol.channel import Channel, ChannelClosed
from ..protocol.messages import Msg


class AgentLink(QObject):
    connected = Signal(dict)
    disconnected = Signal(str)
    logMessage = Signal(str)
    transferProgress = Signal(str, int, int)
    restoreResult = Signal(dict)
    frameReceived = Signal(str, dict, bytes)
    sessionGone = Signal(str)
    errorOccurred = Signal(str)
    pairingRequired = Signal(str, int)   # host, port

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._channel: Optional[Channel] = None
        self._reader: Optional[threading.Thread] = None
        self._heartbeat: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.peer_name = ""
        self.peer_host = ""
        self.peer_port = 0
        self.last_pong = 0.0
        self._pending_code = ""

    # -- state ----------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._channel is not None

    # -- connect / disconnect -------------------------------------------------
    def connect_to(self, host: str, port: int = config.CONTROL_PORT,
                   code: Optional[str] = None) -> None:
        """Non-blocking. Emits ``connected``, ``pairingRequired`` or ``errorOccurred``.

        ``code`` is the target's pairing code. When omitted, a code remembered
        from a previous successful pairing with this host is used.
        """
        if self.is_connected:
            self.disconnect_from("switching target")
        threading.Thread(target=self._do_connect, args=(host, port, code),
                         name="link-connect", daemon=True).start()

    def _do_connect(self, host: str, port: int,
                    code: Optional[str] = None) -> None:
        try:
            channel = chan.connect(host, port, config.CONNECT_TIMEOUT)
        except OSError as exc:
            self.errorOccurred.emit(f"Could not reach {host}:{port} - {exc}")
            return

        with self._lock:
            self._channel = channel
            self._stop = threading.Event()
        self.peer_host = host
        self.peer_port = port

        self._pending_code = security.normalise(code) if code else security.recall_code(host)
        try:
            channel.send(Msg.HELLO, {
                "role": "controller",
                "version": config.VERSION,
                "code": self._pending_code,
            })
        except ChannelClosed as exc:
            self.errorOccurred.emit(f"Handshake failed: {exc}")
            self._teardown("handshake failed")
            return

        self._reader = threading.Thread(target=self._read_loop, name="link-read", daemon=True)
        self._reader.start()
        self._heartbeat = threading.Thread(target=self._heartbeat_loop,
                                           name="link-ping", daemon=True)
        self._heartbeat.start()

    def disconnect_from(self, reason: str = "disconnected by user") -> None:
        self._teardown(reason)

    def _teardown(self, reason: str) -> None:
        with self._lock:
            channel, self._channel = self._channel, None
        self._stop.set()
        if channel is not None:
            channel.close()
            self.disconnected.emit(reason)

    # -- loops ----------------------------------------------------------------
    def _read_loop(self) -> None:
        channel = self._channel
        if channel is None:
            return
        try:
            while not self._stop.is_set():
                mtype, payload, blob = channel.recv()
                self._dispatch(mtype, payload, blob)
        except ChannelClosed as exc:
            if not self._stop.is_set():
                self._teardown(str(exc))
        except Exception as exc:
            self._teardown(f"link error: {exc}")

    def _dispatch(self, mtype: int, payload: dict, blob: bytes) -> None:
        if mtype == Msg.HELLO_ACK:
            if self._pending_code:
                security.remember_code(self.peer_host, self._pending_code)
            self.peer_name = payload.get("name", self.peer_host)
            self.last_pong = time.monotonic()
            self.connected.emit(payload)
        elif mtype == Msg.PONG:
            self.last_pong = time.monotonic()
        elif mtype == Msg.TRANSFER_ACK:
            if payload.get("stage") == "chunk":
                self.transferProgress.emit(
                    payload.get("session", ""),
                    int(payload.get("received", 0)),
                    int(payload.get("total", 0)),
                )
        elif mtype == Msg.RESTORE_RESULT:
            self.restoreResult.emit(payload)
        elif mtype == Msg.FRAME:
            self.frameReceived.emit(payload.get("session", ""), payload, blob)
        elif mtype == Msg.SESSION_GONE:
            self.sessionGone.emit(payload.get("session", ""))
        elif mtype == Msg.LOG:
            self.logMessage.emit(payload.get("text", ""))
        elif mtype == Msg.ERROR:
            if payload.get("needs_code"):
                security.forget_code(self.peer_host)
                self.pairingRequired.emit(self.peer_host, self.peer_port)
            else:
                self.errorOccurred.emit(payload.get("error", "unknown agent error"))
            if payload.get("fatal"):
                self._teardown("not paired")

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(config.HEARTBEAT_INTERVAL):
            channel = self._channel
            if channel is None:
                return
            try:
                channel.send(Msg.PING, {"t": time.time()})
            except ChannelClosed:
                self._teardown("connection lost")
                return
            if self.last_pong and (time.monotonic() - self.last_pong) > config.HEARTBEAT_TIMEOUT:
                self._teardown("the agent stopped responding")
                return

    # -- sending --------------------------------------------------------------
    def send_bundle(self, session_id: str, meta: dict, blob: bytes) -> None:
        """Ship a captured state bundle. Runs on its own thread."""
        threading.Thread(
            target=self._do_send_bundle, args=(session_id, meta, blob),
            name="link-transfer", daemon=True,
        ).start()

    def _do_send_bundle(self, session_id: str, meta: dict, blob: bytes) -> None:
        from .. import bundle as bundle_mod

        channel = self._channel
        if channel is None:
            self.errorOccurred.emit("Not connected to a target laptop.")
            return
        try:
            channel.send(Msg.TRANSFER_BEGIN, {
                "session": session_id, "meta": meta, "size": len(blob)})
            for offset in range(0, len(blob), config.CHUNK_SIZE):
                if self._stop.is_set():
                    return
                channel.send(Msg.TRANSFER_CHUNK, {"session": session_id},
                             blob[offset:offset + config.CHUNK_SIZE])
            channel.send(Msg.TRANSFER_END, {
                "session": session_id, "sha256": bundle_mod.digest(blob)})
        except ChannelClosed as exc:
            self.errorOccurred.emit(f"Transfer interrupted: {exc}")

    def send_input(self, session_id: str, event: dict) -> None:
        channel = self._channel
        if channel is None:
            return
        try:
            channel.send(Msg.INPUT, {"session": session_id, "event": event})
        except ChannelClosed:
            pass

    def kill_session(self, session_id: str) -> None:
        channel = self._channel
        if channel is None:
            return
        try:
            channel.send(Msg.SESSION_KILL, {"session": session_id})
        except ChannelClosed:
            pass
