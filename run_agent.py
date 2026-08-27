"""Laptop 2. The machine that does the work.

    python run_agent.py [--port 47811] [--name "Workhorse"]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime


def main(argv=None) -> int:
    if sys.platform != "win32":
        print("The agent uses Win32 APIs and only runs on Windows.")
        return 1

    from appmig import config
    from appmig.agent.server import Agent
    from appmig.winapi.dpi import enable_dpi_awareness
    from appmig.discovery.peers import local_addresses

    parser = argparse.ArgumentParser(description="AppMigrate agent")
    parser.add_argument("--port", type=int, default=config.CONTROL_PORT)
    parser.add_argument("--name", default=None, help="Name shown to controllers")
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)

    mode = enable_dpi_awareness()
    print(f"{config.APP_NAME} agent {config.VERSION}  (dpi: {mode})")
    for address in local_addresses():
        print(f"  reachable at {address}")
    print()

    agent = Agent(port=args.port, log=log, name=args.name)
    try:
        agent.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        agent.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
