"""Find target laptops over Tailscale.

UDP broadcast discovery stops at the local link, so it never finds a laptop
across a tailnet. Tailscale already knows every machine on your network, so we
ask its CLI rather than inventing a second discovery mechanism.

Connection quality matters here in a way it does not over a cable. A peer with a
populated ``CurAddr`` has a direct path and can carry the video stream. A peer
reachable only through a DERP relay is routed through Tailscale's servers, which
is fine for the state transfer but usually too slow and too far for smooth
remote UI. The UI shows which one you have.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# Tailscale hands out addresses from the carrier-grade NAT range 100.64.0.0/10.
_TAILSCALE_NET = (100, 64, 0, 0)
_TAILSCALE_MASK_BITS = 10

_CLI_CANDIDATES = [
    r"%PROGRAMFILES%\Tailscale\tailscale.exe",
    r"%PROGRAMFILES(X86)%\Tailscale\tailscale.exe",
    r"%LOCALAPPDATA%\Tailscale\tailscale.exe",
]

LINK_DIRECT = "direct"
LINK_RELAY = "relay"
LINK_OFFLINE = "offline"


@dataclass
class TailscalePeer:
    host: str            # short display name
    dns_name: str        # full MagicDNS name
    ip: str              # 100.x.y.z
    os_name: str
    online: bool
    link: str            # direct | relay | offline
    relay_region: str = ""

    @property
    def supported(self) -> bool:
        """Only Windows machines can run the agent."""
        return self.os_name.lower() == "windows"

    @property
    def quality_note(self) -> str:
        if not self.online:
            return "Offline"
        if not self.supported:
            return f"{self.os_name} cannot run the agent"
        if self.link == LINK_DIRECT:
            return "Direct connection"
        return f"Relayed via {self.relay_region or 'DERP'} — transfer works, video may lag"


@dataclass
class TailscaleStatus:
    running: bool
    self_host: str = ""
    self_ip: str = ""
    peers: List[TailscalePeer] = None
    error: str = ""

    def __post_init__(self):
        if self.peers is None:
            self.peers = []


def find_cli() -> Optional[str]:
    for candidate in _CLI_CANDIDATES:
        expanded = os.path.expandvars(candidate)
        if os.path.isfile(expanded):
            return expanded
    return shutil.which("tailscale")


def is_tailscale_ip(address: str) -> bool:
    try:
        octets = [int(part) for part in address.split(".")]
    except (ValueError, AttributeError):
        return False
    if len(octets) != 4:
        return False
    # 100.64.0.0/10 -> first octet 100, second octet 64..127
    return octets[0] == 100 and 64 <= octets[1] <= 127


def status(timeout: float = 6.0) -> TailscaleStatus:
    """Ask the Tailscale CLI who is on this tailnet."""
    cli = find_cli()
    if cli is None:
        return TailscaleStatus(running=False, error="Tailscale is not installed.")

    try:
        result = subprocess.run(
            [cli, "status", "--json"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return TailscaleStatus(running=False, error=f"Could not run Tailscale: {exc}")

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        return TailscaleStatus(running=False, error=message or "Tailscale reported an error.")

    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        return TailscaleStatus(running=False, error=f"Unreadable Tailscale output: {exc}")

    backend = data.get("BackendState", "")
    if backend != "Running":
        return TailscaleStatus(
            running=False,
            error=f"Tailscale is installed but not connected (state: {backend or 'unknown'}).",
        )

    myself = data.get("Self") or {}
    peers = []
    for entry in (data.get("Peer") or {}).values():
        addresses = entry.get("TailscaleIPs") or []
        ipv4 = next((a for a in addresses if ":" not in a), "")
        if not ipv4:
            continue
        online = bool(entry.get("Online"))
        if not online:
            link = LINK_OFFLINE
        elif entry.get("CurAddr"):
            link = LINK_DIRECT
        else:
            link = LINK_RELAY
        peers.append(TailscalePeer(
            host=entry.get("HostName", ipv4),
            dns_name=(entry.get("DNSName") or "").rstrip("."),
            ip=ipv4,
            os_name=entry.get("OS", "") or "unknown",
            online=online,
            link=link,
            relay_region=entry.get("Relay", "") or "",
        ))

    peers.sort(key=lambda p: (not p.online, not p.supported, p.host.lower()))

    self_addresses = myself.get("TailscaleIPs") or []
    return TailscaleStatus(
        running=True,
        self_host=myself.get("HostName", ""),
        self_ip=next((a for a in self_addresses if ":" not in a), ""),
        peers=peers,
    )


def probe_agent(host: str, port: int, timeout: float = 2.5) -> bool:
    """Is something listening on the agent port over there?"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def self_addresses() -> Tuple[str, str]:
    """(hostname, tailscale ip) for this machine, empty strings if unavailable."""
    state = status()
    return (state.self_host, state.self_ip) if state.running else ("", "")
