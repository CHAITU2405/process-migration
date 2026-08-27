"""Win32 window enumeration, graceful close, and window capture via ctypes."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Callable, List, Optional

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

WM_CLOSE = 0x0010
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
DWMWA_CLOAKED = 14
PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    rect: tuple = field(default=(0, 0, 0, 0))

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _is_cloaked(hwnd: int) -> bool:
    """UWP windows stay 'visible' after being hidden by the shell; DWM knows better."""
    cloaked = wintypes.DWORD()
    result = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return result == 0 and cloaked.value != 0


def window_rect(hwnd: int) -> tuple:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (0, 0, 0, 0)
    return (rect.left, rect.top, rect.right, rect.bottom)


def client_size(hwnd: int) -> tuple:
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return (0, 0)
    return (rect.right - rect.left, rect.bottom - rect.top)


def pid_for_window(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def enumerate_windows(predicate: Optional[Callable[[WindowInfo], bool]] = None) -> List[WindowInfo]:
    """Every top-level window a human would consider 'an open app window'."""
    found: List[WindowInfo] = []

    def _callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        # Only true top-level windows; skip owned dialogs and popups.
        if user32.GetAncestor(hwnd, 3) != hwnd:  # GA_ROOTOWNER
            return True
        title = _window_title(hwnd)
        if not title.strip():
            return True
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex_style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
            return True
        if _is_cloaked(hwnd):
            return True
        rect = window_rect(hwnd)
        info = WindowInfo(hwnd=int(hwnd), pid=pid_for_window(hwnd), title=title, rect=rect)
        if info.width < 80 or info.height < 60:
            return True
        if predicate is None or predicate(info):
            found.append(info)
        return True

    user32.EnumWindows(WNDENUMPROC(_callback), 0)
    return found


def windows_for_pids(pids: set[int]) -> List[WindowInfo]:
    return enumerate_windows(lambda w: w.pid in pids)


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


PARK_X, PARK_Y = -32000, -32000
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010


def park_offscreen(hwnd: int) -> tuple:
    """Move a window off the visible desktop, returning where it was.

    The application keeps running and keeps rendering -- PrintWindow captures an
    off-screen window exactly as it captures a visible one -- but it no longer
    appears on the target machine's screen and cannot be clicked there by
    accident. This is what makes the target a headless worker rather than a
    second machine somebody has to leave alone.
    """
    original = window_rect(hwnd)
    user32.SetWindowPos(hwnd, 0, PARK_X, PARK_Y, 0, 0,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    return original


def restore_position(hwnd: int, rect: tuple) -> None:
    """Put a parked window back where it was."""
    if not rect or not is_window(hwnd):
        return
    left, top, right, bottom = rect
    if left <= PARK_X:
        left, top = 80, 80        # never restore it back to nowhere
    user32.SetWindowPos(hwnd, 0, left, top, 0, 0,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def request_close(hwnd: int) -> None:
    """Ask nicely. This is what lets the app flush its own session state."""
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def wait_for_exit(pid: int, timeout: float) -> bool:
    import psutil

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True
    try:
        proc.wait(timeout=timeout)
        return True
    except psutil.TimeoutExpired:
        return False
    except psutil.NoSuchProcess:
        return True


def wait_for_window(pids: set[int], timeout: float, poll: float = 0.4) -> Optional[WindowInfo]:
    """Poll until one of these processes puts a real window on screen."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = windows_for_pids(pids)
        if candidates:
            return max(candidates, key=lambda w: w.area)
        time.sleep(poll)
    return None


def snapshot_hwnds() -> set:
    """Every window that exists right now, so new ones can be told apart."""
    return {window.hwnd for window in enumerate_windows()}


def find_launched_window(
    pid: int,
    exe_name: str,
    before: set,
    timeout: float,
    poll: float = 0.4,
) -> Optional[WindowInfo]:
    """Locate the window belonging to an app we just started.

    The obvious approach -- watch the pid we launched and its children -- fails
    for a large class of Windows applications. Packaged apps such as Notepad,
    launcher stubs, and single-instance apps all hand off to a process that is
    not our descendant. So the pid tree is tried first for precision, then we
    fall back to any newly appeared window whose process has the same executable
    name.
    """
    import psutil

    from ..discovery.apps import process_tree_pids

    target = (exe_name or "").lower()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        # Precise: a window owned by the process tree we started.
        owned = windows_for_pids(process_tree_pids(pid))
        if owned:
            return max(owned, key=lambda w: w.area)

        # Fallback: a window that did not exist before, from a matching binary.
        fresh = []
        for window in enumerate_windows():
            if window.hwnd in before:
                continue
            try:
                name = psutil.Process(window.pid).name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
            if name == target:
                fresh.append(window)
        if fresh:
            return max(fresh, key=lambda w: w.area)

        time.sleep(poll)
    return None


def capture_window(hwnd: int):
    """Grab a window's pixels into a PIL image, even when it is occluded.

    Returns ``None`` if the window vanished or has no drawable area.
    """
    from PIL import Image

    if not is_window(hwnd):
        return None
    left, top, right, bottom = window_rect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None

    hdc_window = user32.GetWindowDC(hwnd)
    if not hdc_window:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    old = gdi32.SelectObject(hdc_mem, hbitmap)
    try:
        # PW_RENDERFULLCONTENT is what makes this work for Chromium/UWP surfaces.
        ok = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
        if not ok:
            gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_window, 0, 0, SRCCOPY)

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height   # negative => top-down rows
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(
            hdc_mem, hbitmap, 0, height, buffer, ctypes.byref(info), DIB_RGB_COLORS
        )
        if not copied:
            return None
        return Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)
