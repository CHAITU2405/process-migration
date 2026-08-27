"""Controller-side transfer orchestration.

The ordering here is the safety-critical part of the project:

    prepare -> close -> capture -> write rollback -> ship -> restore -> confirm

The source application must be closed before its state can be captured, because
a clean shutdown is what makes the app flush its session to disk. That means the
app is gone before we know whether the far side succeeded, so every capture is
written to a rollback bundle first. If the restore fails, the session can be
brought straight back up on this machine.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from . import bundle, config
from .adapters.base import CapturedState, LaunchSpec, StateAdapter
from .adapters.registry import adapter_by_id, adapter_for
from .discovery.apps import AppInfo, process_tree_pids
from .winapi import windows as win

CLOSE_TIMEOUT = 12.0
Logger = Callable[[str], None]


class TransferError(Exception):
    """A transfer failed in a way the user needs to see and act on."""


class AppWouldNotClose(TransferError):
    """The app ignored the close request, usually due to a modal save prompt."""


@dataclass
class CaptureResult:
    session_id: str
    state: CapturedState
    blob: bytes
    rollback_path: Path
    adapter: StateAdapter
    warnings: List[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return len(self.blob) / (1024 * 1024)


def capture_and_close(app: AppInfo, log: Logger = lambda _m: None) -> CaptureResult:
    """Close the application and harvest the state it wrote on the way out."""
    adapter = adapter_for(app)
    session_id = uuid.uuid4().hex[:12]
    log(f"Adapter: {adapter.display_name} ({adapter.fidelity} fidelity)")

    state = CapturedState(
        adapter_id=adapter.id,
        app_name=app.display_name,
        exe_path=app.exe_path,
        exe_name=app.exe_name,
        cmdline=list(app.cmdline),
        cwd=app.cwd,
        fidelity=adapter.fidelity,
        title=app.title,
    )

    log("Asking the application to save its state...")
    try:
        state.notes.extend(adapter.prepare(app))
    except Exception as exc:
        log(f"Pre-save step reported: {exc}")

    pids = process_tree_pids(app.pid)
    log("Closing the application on this laptop...")
    win.request_close(app.hwnd)

    if not win.wait_for_exit(app.pid, CLOSE_TIMEOUT):
        raise AppWouldNotClose(
            f"{app.display_name} did not close within {CLOSE_TIMEOUT:.0f} seconds. "
            "It is probably showing an unsaved-changes prompt. Deal with that "
            "prompt and try again -- nothing has been transferred, and the app "
            "is untouched."
        )

    # Session files land a moment after the process exits.
    time.sleep(0.6)

    log("Capturing session state...")
    try:
        adapter.capture(app, state)
    except Exception as exc:
        raise TransferError(f"State capture failed: {exc}") from exc

    blob = bundle.pack(state)
    rollback_path = bundle.write_rollback(blob, session_id, config.ROLLBACK_DIR)
    log(f"Captured {len(blob) / 1024:.0f} KB across {len(state.files)} file(s).")

    return CaptureResult(
        session_id=session_id,
        state=state,
        blob=blob,
        rollback_path=rollback_path,
        adapter=adapter,
        warnings=list(state.notes),
    )


def restore_locally(blob: bytes, log: Logger = lambda _m: None) -> LaunchSpec:
    """Bring a captured session back up on this machine after a failed transfer."""
    state = bundle.unpack(blob)
    adapter = adapter_by_id(state.adapter_id)
    workdir = config.SESSION_DIR / f"rollback-{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    spec = adapter.restore(state, workdir)
    log(f"Relaunching {state.app_name} here.")
    launch(spec)
    return spec


def launch(spec: LaunchSpec) -> int:
    """Start the restored application, detached from this process."""
    import subprocess

    creationflags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        spec.argv,
        cwd=spec.cwd,
        env=spec.env,
        creationflags=creationflags,
        close_fds=True,
    )
    return process.pid


def discard_rollback(path: Optional[Path]) -> None:
    """Called once the far side confirms a live window."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
