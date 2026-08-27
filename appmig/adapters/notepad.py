"""Windows 11 Notepad.

Notepad keeps unsaved tab contents in a ``TabState`` directory inside its
packaged app data. Carrying that directory across moves the actual unsaved text,
which makes it the most convincing demonstration of the whole idea: type
something, never save it, transfer, and the words are still there.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import List, Optional

from ..discovery.apps import AppInfo
from .base import FIDELITY_HIGH, CapturedState, LaunchSpec, StateAdapter

_PACKAGE_GLOB = r"%LOCALAPPDATA%\Packages\Microsoft.WindowsNotepad_*\LocalState"


class NotepadAdapter(StateAdapter):
    id = "notepad"
    display_name = "Windows Notepad"
    fidelity = FIDELITY_HIGH
    carries = "Open tabs including unsaved text, and the caret position."

    def can_handle(self, app: AppInfo) -> bool:
        return app.exe_name.lower() == "notepad.exe" and _local_state() is not None

    def capture(self, app: AppInfo, state: CapturedState) -> None:
        local_state = _local_state()
        if local_state is None:
            state.notes.append("This build of Notepad does not keep tab state.")
            return

        tab_state = local_state / "TabState"
        taken = state.add_tree(tab_state, "tabstate", max_bytes=64 << 20)
        if taken:
            tab_count = len({
                name.split("/")[1].split(".")[0]
                for name in state.files if name.startswith("tabstate/")
            })
            state.notes.append(f"Carrying {tab_count} tab(s), unsaved text included.")
        else:
            state.notes.append("Notepad had no saved tab state to carry.")

    def restore(self, state: CapturedState, workdir: Path) -> LaunchSpec:
        warnings: List[str] = []
        local_state = _local_state()
        if local_state is None:
            raise FileNotFoundError("Windows Notepad app data was not found here.")

        target = local_state / "TabState"
        if _notepad_running():
            warnings.append(
                "Notepad was already running here and was closed so the "
                "transferred tabs could be laid down."
            )
            _close_notepad()

        source = self.materialise(state, workdir, "tabstate")
        if any(source.iterdir()):
            target.mkdir(parents=True, exist_ok=True)
            self.copy_into(source, target)
        else:
            warnings.append("No tab state arrived; Notepad opens empty.")

        executable = self.resolve_executable(
            state, [r"%WINDIR%\System32\notepad.exe"])
        if executable is None:
            executable = "notepad.exe"
        return LaunchSpec(argv=[executable], warnings=warnings)


def _local_state() -> Optional[Path]:
    matches = glob.glob(os.path.expandvars(_PACKAGE_GLOB))
    return Path(matches[0]) if matches else None


def _notepad_running() -> bool:
    import psutil
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower() == "notepad.exe":
            return True
    return False


def _close_notepad() -> None:
    import time

    import psutil

    from ..winapi import windows as win

    for window in win.enumerate_windows():
        try:
            if psutil.Process(window.pid).name().lower() == "notepad.exe":
                win.request_close(window.hwnd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    time.sleep(1.5)
