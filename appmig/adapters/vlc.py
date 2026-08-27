"""VLC media player.

VLC records recently played media and their playback positions in
``vlc-qt-interface.ini`` when it exits cleanly. Carrying that file plus the
media path lets playback resume where it stopped, provided the media itself is
reachable from the target machine.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from ..discovery.apps import AppInfo
from .base import FIDELITY_HIGH, CapturedState, LaunchSpec, StateAdapter

_EXE_CANDIDATES = [
    r"%PROGRAMFILES%\VideoLAN\VLC\vlc.exe",
    r"%PROGRAMFILES(X86)%\VideoLAN\VLC\vlc.exe",
]
_MEDIA_SUFFIXES = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg",
    ".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a", ".opus", ".wma",
    ".m3u", ".m3u8", ".xspf",
}


class VLCAdapter(StateAdapter):
    id = "vlc"
    display_name = "VLC Media Player"
    fidelity = FIDELITY_HIGH
    carries = "Current media file and playback position."

    def can_handle(self, app: AppInfo) -> bool:
        return app.exe_name.lower() == "vlc.exe"

    def capture(self, app: AppInfo, state: CapturedState) -> None:
        media = self._media_path(app)
        state.meta["media"] = media or ""

        config_dir = _config_dir()
        if config_dir is not None:
            for name in ("vlc-qt-interface.ini", "vlcrc"):
                path = config_dir / name
                if path.is_file():
                    try:
                        state.add_file(f"vlcconfig/{name}", path.read_bytes())
                    except OSError:
                        continue

        if media:
            state.notes.append(f"Media: {os.path.basename(media)}")
            state.notes.append(
                "Playback position resumes only if VLC has 'Continue playback' "
                "enabled on the target machine."
            )
        else:
            state.notes.append("No media file detected; VLC opens with an empty playlist.")

    def _media_path(self, app: AppInfo) -> Optional[str]:
        for argument in app.cmdline[1:]:
            if argument.startswith("-"):
                continue
            if Path(argument).suffix.lower() in _MEDIA_SUFFIXES:
                return os.path.abspath(argument)
        return None

    def restore(self, state: CapturedState, workdir: Path) -> LaunchSpec:
        executable = self.resolve_executable(state, _EXE_CANDIDATES)
        if executable is None:
            raise FileNotFoundError("VLC is not installed on this machine.")

        warnings: List[str] = []
        config_dir = _config_dir()
        if config_dir is not None:
            source = self.materialise(state, workdir, "vlcconfig")
            if any(source.iterdir()):
                config_dir.mkdir(parents=True, exist_ok=True)
                self.copy_into(source, config_dir)

        argv = [executable]
        media = state.meta.get("media") or ""
        if media:
            if os.path.exists(media):
                argv.append(media)
            else:
                warnings.append(
                    f"The media file {media} is not reachable from this machine. "
                    "Use a shared or network path for media that should follow "
                    "the session."
                )
        return LaunchSpec(argv=argv, warnings=warnings)


def _config_dir() -> Optional[Path]:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "vlc" if appdata else None
