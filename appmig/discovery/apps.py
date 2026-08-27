"""Build the list of running applications the user can choose to transfer."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List

import psutil

from ..winapi import windows as win

# Shell surfaces and our own UI are never migration candidates.
_EXCLUDED_EXES = {
    "explorer.exe", "searchhost.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "textinputhost.exe", "systemsettings.exe",
    "applicationframehost.exe", "lockapp.exe", "widgets.exe", "sihost.exe",
}
_EXCLUDED_TITLES = {
    "Program Manager",
    "Windows Input Experience",
    "Windows Shell Experience Host",
}

_FRIENDLY_NAMES = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "brave.exe": "Brave",
    "firefox.exe": "Mozilla Firefox",
    "code.exe": "Visual Studio Code",
    "vlc.exe": "VLC Media Player",
    "notepad.exe": "Notepad",
    "notepad++.exe": "Notepad++",
    "wordpad.exe": "WordPad",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "sublime_text.exe": "Sublime Text",
    "pycharm64.exe": "PyCharm",
    "idea64.exe": "IntelliJ IDEA",
    "windowsterminal.exe": "Windows Terminal",
    "spotify.exe": "Spotify",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "obsidian.exe": "Obsidian",
    "krita.exe": "Krita",
    "blender.exe": "Blender",
    "mpv.exe": "mpv",
}


@dataclass
class AppInfo:
    hwnd: int
    pid: int
    title: str
    exe_path: str
    exe_name: str
    cmdline: List[str] = field(default_factory=list)
    cwd: str = ""
    memory_mb: float = 0.0
    rect: tuple = (0, 0, 0, 0)

    @property
    def display_name(self) -> str:
        """A human label rather than an executable name."""
        friendly = _FRIENDLY_NAMES.get(self.exe_name.lower())
        if friendly:
            return friendly
        stem = os.path.splitext(self.exe_name)[0]
        return stem.replace("_", " ").replace("-", " ").title()

    @property
    def key(self) -> str:
        return f"{self.pid}:{self.hwnd}"


def list_running_apps(include_self: bool = False) -> List[AppInfo]:
    """One entry per application process, using its largest visible window.

    Multi-window apps such as browsers and editors collapse to a single row,
    because the unit of transfer is the application session rather than an
    individual window.
    """
    own_pid = os.getpid()
    best_by_pid: Dict[int, win.WindowInfo] = {}

    for window in win.enumerate_windows():
        if not include_self and window.pid == own_pid:
            continue
        if window.title in _EXCLUDED_TITLES:
            continue
        current = best_by_pid.get(window.pid)
        if current is None or window.area > current.area:
            best_by_pid[window.pid] = window

    apps: List[AppInfo] = []
    for pid, window in best_by_pid.items():
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                exe_name = proc.name() or ""
                if exe_name.lower() in _EXCLUDED_EXES:
                    continue
                try:
                    exe_path = proc.exe() or ""
                except (psutil.AccessDenied, OSError):
                    exe_path = ""
                try:
                    cmdline = list(proc.cmdline())
                except (psutil.AccessDenied, OSError):
                    cmdline = [exe_path] if exe_path else []
                try:
                    cwd = proc.cwd() or ""
                except (psutil.AccessDenied, OSError):
                    cwd = ""
            memory_mb = _tree_memory_mb(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue

        apps.append(AppInfo(
            hwnd=window.hwnd,
            pid=pid,
            title=window.title,
            exe_path=exe_path,
            exe_name=exe_name,
            cmdline=cmdline,
            cwd=cwd,
            memory_mb=memory_mb,
            rect=window.rect,
        ))

    apps.sort(key=lambda a: (a.display_name.lower(), a.pid))
    return apps


def _tree_memory_mb(proc: psutil.Process) -> float:
    """Chromium-style apps spread across children, so report the whole tree."""
    total = 0
    try:
        total += proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0
    return total / (1024 * 1024)


def process_tree_pids(pid: int) -> set:
    """Every pid belonging to one application, parent plus descendants."""
    pids = {pid}
    try:
        proc = psutil.Process(pid)
        pids.update(child.pid for child in proc.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return pids
