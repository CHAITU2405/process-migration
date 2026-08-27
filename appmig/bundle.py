"""Serialise a captured application state into a single transferable blob.

A bundle is a zip archive holding one ``manifest.json`` plus a ``files/`` tree
of whatever the adapter decided was worth carrying across.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Dict

from .adapters.base import CapturedState

MANIFEST_NAME = "manifest.json"
FILES_PREFIX = "files/"


def pack(state: CapturedState) -> bytes:
    manifest = {
        "adapter_id": state.adapter_id,
        "app_name": state.app_name,
        "exe_path": state.exe_path,
        "exe_name": state.exe_name,
        "cmdline": state.cmdline,
        "cwd": state.cwd,
        "fidelity": state.fidelity,
        "meta": state.meta,
        "notes": state.notes,
        "title": state.title,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for relative_path, content in state.files.items():
            archive.writestr(FILES_PREFIX + relative_path.replace("\\", "/"), content)
    return buffer.getvalue()


def unpack(blob: bytes) -> CapturedState:
    with zipfile.ZipFile(io.BytesIO(blob), "r") as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME))
        files: Dict[str, bytes] = {}
        for entry in archive.namelist():
            if entry.startswith(FILES_PREFIX) and not entry.endswith("/"):
                files[entry[len(FILES_PREFIX):]] = archive.read(entry)

    return CapturedState(
        adapter_id=manifest["adapter_id"],
        app_name=manifest.get("app_name", ""),
        exe_path=manifest.get("exe_path", ""),
        exe_name=manifest.get("exe_name", ""),
        cmdline=manifest.get("cmdline", []),
        cwd=manifest.get("cwd", ""),
        fidelity=manifest.get("fidelity", "fresh"),
        meta=manifest.get("meta", {}),
        notes=manifest.get("notes", []),
        title=manifest.get("title", ""),
        files=files,
    )


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def write_rollback(blob: bytes, session_id: str, directory: Path) -> Path:
    """Keep the captured state on disk until the far side confirms a restore.

    This is the safety net that makes closing the source app survivable.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.ambundle"
    path.write_bytes(blob)
    return path
