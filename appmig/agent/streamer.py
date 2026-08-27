"""Capture the restored window on the agent and stream it to the controller.

Frames are JPEG over the existing control channel. That is deliberately modest:
it needs no external binaries and runs anywhere Python does. The encode step is
isolated behind ``_encode`` so a hardware H.264 path can replace it later
without touching the transport or the viewer.

Unchanged frames are suppressed, which matters more than raw frame rate for the
usual case of a mostly static application window.
"""
from __future__ import annotations

import hashlib
import io
import threading
import time
from typing import Callable, Optional

from .. import config
from ..protocol.channel import Channel, ChannelClosed
from ..protocol.messages import Msg
from ..winapi import windows as win


class WindowStreamer(threading.Thread):
    def __init__(
        self,
        hwnd: int,
        channel: Channel,
        session_id: str,
        on_window_gone: Optional[Callable[[], None]] = None,
        fps: int = config.STREAM_FPS,
        quality: int = config.STREAM_QUALITY,
    ):
        super().__init__(name=f"stream-{session_id}", daemon=True)
        self.hwnd = hwnd
        self.channel = channel
        self.session_id = session_id
        self.on_window_gone = on_window_gone
        self.interval = 1.0 / max(1, fps)
        self.quality = quality
        self._stop = threading.Event()
        self._last_hash = b""
        self._last_sent = 0.0
        self._sequence = 0

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        misses = 0
        while not self._stop.is_set():
            started = time.monotonic()

            if not win.is_window(self.hwnd):
                misses += 1
                # A restored app may briefly recreate its top-level window.
                if misses > 6:
                    self._notify_gone()
                    return
                self._stop.wait(0.5)
                continue
            misses = 0

            try:
                self._tick()
            except ChannelClosed:
                return
            except Exception:
                # A single bad capture must never kill the stream.
                pass

            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, self.interval - elapsed))

    # -- internals ------------------------------------------------------------
    def _tick(self) -> None:
        image = win.capture_window(self.hwnd)
        if image is None:
            return

        source_width, source_height = image.size
        if source_width > config.STREAM_MAX_WIDTH:
            scale = config.STREAM_MAX_WIDTH / source_width
            image = image.resize(
                (config.STREAM_MAX_WIDTH, max(1, int(source_height * scale)))
            )

        payload = self._encode(image)
        fingerprint = hashlib.blake2b(payload, digest_size=16).digest()
        now = time.monotonic()

        unchanged = fingerprint == self._last_hash
        if unchanged and (now - self._last_sent) < config.IDLE_FRAME_INTERVAL:
            return

        self._last_hash = fingerprint
        self._last_sent = now
        self._sequence += 1

        self.channel.send(
            Msg.FRAME,
            {
                "session": self.session_id,
                "seq": self._sequence,
                "w": image.size[0],
                "h": image.size[1],
                "sw": source_width,
                "sh": source_height,
            },
            payload,
        )

    def _encode(self, image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=self.quality,
                   optimize=False, subsampling=1)
        return buffer.getvalue()

    def _notify_gone(self) -> None:
        if self.on_window_gone is not None:
            try:
                self.on_window_gone()
            except Exception:
                pass
