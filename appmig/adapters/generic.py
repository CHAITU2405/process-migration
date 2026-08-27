"""Fallback adapter: relaunch the same executable with the same arguments.

Every application matches this one, which is what keeps the app list fully
actionable. Nothing is greyed out; some entries simply arrive clean.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from ..discovery.apps import AppInfo
from .base import FIDELITY_FRESH, CapturedState, LaunchSpec, StateAdapter


class GenericAdapter(StateAdapter):
    id = "generic"
    display_name = "Generic relaunch"
    fidelity = FIDELITY_FRESH
    carries = "Executable path, command line, and working directory."

    def can_handle(self, app: AppInfo) -> bool:
        return bool(app.exe_path or app.exe_name)

    def capture(self, app: AppInfo, state: CapturedState) -> None:
        state.notes.append(
            "No session format is known for this application, so it will start "
            "fresh on the target machine."
        )

    def restore(self, state: CapturedState, workdir: Path) -> LaunchSpec:
        argv = list(state.cmdline) if state.cmdline else []
        warnings: List[str] = []

        executable = self.resolve_executable(state, [])
        if executable is None:
            raise FileNotFoundError(
                f"{state.exe_name or 'The application'} was not found on this machine."
            )

        if argv:
            argv[0] = executable
        else:
            argv = [executable]

        cwd = state.cwd if state.cwd and os.path.isdir(state.cwd) else None
        if state.cwd and cwd is None:
            warnings.append(f"Working directory {state.cwd} does not exist here.")

        # Arguments that name files are only meaningful if those files exist.
        for argument in argv[1:]:
            if os.path.sep in argument and not argument.startswith("-"):
                if not os.path.exists(argument):
                    warnings.append(f"Path not found on this machine: {argument}")

        return LaunchSpec(argv=argv, cwd=cwd, warnings=warnings)
