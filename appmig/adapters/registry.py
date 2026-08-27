"""Adapter lookup. First match wins; the generic adapter always matches last."""
from __future__ import annotations

from typing import Dict, List

from ..discovery.apps import AppInfo
from .base import StateAdapter
from .browser import ChromiumAdapter
from .generic import GenericAdapter
from .notepad import NotepadAdapter
from .vlc import VLCAdapter
from .vscode import VSCodeAdapter

_SPECIALISED: List[StateAdapter] = [
    ChromiumAdapter(),
    VSCodeAdapter(),
    NotepadAdapter(),
    VLCAdapter(),
]
_FALLBACK = GenericAdapter()

_BY_ID: Dict[str, StateAdapter] = {
    adapter.id: adapter for adapter in (*_SPECIALISED, _FALLBACK)
}


def adapter_for(app: AppInfo) -> StateAdapter:
    for adapter in _SPECIALISED:
        try:
            if adapter.can_handle(app):
                return adapter
        except Exception:
            continue
    return _FALLBACK


def adapter_by_id(adapter_id: str) -> StateAdapter:
    adapter = _BY_ID.get(adapter_id)
    if adapter is None:
        raise KeyError(f"Unknown adapter: {adapter_id}")
    return adapter


def all_adapters() -> List[StateAdapter]:
    return [*_SPECIALISED, _FALLBACK]
