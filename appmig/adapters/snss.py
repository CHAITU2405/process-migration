"""A focused reader for Chromium's SNSS session files.

Only enough of the format is implemented to answer one question: which tabs are
open, and what page is each one showing?

File layout::

    "SNSS" + int32 version
    repeated: uint16 size, uint8 command_id, (size - 1) bytes of payload

Payloads are Chromium ``base::Pickle`` buffers: a uint32 payload size followed by
4-byte-aligned fields. Strings are a int32 length then the bytes, padded up to
the next multiple of four.

Command ids below are from ``session_service_commands.cc``. They apply to
``Session_*`` files, which describe the *live* session. ``Tabs_*`` files use a
different id set and describe recently *closed* tabs, so they are deliberately
not read here -- restoring from them would reopen tabs the user had shut.
"""
from __future__ import annotations

import struct
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Tuple

MAGIC = b"SNSS"

CMD_SET_TAB_WINDOW = 0
CMD_SET_TAB_INDEX_IN_WINDOW = 2
CMD_UPDATE_TAB_NAVIGATION = 6
CMD_SET_SELECTED_NAVIGATION_INDEX = 7
CMD_TAB_CLOSED = 16
CMD_WINDOW_CLOSED = 17

_ALLOWED_SCHEMES = ("http://", "https://", "file://")


def iter_commands(blob: bytes) -> Iterator[Tuple[int, bytes]]:
    if blob[:4] != MAGIC or len(blob) < 8:
        return
    offset = 8
    total = len(blob)
    while offset + 2 <= total:
        (size,) = struct.unpack_from("<H", blob, offset)
        offset += 2
        if size == 0 or offset + size > total:
            return
        yield blob[offset], blob[offset + 1: offset + size]
        offset += size


def _read_int(payload: bytes, pos: int) -> Tuple[Optional[int], int]:
    if pos + 4 > len(payload):
        return None, pos
    (value,) = struct.unpack_from("<i", payload, pos)
    return value, pos + 4


def _read_string(payload: bytes, pos: int) -> Tuple[Optional[bytes], int]:
    length, pos = _read_int(payload, pos)
    if length is None or length < 0 or pos + length > len(payload):
        return None, pos
    data = payload[pos: pos + length]
    pos += length + (-length % 4)  # pickle pads fields to 4-byte alignment
    return data, pos


def _read_pair(payload: bytes) -> Optional[Tuple[int, int]]:
    """Most commands are just two int32s after the pickle header."""
    if len(payload) < 12:
        return None
    first, pos = _read_int(payload, 4)
    second, _pos = _read_int(payload, pos)
    if first is None or second is None:
        return None
    return first, second


def _read_navigation(payload: bytes) -> Optional[Tuple[int, int, str]]:
    """kCommandUpdateTabNavigation: tab id, entry index, and the page URL."""
    if len(payload) < 16:
        return None
    tab_id, pos = _read_int(payload, 4)
    index, pos = _read_int(payload, pos)
    raw_url, _pos = _read_string(payload, pos)
    if tab_id is None or index is None or not raw_url:
        return None
    try:
        url = raw_url.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not url.startswith(_ALLOWED_SCHEMES):
        return None
    return tab_id, index, url


def open_tab_urls(blob: bytes) -> List[str]:
    """The current URL of every tab still open in this session, in tab order."""
    known_tabs: Dict[int, int] = {}          # tab id -> index within its window
    closed_tabs: set = set()
    selected_index: Dict[int, int] = {}
    navigations: Dict[int, Dict[int, str]] = defaultdict(dict)
    highest_index: Dict[int, int] = {}

    for command_id, payload in iter_commands(blob):
        if command_id == CMD_SET_TAB_WINDOW:
            pair = _read_pair(payload)
            if pair is not None:
                known_tabs.setdefault(pair[1], 0)   # payload is (window id, tab id)
        elif command_id == CMD_SET_TAB_INDEX_IN_WINDOW:
            pair = _read_pair(payload)
            if pair is not None:
                known_tabs[pair[0]] = pair[1]
        elif command_id == CMD_TAB_CLOSED:
            pair = _read_pair(payload)
            if pair is not None:
                closed_tabs.add(pair[0])
        elif command_id == CMD_SET_SELECTED_NAVIGATION_INDEX:
            pair = _read_pair(payload)
            if pair is not None:
                selected_index[pair[0]] = pair[1]
        elif command_id == CMD_UPDATE_TAB_NAVIGATION:
            parsed = _read_navigation(payload)
            if parsed is not None:
                tab_id, index, url = parsed
                navigations[tab_id][index] = url
                highest_index[tab_id] = max(highest_index.get(tab_id, -1), index)
                known_tabs.setdefault(tab_id, 0)

    urls: List[str] = []
    seen: set = set()
    for tab_id in sorted(known_tabs, key=lambda t: (known_tabs.get(t, 0), t)):
        if tab_id in closed_tabs:
            continue
        entries = navigations.get(tab_id)
        if not entries:
            continue
        # Prefer the entry the tab was actually sitting on; fall back to the
        # newest one we saw for it.
        index = selected_index.get(tab_id, highest_index.get(tab_id, -1))
        url = entries.get(index) or entries.get(highest_index.get(tab_id, -1))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def looks_like_session_file(name: str) -> bool:
    return name.rsplit("/", 1)[-1].startswith("Session_")
