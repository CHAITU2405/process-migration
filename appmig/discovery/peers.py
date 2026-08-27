"""UDP presence, so the controller can tell whether a target laptop is reachable.

The agent beacons and the controller listens. Manual IP entry stays available
for links where broadcast traffic is filtered.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .. import config


@dataclass
class Peer:
    name: str
    host: str
    port: int
    last_seen: float
    version: str = ""
    manual: bool = False

    @property
    def stale(self) -> bool:
        return not self.manual and (time.time() - self.last_seen) > config.PEER_TIMEOUT

    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}"


class BeaconBroadcaster:
    """Runs on the agent, announcing that it is accepting transfers."""

    def __init__(self, name: Optional[str] = None, port: int = config.CONTROL_PORT):
        self.name = name or socket.gethostname()
        self.port = port
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="beacon", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        payload = json.dumps({
            "role": "agent",
            "name": self.name,
            "port": self.port,
            "version": config.VERSION,
        }).encode()
        while not self._stop.is_set():
            for address in broadcast_addresses():
                try:
                    sock.sendto(payload, (address, config.BEACON_PORT))
                except OSError:
                    continue
            self._stop.wait(config.BEACON_INTERVAL)
        sock.close()


class PeerWatcher:
    """Runs on the controller, maintaining the live set of reachable agents."""

    def __init__(self, on_change: Optional[Callable[[List[Peer]], None]] = None):
        self.on_change = on_change
        self._peers: Dict[str, Peer] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []

    def start(self) -> None:
        for target, name in ((self._listen, "peer-listen"), (self._sweep, "peer-sweep")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()

    def peers(self) -> List[Peer]:
        with self._lock:
            return sorted(self._peers.values(), key=lambda p: (not p.manual, p.name.lower()))

    def add_manual(self, host: str, port: int = config.CONTROL_PORT, name: str = "") -> Peer:
        peer = Peer(name=name or host, host=host, port=port,
                    last_seen=time.time(), manual=True)
        with self._lock:
            self._peers[peer.key] = peer
        self._notify()
        return peer

    def remove(self, host: str, port: int) -> None:
        with self._lock:
            self._peers.pop(f"{host}:{port}", None)
        self._notify()

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", config.BEACON_PORT))
        except OSError:
            return
        sock.settimeout(1.0)
        while not self._stop.is_set():
            try:
                data, address = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                message = json.loads(data.decode())
            except ValueError:
                continue
            if message.get("role") != "agent":
                continue

            host = address[0]
            port = int(message.get("port", config.CONTROL_PORT))
            key = f"{host}:{port}"
            is_new = False
            with self._lock:
                existing = self._peers.get(key)
                if existing is not None and existing.manual:
                    existing.last_seen = time.time()
                else:
                    is_new = existing is None
                    self._peers[key] = Peer(
                        name=message.get("name", host),
                        host=host,
                        port=port,
                        last_seen=time.time(),
                        version=message.get("version", ""),
                    )
            if is_new:
                self._notify()
        sock.close()

    def _sweep(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(config.PEER_TIMEOUT / 2)
            with self._lock:
                dead = [key for key, peer in self._peers.items() if peer.stale]
                for key in dead:
                    del self._peers[key]
            if dead:
                self._notify()

    def _notify(self) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change(self.peers())
        except Exception:
            pass


def broadcast_addresses() -> List[str]:
    """Global broadcast plus a directed broadcast per interface.

    Thunderbolt and USB4 links come up as their own subnet, and some drivers
    drop 255.255.255.255 while still passing the directed form.
    """
    addresses = {"255.255.255.255"}
    try:
        import psutil
        for entries in psutil.net_if_addrs().values():
            for addr in entries:
                if addr.family == socket.AF_INET and addr.broadcast:
                    addresses.add(addr.broadcast)
    except Exception:
        pass
    return list(addresses)


def local_addresses() -> List[str]:
    """IPv4 addresses this machine is reachable on, for display in the agent."""
    found = []
    try:
        import psutil
        for name, entries in psutil.net_if_addrs().items():
            for addr in entries:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    found.append((name, addr.address))
    except Exception:
        pass
    return [f"{address}  ({name})" for name, address in found]
