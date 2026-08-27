"""Central configuration. Ports, timeouts, and on-disk locations."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "AppMigrate"
VERSION = "0.1.0"

# --- network -----------------------------------------------------------------
BEACON_PORT = 47810      # UDP: agents announce themselves here
CONTROL_PORT = 47811     # TCP: single full-duplex control + stream channel

BEACON_INTERVAL = 2.0    # seconds between agent beacons
PEER_TIMEOUT = 6.0       # drop a peer we have not heard from in this long
HEARTBEAT_INTERVAL = 2.0
HEARTBEAT_TIMEOUT = 8.0
CONNECT_TIMEOUT = 5.0

# --- streaming ---------------------------------------------------------------
STREAM_FPS = 20
STREAM_QUALITY = 72          # JPEG quality
STREAM_MAX_WIDTH = 1920      # downscale wider windows before encoding
IDLE_FRAME_INTERVAL = 1.0    # resend an unchanged frame at least this often

# --- transfer ----------------------------------------------------------------
CHUNK_SIZE = 1 << 20         # 1 MiB bundle chunks
RESTORE_WINDOW_TIMEOUT = 30.0  # how long to wait for the restored app's window

# --- paths -------------------------------------------------------------------
def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))


DATA_DIR = _local_appdata() / APP_NAME
PROFILE_DIR = DATA_DIR / "profiles"      # sandboxed browser profiles
SESSION_DIR = DATA_DIR / "sessions"      # unpacked incoming bundles
ROLLBACK_DIR = DATA_DIR / "rollback"     # bundles kept until restore is confirmed

for _p in (DATA_DIR, PROFILE_DIR, SESSION_DIR, ROLLBACK_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# --- behaviour flags ---------------------------------------------------------
# Restore browsers into a dedicated sandbox profile rather than writing over the
# user's real one. Safe by default; see README for the trade-off.
BROWSER_SANDBOX_PROFILE = True

# Move the restored app off the target laptop's visible desktop. It keeps
# running and streaming, but nobody sitting at that machine sees or touches it.
HIDE_ON_TARGET = True

# "post" injects window messages (does not steal the agent's real cursor).
# "sendinput" drives the agent's actual input stack -- more compatible, more invasive.
INPUT_MODE = "post"
