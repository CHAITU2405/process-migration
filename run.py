#!/usr/bin/env python3
"""AppMigrate. Run this on both laptops.

    python run.py

Everything is managed from the window that opens: whether this laptop receives
applications, which target to send to, pairing, Tailscale, and the transfer
itself. There is no separate agent command to remember -- the Connection page
has a "Start receiving" switch.

    python run.py --receive        start receiving immediately on launch
    python run.py --name Workhorse the name other laptops see
    python run.py --port 47811     listen somewhere other than the default
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# import name -> pip name
REQUIREMENTS = {"PySide6": "PySide6", "psutil": "psutil", "PIL": "Pillow"}


def missing_packages() -> List[str]:
    return [pip_name for module, pip_name in REQUIREMENTS.items()
            if find_spec(module) is None]


def ensure_dependencies() -> bool:
    """Install what is missing, so a fresh laptop needs only Python."""
    pending = missing_packages()
    if not pending:
        return True

    print(f"  First run: installing {', '.join(pending)}\n")
    requirements = ROOT / "requirements.txt"
    command = [sys.executable, "-m", "pip", "install"]
    command += ["-r", str(requirements)] if requirements.is_file() else pending

    if subprocess.run(command, cwd=str(ROOT)).returncode != 0:
        print(
            "\n  Install failed.\n"
            "  If pip complained about path length, enable Long Path support:\n"
            "    https://pip.pypa.io/warnings/enable-long-paths\n"
        )
        return False

    print("\n  Dependencies installed.\n")
    return True


def main() -> int:
    if sys.platform != "win32":
        print("AppMigrate uses Win32 APIs and only runs on Windows.")
        return 1

    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Move a running application to another laptop.",
    )
    parser.add_argument("--receive", action="store_true",
                        help="Start receiving as soon as the window opens")
    parser.add_argument("--name", default=None,
                        help="Name other laptops see for this machine")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to receive on")
    args = parser.parse_args()

    if not ensure_dependencies():
        input("\n  Press Enter to close. ")
        return 1

    # DPI awareness must be set before Qt or any window capture happens.
    from appmig.winapi.dpi import enable_dpi_awareness
    enable_dpi_awareness()

    from PySide6.QtWidgets import QApplication

    from appmig import config, security
    from appmig.ui import theme
    from appmig.ui.main_window import MainWindow

    print(f"  {config.APP_NAME} {config.VERSION}")
    print(f"  Pairing code for this laptop: {security.format_code(security.local_code())}")
    print()

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setStyleSheet(theme.STYLESHEET)

    window = MainWindow()
    if args.name:
        window.agent_name = args.name
    window.show()

    if args.receive:
        window.start_receiving(name=args.name, port=args.port)

    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
