"""The adapter contract.

Transfer order matters, and it is the whole trick behind this project:

    1. ``prepare()``   nudge the app to save whatever it can while still alive
    2. close the app   WM_CLOSE, so it flushes its own session files on exit
    3. ``capture()``   harvest the files it just wrote
    4. ship the bundle
    5. ``restore()``   lay those files down on the target and hand back a launch spec

Step 2 sitting between prepare and capture is deliberate. A clean shutdown is a
better state serialiser than anything we could reconstruct from the outside.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..discovery.apps import AppInfo

# How faithfully a given adapter expects to reproduce the session.
FIDELITY_HIGH = "high"      # tabs, open documents, cursor, playback position
FIDELITY_PARTIAL = "partial"  # documents survive, undo history and layout do not
FIDELITY_FRESH = "fresh"    # app relaunches clean with the same arguments


@dataclass
class CapturedState:
    adapter_id: str
    app_name: str
    exe_path: str
    exe_name: str
    cmdline: List[str] = field(default_factory=list)
    cwd: str = ""
    fidelity: str = FIDELITY_FRESH
    title: str = ""
    meta: Dict = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    files: Dict[str, bytes] = field(default_factory=dict)

    @property
    def total_bytes(self) -> int:
        return sum(len(content) for content in self.files.values())

    def add_file(self, relative_path: str, content: bytes) -> None:
        self.files[relative_path.replace("\\", "/")] = content

    def add_tree(self, root: Path, prefix: str, max_bytes: int = 64 << 20) -> int:
        """Copy a directory into the bundle, skipping anything oversized.

        Returns the number of bytes actually taken. Session directories are
        normally tiny; the cap is there to stop an adapter accidentally
        swallowing a multi-gigabyte cache.
        """
        if not root.exists():
            return 0
        taken = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > max_bytes or taken + size > max_bytes:
                continue
            try:
                content = path.read_bytes()
            except (OSError, PermissionError):
                continue
            relative = path.relative_to(root).as_posix()
            self.add_file(f"{prefix}/{relative}", content)
            taken += size
        return taken


@dataclass
class LaunchSpec:
    """What the agent should actually run once state is in place."""
    argv: List[str]
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    warnings: List[str] = field(default_factory=list)


class StateAdapter:
    """Base class. Subclasses override what they can meaningfully improve on."""

    id: str = "base"
    display_name: str = "Base"
    fidelity: str = FIDELITY_FRESH
    # What this adapter claims it will carry across, shown in the UI.
    carries: str = "Application relaunches with the same arguments."

    def can_handle(self, app: AppInfo) -> bool:
        raise NotImplementedError

    def prepare(self, app: AppInfo) -> List[str]:
        """Optional pre-close nudge. Returns human-readable notes."""
        return []

    def capture(self, app: AppInfo, state: CapturedState) -> None:
        """Fill ``state`` with whatever the app left behind on disk."""
        return None

    def restore(self, state: CapturedState, workdir: Path) -> LaunchSpec:
        raise NotImplementedError

    # -- helpers shared by subclasses -----------------------------------------
    @staticmethod
    def materialise(state: CapturedState, workdir: Path, prefix: str) -> Path:
        """Write one bundle subtree out to disk and return its root."""
        root = workdir / prefix
        root.mkdir(parents=True, exist_ok=True)
        marker = prefix + "/"
        for relative_path, content in state.files.items():
            if not relative_path.startswith(marker):
                continue
            destination = root / relative_path[len(marker):]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        return root

    @staticmethod
    def copy_into(source_root: Path, destination_root: Path) -> None:
        """Merge a materialised tree into a real config location."""
        import shutil
        for path in source_root.rglob("*"):
            if not path.is_file():
                continue
            destination = destination_root / path.relative_to(source_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(path, destination)
            except (OSError, PermissionError):
                continue

    @staticmethod
    def resolve_executable(state: CapturedState, candidates: List[str]) -> Optional[str]:
        """Find the app on *this* machine; the source path may not exist here."""
        if state.exe_path and os.path.isfile(state.exe_path):
            return state.exe_path
        for candidate in candidates:
            expanded = os.path.expandvars(candidate)
            if os.path.isfile(expanded):
                return expanded
        from shutil import which
        return which(state.exe_name) if state.exe_name else None
