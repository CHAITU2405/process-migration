"""Chromium-family adapter: Chrome, Edge, and Brave.

Chromium writes its session to ``<profile>/Sessions`` in the SNSS format on
clean exit. This adapter reads those records (see :mod:`.snss`) to work out
which tabs were open and what page each was showing, then reopens exactly those
URLs on the target. Reopening URLs is far more predictable than asking Chromium
to adopt a transplanted session directory; the cost is scroll position and
per-tab back/forward history.

Note that the live session file is locked while the browser is running, which is
another reason capture happens only after the app has closed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .. import config
from ..discovery.apps import AppInfo
from . import snss
from .base import FIDELITY_HIGH, CapturedState, LaunchSpec, StateAdapter

_URL_PATTERN = re.compile(rb"https?://[\x21-\x7E]{4,2000}")
_TRAILING_JUNK = '\\"\'<>(),;'

_DEFAULT_PROFILE_ROOTS = {
    "chrome.exe": r"%LOCALAPPDATA%\Google\Chrome\User Data",
    "msedge.exe": r"%LOCALAPPDATA%\Microsoft\Edge\User Data",
    "brave.exe": r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data",
}

_EXE_CANDIDATES = {
    "chrome.exe": [
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ],
    "msedge.exe": [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave.exe": [
        r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%PROGRAMFILES(X86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
}

MAX_TABS = 40


class ChromiumAdapter(StateAdapter):
    id = "chromium"
    display_name = "Chromium browser"
    fidelity = FIDELITY_HIGH
    carries = "Open tabs and their URLs, restored into an isolated profile."

    def can_handle(self, app: AppInfo) -> bool:
        return app.exe_name.lower() in _DEFAULT_PROFILE_ROOTS

    # -- capture --------------------------------------------------------------
    def capture(self, app: AppInfo, state: CapturedState) -> None:
        profile_root = self._profile_root(app)
        profile_name = self._profile_name(app)
        state.meta["profile_name"] = profile_name

        if profile_root is None or not profile_root.exists():
            state.notes.append("Browser profile directory could not be located.")
            return

        sessions_dir = profile_root / profile_name / "Sessions"
        taken = self._collect_sessions(sessions_dir, state)
        if taken == 0:
            state.notes.append(
                "No readable session file was found. If the browser was still "
                "running, its live session file stays locked."
            )

        urls = self._scrape_urls(state)
        state.meta["urls"] = urls
        if urls:
            state.notes.append(f"Recovered {len(urls)} open tab(s).")
        else:
            state.notes.append(
                "No tabs were recovered. The browser may not have written its "
                "session file before exiting."
            )
        state.meta["session_bytes"] = taken

    @staticmethod
    def _collect_sessions(sessions_dir: Path, state: CapturedState) -> int:
        """Carry the newest few Session_* files and nothing else.

        Tabs_* files describe recently *closed* tabs and are often far larger
        than the live session, so they are skipped entirely.
        """
        if not sessions_dir.is_dir():
            return 0
        try:
            candidates = sorted(
                (p for p in sessions_dir.glob("Session_*") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:3]
        except OSError:
            return 0

        taken = 0
        for path in candidates:
            try:
                content = path.read_bytes()
            except (OSError, PermissionError):
                continue  # the live file is locked while the browser runs
            state.add_file(f"sessions/{path.name}", content)
            taken += len(content)
        return taken

    def _scrape_urls(self, state: CapturedState) -> List[str]:
        """Open tabs from the newest session file, newest file first."""
        session_files = sorted(
            (name for name in state.files if snss.looks_like_session_file(name)),
            reverse=True,
        )
        for name in session_files:
            urls = snss.open_tab_urls(state.files[name])
            if urls:
                return urls[:MAX_TABS]

        # The record parse found nothing usable. Fall back to pulling anything
        # URL-shaped out of the bytes; noisier, but better than losing the lot.
        return self._salvage_urls(session_files, state)

    def _salvage_urls(self, session_files: List[str], state: CapturedState) -> List[str]:
        seen: set = set()
        urls: List[str] = []
        for name in session_files:
            for match in _URL_PATTERN.finditer(state.files[name]):
                url = self._clean(match.group().decode("utf-8", "ignore"))
                if url is None or url in seen:
                    continue
                seen.add(url)
                urls.append(url)
                if len(urls) >= MAX_TABS:
                    return urls
        return urls

    @staticmethod
    def _clean(url: str) -> Optional[str]:
        url = url.rstrip(_TRAILING_JUNK)
        # SNSS packs records back to back, so a match can run into binary noise.
        for terminator in ("\x00", "\\x", "%00"):
            if terminator in url:
                url = url.split(terminator)[0]
        if len(url) < 12 or len(url) > 2000:
            return None
        lowered = url.lower()
        if any(lowered.startswith(prefix) for prefix in
               ("http://localhost/chrome", "https://www.google.com/complete")):
            return None
        if "/gen_204" in lowered or "clients1.google" in lowered:
            return None
        return url

    def _profile_root(self, app: AppInfo) -> Optional[Path]:
        for argument in app.cmdline:
            if argument.startswith("--user-data-dir="):
                return Path(argument.split("=", 1)[1].strip('"'))
        default = _DEFAULT_PROFILE_ROOTS.get(app.exe_name.lower())
        return Path(os.path.expandvars(default)) if default else None

    @staticmethod
    def _profile_name(app: AppInfo) -> str:
        for argument in app.cmdline:
            if argument.startswith("--profile-directory="):
                return argument.split("=", 1)[1].strip('"')
        return "Default"

    # -- restore --------------------------------------------------------------
    def restore(self, state: CapturedState, workdir: Path) -> LaunchSpec:
        executable = self.resolve_executable(
            state, _EXE_CANDIDATES.get(state.exe_name.lower(), []))
        if executable is None:
            raise FileNotFoundError(
                f"{state.app_name} is not installed on this machine.")

        warnings: List[str] = []
        urls = state.meta.get("urls", [])

        if config.BROWSER_SANDBOX_PROFILE:
            profile_dir = config.PROFILE_DIR / workdir.name
            profile_dir.mkdir(parents=True, exist_ok=True)
            argv = [
                executable,
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            warnings.append(
                "Restored into an isolated profile, so saved logins and "
                "extensions from the source machine are not carried across."
            )
        else:
            # Transplant the session files into the real profile and let the
            # browser restore them itself. Requires the browser to be closed here.
            profile_root = Path(os.path.expandvars(
                _DEFAULT_PROFILE_ROOTS[state.exe_name.lower()]))
            target = profile_root / state.meta.get("profile_name", "Default") / "Sessions"
            source = self.materialise(state, workdir, "sessions")
            self.copy_into(source, target)
            argv = [executable, "--restore-last-session"]
            warnings.append(
                "Wrote session files into the real browser profile. Close any "
                "running browser window on this machine first."
            )

        if urls:
            argv.extend(urls)
        elif config.BROWSER_SANDBOX_PROFILE:
            warnings.append("No tabs were recovered; the browser opens blank.")

        return LaunchSpec(argv=argv, warnings=warnings)
