"""The agent: laptop 2. Receives state, restores it, runs the app, streams the UI.

Handles one controller at a time. A second connection is refused rather than
queued, because two controllers driving the same desktop would fight over input.
"""
from __future__ import annotations

import socket
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from .. import bundle, config, migrate, security
from ..adapters.registry import adapter_by_id
from ..discovery.peers import BeaconBroadcaster
from ..protocol.channel import Channel, ChannelClosed
from ..protocol.messages import Msg
from ..winapi import windows as win
from ..winapi.input import InputInjector
from .streamer import WindowStreamer

Logger = Callable[[str], None]


@dataclass
class Session:
    session_id: str
    app_name: str
    pid: int
    hwnd: int
    workdir: Path
    streamer: Optional[WindowStreamer] = None
    injector: Optional[InputInjector] = None
    warnings: list = field(default_factory=list)


class _Incoming:
    """Accumulates a chunked bundle transfer."""

    def __init__(self, session_id: str, meta: dict, total: int):
        self.session_id = session_id
        self.meta = meta
        self.total = total
        self.parts: list = []
        self.received = 0

    def add(self, chunk: bytes) -> None:
        self.parts.append(chunk)
        self.received += len(chunk)

    def blob(self) -> bytes:
        return b"".join(self.parts)


class Agent:
    def __init__(self, port: int = config.CONTROL_PORT, log: Logger = print,
                 name: Optional[str] = None):
        self.port = port
        self.log = log
        self.name = name or socket.gethostname()
        self.sessions: Dict[str, Session] = {}
        self._beacon = BeaconBroadcaster(name=self.name, port=port)
        self._server: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._busy = threading.Lock()

    # -- lifecycle ------------------------------------------------------------
    def serve_forever(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("", self.port))
        self._server.listen(4)
        self._beacon.start()
        self.log(f"Agent '{self.name}' listening on port {self.port}")

        try:
            while not self._stop.is_set():
                try:
                    client, address = self._server.accept()
                except OSError:
                    break
                if not self._busy.acquire(blocking=False):
                    self.log(f"Refused {address[0]}: another controller is connected")
                    client.close()
                    continue
                threading.Thread(
                    target=self._serve_client, args=(client, address),
                    name="controller", daemon=True,
                ).start()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop.set()
        self._beacon.stop()
        for session in list(self.sessions.values()):
            self._stop_session(session.session_id, close_app=False)
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass

    # -- per-connection -------------------------------------------------------
    def _serve_client(self, client: socket.socket, address) -> None:
        channel = Channel(client)
        self.log(f"Controller connected from {address[0]}")
        incoming: Optional[_Incoming] = None
        authenticated = False
        try:
            while True:
                mtype, payload, blob = channel.recv()

                if mtype == Msg.HELLO:
                    if not security.check(payload.get("code"), address[0]):
                        self.log(f"Rejected {address[0]}: wrong or missing pairing code")
                        channel.send(Msg.ERROR, {
                            "error": "Pairing code required. Read it from the "
                                     "AppMigrate window on the target laptop.",
                            "fatal": True,
                            "needs_code": True,
                        })
                        return
                    authenticated = True
                    self.log(f"Paired with {address[0]}")
                    channel.send(Msg.HELLO_ACK, {
                        "name": self.name,
                        "version": config.VERSION,
                        "input_mode": config.INPUT_MODE,
                    })
                elif not authenticated:
                    # Nothing else is served before the handshake succeeds.
                    channel.send(Msg.ERROR, {"error": "Not paired.", "fatal": True})
                    return
                elif mtype == Msg.PING:
                    channel.send(Msg.PONG, {"t": payload.get("t")})

                elif mtype == Msg.TRANSFER_BEGIN:
                    incoming = _Incoming(
                        payload["session"], payload.get("meta", {}),
                        int(payload.get("size", 0)))
                    self.log(f"Incoming: {incoming.meta.get('app_name', 'app')} "
                             f"({incoming.total / 1024:.0f} KB)")
                    channel.send(Msg.TRANSFER_ACK, {"session": incoming.session_id,
                                                    "stage": "begin"})
                elif mtype == Msg.TRANSFER_CHUNK:
                    if incoming is not None:
                        incoming.add(blob)
                        channel.send(Msg.TRANSFER_ACK, {
                            "session": incoming.session_id, "stage": "chunk",
                            "received": incoming.received, "total": incoming.total})
                elif mtype == Msg.TRANSFER_END:
                    if incoming is None:
                        channel.send(Msg.ERROR, {"error": "no transfer in progress"})
                        continue
                    self._finish_transfer(channel, incoming, payload.get("sha256", ""))
                    incoming = None

                elif mtype == Msg.INPUT:
                    session = self.sessions.get(payload.get("session", ""))
                    if session is not None and session.injector is not None:
                        session.injector.apply(payload.get("event", {}))

                elif mtype == Msg.STREAM_STOP:
                    session = self.sessions.get(payload.get("session", ""))
                    if session is not None and session.streamer is not None:
                        session.streamer.stop()

                elif mtype == Msg.SESSION_KILL:
                    self._stop_session(payload.get("session", ""), close_app=True)
                    channel.send(Msg.SESSION_GONE, {"session": payload.get("session", "")})

        except ChannelClosed:
            self.log("Controller disconnected")
        except Exception:
            self.log("Connection error:\n" + traceback.format_exc())
        finally:
            for session_id in list(self.sessions):
                session = self.sessions[session_id]
                if session.streamer is not None:
                    session.streamer.stop()
            channel.close()
            self._busy.release()

    # -- restore --------------------------------------------------------------
    def _finish_transfer(self, channel: Channel, incoming: _Incoming, expected: str) -> None:
        blob = incoming.blob()
        actual = bundle.digest(blob)
        if expected and actual != expected:
            channel.send(Msg.RESTORE_RESULT, {
                "session": incoming.session_id, "ok": False,
                "error": "Bundle checksum mismatch; the transfer was corrupted."})
            return

        try:
            session = self._restore(incoming.session_id, blob)
        except Exception as exc:
            self.log(f"Restore failed: {exc}")
            channel.send(Msg.RESTORE_RESULT, {
                "session": incoming.session_id, "ok": False, "error": str(exc)})
            return

        self.sessions[session.session_id] = session
        session.injector = InputInjector(session.hwnd, mode=config.INPUT_MODE)
        session.streamer = WindowStreamer(
            hwnd=session.hwnd, channel=channel, session_id=session.session_id,
            on_window_gone=lambda sid=session.session_id: self._window_gone(channel, sid),
        )
        session.streamer.start()

        self.log(f"Restored {session.app_name} (pid {session.pid}); streaming started")
        channel.send(Msg.RESTORE_RESULT, {
            "session": session.session_id, "ok": True, "pid": session.pid,
            "hwnd": session.hwnd, "app_name": session.app_name,
            "warnings": session.warnings})

    def _restore(self, session_id: str, blob: bytes) -> Session:
        state = bundle.unpack(blob)
        adapter = adapter_by_id(state.adapter_id)
        workdir = config.SESSION_DIR / session_id
        workdir.mkdir(parents=True, exist_ok=True)

        spec = adapter.restore(state, workdir)
        self.log(f"Launching: {' '.join(spec.argv[:3])}...")

        # Snapshot first: many apps surface their window from a process that is
        # not a descendant of the one we start.
        before = win.snapshot_hwnds()
        launched_exe = Path(spec.argv[0]).name
        pid = migrate.launch(spec)

        window = win.find_launched_window(
            pid=pid,
            exe_name=launched_exe,
            before=before,
            timeout=config.RESTORE_WINDOW_TIMEOUT,
        )
        if window is None:
            raise TimeoutError(
                f"{state.app_name} was launched but no window appeared within "
                f"{config.RESTORE_WINDOW_TIMEOUT:.0f} seconds."
            )

        return Session(
            session_id=session_id, app_name=state.app_name, pid=window.pid,
            hwnd=window.hwnd, workdir=workdir, warnings=list(spec.warnings),
        )

    # -- teardown -------------------------------------------------------------
    def _window_gone(self, channel: Channel, session_id: str) -> None:
        self.log(f"Session {session_id}: the application window closed")
        self.sessions.pop(session_id, None)
        try:
            channel.send(Msg.SESSION_GONE, {"session": session_id})
        except ChannelClosed:
            pass

    def _stop_session(self, session_id: str, close_app: bool) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        if session.streamer is not None:
            session.streamer.stop()
        if close_app and win.is_window(session.hwnd):
            win.request_close(session.hwnd)


def run(port: int = config.CONTROL_PORT, name: Optional[str] = None) -> None:
    agent = Agent(port=port, name=name)
    try:
        agent.serve_forever()
    except KeyboardInterrupt:
        agent.shutdown()
