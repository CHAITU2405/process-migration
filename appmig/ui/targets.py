"""One list of target laptops, however they were found.

Three sources feed it:

``local``      UDP beacons on the local link -- a cable or the same Wi-Fi
``tailscale``  whatever the Tailscale CLI reports on this tailnet
``manual``     an address typed in by hand

Tailscale peers get their agent port probed in the background, because being on
the tailnet says nothing about whether AppMigrate is running over there. Local
peers need no probe: they only appear because their agent beaconed.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from .. import config
from ..discovery import tailscale as ts
from ..discovery.peers import Peer, PeerWatcher

SOURCE_LOCAL = "local"
SOURCE_TAILSCALE = "tailscale"
SOURCE_MANUAL = "manual"

TAILSCALE_POLL_SECONDS = 15.0
PROBE_INTERVAL_SECONDS = 20.0


@dataclass
class Target:
    key: str
    name: str
    host: str
    port: int
    source: str
    online: bool = True
    link: str = ""             # tailscale only: direct | relay | offline
    supported: bool = True     # can this machine run the agent at all
    agent_ready: Optional[bool] = None   # None while unprobed
    note: str = ""

    @property
    def connectable(self) -> bool:
        return self.online and self.supported and self.agent_ready is not False

    @property
    def status_text(self) -> str:
        if not self.supported:
            return self.note or "Cannot run the agent"
        if not self.online:
            return "Offline"
        if self.agent_ready is False:
            return "AppMigrate is not running there"
        if self.agent_ready is None and self.source == SOURCE_TAILSCALE:
            return "Checking..."
        return self.note or "Ready"


class TargetRegistry(QObject):
    """Merges every discovery source into one list the UI can render."""

    targetsChanged = Signal(list)
    tailscaleState = Signal(bool, str)   # running, message

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._local: Dict[str, Target] = {}
        self._tailscale: Dict[str, Target] = {}
        self._manual: Dict[str, Target] = {}
        self._probed_at: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self._watcher = PeerWatcher(on_change=self._on_local_peers)

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        self._watcher.start()
        threading.Thread(target=self._tailscale_loop,
                         name="tailscale-poll", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._watcher.stop()

    # -- sources --------------------------------------------------------------
    def _on_local_peers(self, peers: List[Peer]) -> None:
        found = {}
        for peer in peers:
            if peer.manual:
                continue
            found[peer.key] = Target(
                key=peer.key, name=peer.name, host=peer.host, port=peer.port,
                source=SOURCE_LOCAL, online=True, agent_ready=True,
                note="Found on the local link",
            )
        with self._lock:
            self._local = found
        self._emit()

    def _tailscale_loop(self) -> None:
        while not self._stop.is_set():
            self._refresh_tailscale()
            self._stop.wait(TAILSCALE_POLL_SECONDS)

    def refresh_tailscale_now(self) -> None:
        threading.Thread(target=self._refresh_tailscale,
                         name="tailscale-refresh", daemon=True).start()

    def _refresh_tailscale(self) -> None:
        state = ts.status()
        self.tailscaleState.emit(state.running, state.error)
        if not state.running:
            with self._lock:
                self._tailscale = {}
            self._emit()
            return

        found: Dict[str, Target] = {}
        for peer in state.peers:
            key = f"{peer.ip}:{config.CONTROL_PORT}"
            previous = self._tailscale.get(key)
            found[key] = Target(
                key=key, name=peer.host, host=peer.ip, port=config.CONTROL_PORT,
                source=SOURCE_TAILSCALE, online=peer.online, link=peer.link,
                supported=peer.supported,
                agent_ready=previous.agent_ready if previous else None,
                note=peer.quality_note,
            )
        with self._lock:
            self._tailscale = found
        self._emit()

        # Probe only what could plausibly answer.
        for target in found.values():
            if target.online and target.supported:
                self._maybe_probe(target)

    def _maybe_probe(self, target: Target) -> None:
        last = self._probed_at.get(target.key, 0.0)
        if time.monotonic() - last < PROBE_INTERVAL_SECONDS:
            return
        self._probed_at[target.key] = time.monotonic()
        threading.Thread(target=self._probe, args=(target.key, target.host, target.port),
                         name=f"probe-{target.host}", daemon=True).start()

    def _probe(self, key: str, host: str, port: int) -> None:
        reachable = ts.probe_agent(host, port)
        with self._lock:
            target = self._tailscale.get(key)
            if target is None:
                return
            target.agent_ready = reachable
        self._emit()

    # -- manual ---------------------------------------------------------------
    def add_manual(self, host: str, port: int = config.CONTROL_PORT,
                   name: str = "") -> Target:
        key = f"{host}:{port}"
        source_name = name or (f"{host} (Tailscale)" if ts.is_tailscale_ip(host) else host)
        target = Target(
            key=key, name=source_name, host=host, port=port,
            source=SOURCE_MANUAL, online=True, agent_ready=None,
            note="Added by address",
        )
        with self._lock:
            self._manual[key] = target
        self._emit()
        threading.Thread(target=self._probe_manual, args=(key, host, port),
                         name="probe-manual", daemon=True).start()
        return target

    def _probe_manual(self, key: str, host: str, port: int) -> None:
        reachable = ts.probe_agent(host, port)
        with self._lock:
            target = self._manual.get(key)
            if target is not None:
                target.agent_ready = reachable
        self._emit()

    def remove_manual(self, key: str) -> None:
        with self._lock:
            self._manual.pop(key, None)
        self._emit()

    # -- output ---------------------------------------------------------------
    def targets(self) -> List[Target]:
        with self._lock:
            merged: Dict[str, Target] = {}
            # Local beacons win over a Tailscale entry for the same machine:
            # a direct link is always the better path.
            for source in (self._tailscale, self._manual, self._local):
                merged.update(source)
            values = list(merged.values())

        order = {SOURCE_LOCAL: 0, SOURCE_MANUAL: 1, SOURCE_TAILSCALE: 2}
        values.sort(key=lambda t: (
            not t.connectable, order.get(t.source, 9), t.name.lower()))
        return values

    def _emit(self) -> None:
        self.targetsChanged.emit(self.targets())
