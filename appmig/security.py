"""Pairing codes.

Over a direct cable the link is inherently trusted: nothing else is on it. Over
Tailscale it is not — every device on the tailnet can reach the agent port, and
an agent will launch applications and inject keystrokes on request. That is far
too much authority to hand to anything that can open a socket.

So the agent has a pairing code. The controller must present it in the handshake
before anything else is accepted. The code is generated once, persists, and is
shown in the agent panel so it can be typed into the other laptop.

Loopback is exempt, so a single machine can talk to itself while you are
developing or testing without any of this getting in the way.
"""
from __future__ import annotations

import hmac
import json
import secrets
from pathlib import Path
from typing import Dict, Optional

from . import config

# Base32 minus the characters people misread: I, L, O, U, 0, 1.
_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
_CODE_LENGTH = 8

TOKEN_FILE = config.DATA_DIR / "pairing.token"
KNOWN_PEERS_FILE = config.DATA_DIR / "known_peers.json"

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


# --------------------------------------------------------------- agent side
def generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def local_code() -> str:
    """This machine's pairing code, created on first use and kept thereafter."""
    try:
        existing = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(existing) == _CODE_LENGTH:
            return existing
    except (OSError, ValueError):
        pass

    code = generate_code()
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(code, encoding="utf-8")
    except OSError:
        pass
    return code


def rotate_code() -> str:
    """Issue a new code. Previously paired controllers must be given it again."""
    code = generate_code()
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(code, encoding="utf-8")
    except OSError:
        pass
    return code


def is_loopback(address: str) -> bool:
    return address in _LOOPBACK


def check(presented: Optional[str], peer_address: str) -> bool:
    """Does this controller get to talk to us?"""
    if is_loopback(peer_address):
        return True
    if not presented:
        return False
    return hmac.compare_digest(
        normalise(presented).encode(), local_code().encode()
    )


def normalise(code: str) -> str:
    """Accept what people actually type: spaces, dashes, lower case."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def format_code(code: str) -> str:
    """Display form: ABCD-EFGH."""
    code = normalise(code)
    if len(code) == _CODE_LENGTH:
        return f"{code[:4]}-{code[4:]}"
    return code


# ----------------------------------------------------------- controller side
def _load_known() -> Dict[str, str]:
    try:
        return json.loads(KNOWN_PEERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember_code(host: str, code: str) -> None:
    """Store a working code so this laptop is only paired once."""
    known = _load_known()
    known[host] = normalise(code)
    try:
        KNOWN_PEERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        KNOWN_PEERS_FILE.write_text(json.dumps(known, indent=2), encoding="utf-8")
    except OSError:
        pass


def recall_code(host: str) -> str:
    return _load_known().get(host, "")


def forget_code(host: str) -> None:
    known = _load_known()
    if known.pop(host, None) is not None:
        try:
            KNOWN_PEERS_FILE.write_text(json.dumps(known, indent=2), encoding="utf-8")
        except OSError:
            pass


def needs_code(host: str) -> bool:
    """Whether connecting to this address will require pairing."""
    return not is_loopback(host)
