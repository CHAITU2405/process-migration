"""Process-wide DPI awareness.

This matters more than it looks. On a scaled display (125% is the common laptop
default) a process that is *not* per-monitor DPI aware gets lied to by Windows:
``GetWindowRect`` returns virtualised coordinates, and ``PrintWindow`` renders
into a bitmap sized to match, so captured frames come back clipped and soft.

Must be called before any window is created, and before any capture.
"""
from __future__ import annotations

import ctypes

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_PROCESS_PER_MONITOR_DPI_AWARE = 2

_applied = False


def enable_dpi_awareness() -> str:
    """Opt this process into true physical pixels. Returns which path worked."""
    global _applied
    if _applied:
        return "already applied"

    # Windows 10 1703 and newer.
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2):
            _applied = True
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass

    # Windows 8.1 and newer.
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(_PROCESS_PER_MONITOR_DPI_AWARE) == 0:
            _applied = True
            return "per-monitor"
    except (AttributeError, OSError):
        pass

    # Vista and newer: system-wide awareness only.
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            _applied = True
            return "system"
    except (AttributeError, OSError):
        pass

    return "unavailable"


def scale_for_window(hwnd: int) -> float:
    """The scale factor of the monitor a window is on, 1.0 at 96 DPI."""
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        return (dpi / 96.0) if dpi else 1.0
    except (AttributeError, OSError):
        return 1.0
