"""Length-prefixed framing over a plain TCP socket.

Frame layout::

    [1B type][4B json length][4B blob length][json][blob]

Sends are mutex-guarded so a streaming thread and a control thread can share one
socket. Receives happen on a single dedicated thread, so they need no lock.
"""
from __future__ import annotations

import json
import socket
import struct
import threading
from typing import Tuple

_HEADER = struct.Struct("!BII")
MAX_JSON = 8 << 20
MAX_BLOB = 256 << 20


class ChannelClosed(Exception):
    """The peer went away, or we shut the socket down deliberately."""


class Channel:
    def __init__(self, sock: socket.socket):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._reader = sock.makefile("rb")
        self._send_lock = threading.Lock()
        self._closed = False

    @property
    def peer(self) -> str:
        try:
            host, port = self._sock.getpeername()[:2]
            return f"{host}:{port}"
        except OSError:
            return "<disconnected>"

    def send(self, mtype: int, payload: dict | None = None, blob: bytes = b"") -> None:
        body = json.dumps(payload or {}, separators=(",", ":")).encode("utf-8")
        header = _HEADER.pack(int(mtype), len(body), len(blob))
        with self._send_lock:
            if self._closed:
                raise ChannelClosed("channel already closed")
            try:
                self._sock.sendall(header + body + blob)
            except OSError as exc:
                self._closed = True
                raise ChannelClosed(str(exc)) from exc

    def recv(self) -> Tuple[int, dict, bytes]:
        header = self._read_exact(_HEADER.size)
        mtype, json_len, blob_len = _HEADER.unpack(header)
        if json_len > MAX_JSON or blob_len > MAX_BLOB:
            raise ChannelClosed("frame exceeds sanity limits")
        body = self._read_exact(json_len) if json_len else b"{}"
        blob = self._read_exact(blob_len) if blob_len else b""
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise ChannelClosed(f"malformed json frame: {exc}") from exc
        return mtype, payload, blob

    def _read_exact(self, count: int) -> bytes:
        if count == 0:
            return b""
        data = self._reader.read(count)
        if data is None or len(data) < count:
            self._closed = True
            raise ChannelClosed("peer closed the connection")
        return data

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        for closeable in (self._reader, self._sock):
            try:
                closeable.close()
            except OSError:
                pass


def connect(host: str, port: int, timeout: float) -> Channel:
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(None)
    return Channel(sock)
