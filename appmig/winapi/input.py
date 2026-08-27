"""Replay controller-side mouse/keyboard events onto a window on the agent.

Two strategies:

``post``      PostMessage window messages straight at the target hwnd. Does not
              disturb the agent machine's real cursor or focus. Works for most
              Win32/Qt/Electron apps; some hardware-accelerated apps ignore it.
``sendinput`` Drive the agent's actual input stack. Universal, but it takes over
              that machine's mouse and keyboard.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import windows as win

user32 = win.user32

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_CHAR = 0x0102
WM_SETFOCUS = 0x0007

MK_LBUTTON, MK_RBUTTON, MK_MBUTTON = 0x0001, 0x0002, 0x0010

_BUTTON_MESSAGES = {
    ("left", True): (WM_LBUTTONDOWN, MK_LBUTTON),
    ("left", False): (WM_LBUTTONUP, 0),
    ("right", True): (WM_RBUTTONDOWN, MK_RBUTTON),
    ("right", False): (WM_RBUTTONUP, 0),
    ("middle", True): (WM_MBUTTONDOWN, MK_MBUTTON),
    ("middle", False): (WM_MBUTTONUP, 0),
}

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
SM_CXSCREEN, SM_CYSCREEN = 0, 1


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _lparam(x: int, y: int) -> int:
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


def _send_input(*inputs: INPUT) -> None:
    array = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))


class InputInjector:
    """Applies input events to one target window."""

    def __init__(self, hwnd: int, mode: str = "post"):
        self.hwnd = hwnd
        self.mode = mode
        self._focused = False

    # -- public ---------------------------------------------------------------
    def apply(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "move":
            self._mouse_move(event["x"], event["y"])
        elif kind == "button":
            self._mouse_button(event["x"], event["y"], event.get("button", "left"),
                               bool(event.get("down")))
        elif kind == "wheel":
            self._wheel(event["x"], event["y"], int(event.get("delta", 0)))
        elif kind == "key":
            self._key(int(event.get("vk", 0)), bool(event.get("down")))
        elif kind == "text":
            for ch in event.get("text", ""):
                self._char(ch)

    # -- post-message path ----------------------------------------------------
    def _post(self, msg: int, wparam: int, lparam: int) -> None:
        user32.PostMessageW(self.hwnd, msg, wparam, lparam)

    def _ensure_focus(self) -> None:
        if self.mode == "sendinput" and not self._focused:
            user32.SetForegroundWindow(self.hwnd)
            self._focused = True

    def _to_screen(self, x: int, y: int) -> tuple:
        left, top, _r, _b = win.window_rect(self.hwnd)
        return left + x, top + y

    def _mouse_move(self, x: int, y: int) -> None:
        if self.mode == "post":
            self._post(WM_MOUSEMOVE, 0, _lparam(x, y))
            return
        self._ensure_focus()
        sx, sy = self._to_screen(x, y)
        width = user32.GetSystemMetrics(SM_CXSCREEN) or 1
        height = user32.GetSystemMetrics(SM_CYSCREEN) or 1
        event = INPUT(type=INPUT_MOUSE)
        event.mi = MOUSEINPUT(
            dx=int(sx * 65535 / width), dy=int(sy * 65535 / height), mouseData=0,
            dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, time=0, dwExtraInfo=None)
        _send_input(event)

    def _mouse_button(self, x: int, y: int, button: str, down: bool) -> None:
        if self.mode == "post":
            msg, flag = _BUTTON_MESSAGES.get((button, down), (None, 0))
            if msg is None:
                return
            if down:
                # Some apps only route input after they believe they have focus.
                self._post(WM_SETFOCUS, 0, 0)
            self._post(msg, flag, _lparam(x, y))
            return
        self._mouse_move(x, y)
        flags = {
            ("left", True): 0x0002, ("left", False): 0x0004,
            ("right", True): 0x0008, ("right", False): 0x0010,
            ("middle", True): 0x0020, ("middle", False): 0x0040,
        }.get((button, down))
        if flags is None:
            return
        event = INPUT(type=INPUT_MOUSE)
        event.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None)
        _send_input(event)

    def _wheel(self, x: int, y: int, delta: int) -> None:
        if self.mode == "post":
            sx, sy = self._to_screen(x, y)
            self._post(WM_MOUSEWHEEL, (delta & 0xFFFF) << 16, _lparam(sx, sy))
            return
        event = INPUT(type=INPUT_MOUSE)
        event.mi = MOUSEINPUT(dx=0, dy=0, mouseData=delta, dwFlags=MOUSEEVENTF_WHEEL,
                              time=0, dwExtraInfo=None)
        _send_input(event)

    def _key(self, vk: int, down: bool) -> None:
        if not vk:
            return
        if self.mode == "post":
            scan = user32.MapVirtualKeyW(vk, 0)
            lparam = 1 | (scan << 16)
            if not down:
                lparam |= (1 << 30) | (1 << 31)
            self._post(WM_KEYDOWN if down else WM_KEYUP, vk, lparam)
            return
        self._ensure_focus()
        event = INPUT(type=INPUT_KEYBOARD)
        event.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0 if down else KEYEVENTF_KEYUP,
                              time=0, dwExtraInfo=None)
        _send_input(event)

    def _char(self, ch: str) -> None:
        if self.mode == "post":
            self._post(WM_CHAR, ord(ch), 1)
            return
        self._ensure_focus()
        down = INPUT(type=INPUT_KEYBOARD)
        down.ki = KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=KEYEVENTF_UNICODE,
                             time=0, dwExtraInfo=None)
        up = INPUT(type=INPUT_KEYBOARD)
        up.ki = KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                           time=0, dwExtraInfo=None)
        _send_input(down, up)
