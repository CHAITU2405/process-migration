"""Replay controller-side mouse/keyboard events onto a window on the agent.

Two strategies:

``post``      PostMessage window messages straight at the target. Does not
              disturb the agent machine's real cursor or focus, so the agent can
              still be used for something else. Works for most Win32/Qt/Electron
              apps; a few hardware-accelerated ones ignore synthetic messages.
``sendinput`` Drive the agent's actual input stack. Universal, but it takes over
              that machine's mouse and keyboard.

Coordinates arriving from the controller are relative to the **captured window
image**, whose origin is the window's top-left corner including its border and
title bar. Window messages, however, carry **client** coordinates, whose origin
sits inside that frame. Injecting one as the other puts every click roughly a
title-bar's height below where the user aimed, so the translation below is not
optional.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import windows as win

user32 = win.user32
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

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

_SENDINPUT_BUTTON_FLAGS = {
    ("left", True): 0x0002, ("left", False): 0x0004,
    ("right", True): 0x0008, ("right", False): 0x0010,
    ("middle", True): 0x0020, ("middle", False): 0x0040,
}

user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.RealChildWindowFromPoint.argtypes = [wintypes.HWND, wintypes.POINT]
user32.RealChildWindowFromPoint.restype = wintypes.HWND
user32.MapWindowPoints.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.POINTER(wintypes.POINT), wintypes.UINT]
user32.GetFocus.restype = wintypes.HWND
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]


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
    """Applies controller input to one target window on the agent."""

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
            for character in event.get("text", ""):
                self._char(character)

    # -- coordinate translation ----------------------------------------------
    def _client_offset(self) -> tuple:
        """Where the client area starts, relative to the window's top-left.

        This is the border width and title bar height. Recomputed per event
        because the window can be moved, resized, or maximised at any time.
        """
        point = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(wintypes.HWND(self.hwnd), ctypes.byref(point)):
            return 0, 0
        left, top, _right, _bottom = win.window_rect(self.hwnd)
        return point.x - left, point.y - top

    def _to_client(self, window_x: int, window_y: int) -> tuple:
        offset_x, offset_y = self._client_offset()
        return window_x - offset_x, window_y - offset_y

    def _resolve_mouse_target(self, window_x: int, window_y: int) -> tuple:
        """Find the actual child control under the pointer.

        Classic Win32 apps put their edit boxes, buttons and canvases in child
        windows that must receive the message themselves; posting everything to
        the top-level window silently does nothing in those apps.
        """
        client_x, client_y = self._to_client(window_x, window_y)
        point = wintypes.POINT(client_x, client_y)
        child = user32.RealChildWindowFromPoint(wintypes.HWND(self.hwnd), point)
        if child and child != self.hwnd:
            mapped = wintypes.POINT(client_x, client_y)
            user32.MapWindowPoints(wintypes.HWND(self.hwnd), child,
                                   ctypes.byref(mapped), 1)
            return int(child), mapped.x, mapped.y
        return self.hwnd, client_x, client_y

    def _focus_target(self) -> int:
        """The control that currently has keyboard focus inside the app."""
        thread_id = user32.GetWindowThreadProcessId(wintypes.HWND(self.hwnd), None)
        our_thread = kernel32.GetCurrentThreadId()
        if not thread_id or thread_id == our_thread:
            return self.hwnd
        if not user32.AttachThreadInput(our_thread, thread_id, True):
            return self.hwnd
        try:
            focused = user32.GetFocus()
        finally:
            user32.AttachThreadInput(our_thread, thread_id, False)
        return int(focused) if focused else self.hwnd

    def _to_screen(self, window_x: int, window_y: int) -> tuple:
        left, top, _right, _bottom = win.window_rect(self.hwnd)
        return left + window_x, top + window_y

    # -- post-message path ----------------------------------------------------
    def _ensure_focus(self) -> None:
        if self.mode == "sendinput" and not self._focused:
            user32.SetForegroundWindow(wintypes.HWND(self.hwnd))
            self._focused = True

    def _mouse_move(self, x: int, y: int) -> None:
        if self.mode == "post":
            target, cx, cy = self._resolve_mouse_target(x, y)
            user32.PostMessageW(target, WM_MOUSEMOVE, 0, _lparam(cx, cy))
            return
        self._ensure_focus()
        screen_x, screen_y = self._to_screen(x, y)
        width = user32.GetSystemMetrics(SM_CXSCREEN) or 1
        height = user32.GetSystemMetrics(SM_CYSCREEN) or 1
        event = INPUT(type=INPUT_MOUSE)
        event.mi = MOUSEINPUT(
            dx=int(screen_x * 65535 / width), dy=int(screen_y * 65535 / height),
            mouseData=0, dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
            time=0, dwExtraInfo=None)
        _send_input(event)

    def _mouse_button(self, x: int, y: int, button: str, down: bool) -> None:
        if self.mode == "post":
            message, flag = _BUTTON_MESSAGES.get((button, down), (None, 0))
            if message is None:
                return
            target, cx, cy = self._resolve_mouse_target(x, y)
            if down:
                # Some controls only route input once they believe they have focus.
                user32.PostMessageW(target, WM_SETFOCUS, 0, 0)
            user32.PostMessageW(target, message, flag, _lparam(cx, cy))
            return
        self._mouse_move(x, y)
        flags = _SENDINPUT_BUTTON_FLAGS.get((button, down))
        if flags is None:
            return
        event = INPUT(type=INPUT_MOUSE)
        event.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags,
                              time=0, dwExtraInfo=None)
        _send_input(event)

    def _wheel(self, x: int, y: int, delta: int) -> None:
        if self.mode == "post":
            # WM_MOUSEWHEEL is the one mouse message that carries screen coords.
            screen_x, screen_y = self._to_screen(x, y)
            target, _cx, _cy = self._resolve_mouse_target(x, y)
            user32.PostMessageW(target, WM_MOUSEWHEEL,
                                (delta & 0xFFFF) << 16, _lparam(screen_x, screen_y))
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
            user32.PostMessageW(self._focus_target(),
                                WM_KEYDOWN if down else WM_KEYUP, vk, lparam)
            return
        self._ensure_focus()
        event = INPUT(type=INPUT_KEYBOARD)
        event.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0 if down else KEYEVENTF_KEYUP,
                              time=0, dwExtraInfo=None)
        _send_input(event)

    def _char(self, character: str) -> None:
        if self.mode == "post":
            user32.PostMessageW(self._focus_target(), WM_CHAR, ord(character), 1)
            return
        self._ensure_focus()
        down = INPUT(type=INPUT_KEYBOARD)
        down.ki = KEYBDINPUT(wVk=0, wScan=ord(character), dwFlags=KEYEVENTF_UNICODE,
                             time=0, dwExtraInfo=None)
        up = INPUT(type=INPUT_KEYBOARD)
        up.ki = KEYBDINPUT(wVk=0, wScan=ord(character),
                           dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                           time=0, dwExtraInfo=None)
        _send_input(down, up)
