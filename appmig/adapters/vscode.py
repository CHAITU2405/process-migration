"""Visual Studio Code.

VS Code stores per-workspace UI state under ``User/workspaceStorage/<hash>``,
keyed by a hash of the folder URI. Carrying the matching entry across brings
open editors, layout, and search state with it. The folder itself is *not*
carried; if the path does not exist on the target machine the restore still
happens but is flagged as degraded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlparse

from ..discovery.apps import AppInfo
from .base import FIDELITY_PARTIAL, CapturedState, LaunchSpec, StateAdapter

_EXE_CANDIDATES = [
    r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
    r"%PROGRAMFILES%\Microsoft VS Code\Code.exe",
]
_TITLE_SUFFIX = " - Visual Studio Code"


class VSCodeAdapter(StateAdapter):
    id = "vscode"
    display_name = "Visual Studio Code"
    fidelity = FIDELITY_PARTIAL
    carries = "Workspace folder, open editors, and window layout."

    def can_handle(self, app: AppInfo) -> bool:
        return app.exe_name.lower() == "code.exe"

    # -- capture --------------------------------------------------------------
    def capture(self, app: AppInfo, state: CapturedState) -> None:
        folder = self._workspace_folder(app)
        state.meta["folder"] = folder or ""

        if not folder:
            state.notes.append("No workspace folder detected; VS Code opens empty.")
            return

        state.notes.append(f"Workspace: {folder}")
        storage = self._storage_entry(folder)
        if storage is None:
            state.notes.append("No stored workspace state found for this folder.")
            return

        state.meta["storage_hash"] = storage.name
        taken = state.add_tree(storage, "workspaceStorage", max_bytes=48 << 20)
        if taken:
            state.notes.append("Carrying open editors and layout.")

    def _workspace_folder(self, app: AppInfo) -> Optional[str]:
        # A folder passed on the command line is the most reliable signal.
        for argument in app.cmdline[1:]:
            if argument.startswith("-"):
                continue
            if os.path.isdir(argument):
                return os.path.abspath(argument)
        # Otherwise fall back to the trailing segment of the window title.
        title = app.title
        if title.endswith(_TITLE_SUFFIX):
            parts = [p.strip() for p in title[: -len(_TITLE_SUFFIX)].split(" - ")]
            for candidate in reversed(parts):
                if app.cwd and os.path.isdir(os.path.join(app.cwd, candidate)):
                    return os.path.abspath(os.path.join(app.cwd, candidate))
        return app.cwd if app.cwd and os.path.isdir(app.cwd) else None

    @staticmethod
    def _storage_root() -> Path:
        return Path(os.path.expandvars(r"%APPDATA%\Code\User\workspaceStorage"))

    def _storage_entry(self, folder: str) -> Optional[Path]:
        """Find the storage directory whose workspace.json points at this folder."""
        root = self._storage_root()
        if not root.is_dir():
            return None
        target = os.path.normcase(os.path.abspath(folder))
        for entry in root.iterdir():
            meta = entry / "workspace.json"
            if not meta.is_file():
                continue
            try:
                uri = json.loads(meta.read_text(encoding="utf-8")).get("folder", "")
            except (OSError, ValueError):
                continue
            resolved = _uri_to_path(uri)
            if resolved and os.path.normcase(resolved) == target:
                return entry
        return None

    # -- restore --------------------------------------------------------------
    def restore(self, state: CapturedState, workdir: Path) -> LaunchSpec:
        executable = self.resolve_executable(state, _EXE_CANDIDATES)
        if executable is None:
            raise FileNotFoundError("Visual Studio Code is not installed on this machine.")

        warnings: List[str] = []
        folder = state.meta.get("folder") or ""
        storage_hash = state.meta.get("storage_hash")

        if storage_hash:
            destination = self._storage_root() / storage_hash
            source = self.materialise(state, workdir, "workspaceStorage")
            if any(source.iterdir()):
                destination.mkdir(parents=True, exist_ok=True)
                self.copy_into(source, destination)

        argv = [executable]
        if folder:
            if os.path.isdir(folder):
                argv.append(folder)
            else:
                warnings.append(
                    f"The workspace folder {folder} does not exist on this "
                    "machine, so VS Code opens without it. Put the project at "
                    "the same path, or on a shared drive, for a full restore."
                )

        return LaunchSpec(argv=argv, warnings=warnings)


def _uri_to_path(uri: str) -> Optional[str]:
    """Turn ``file:///c%3A/Users/x`` into ``C:\\Users\\x``."""
    if not uri.startswith("file://"):
        return None
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return os.path.abspath(path.replace("/", os.sep))
