"""Check what link exists between this laptop and the other one.

    python check_link.py             # list usable interfaces
    python check_link.py --watch     # watch for a cable being plugged in
    python check_link.py 169.254.1.5 # test reachability of the other laptop

Run this on both machines. Any interface it lists as usable will carry the
transfer, whether that is USB4, Ethernet, or Wi-Fi.
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from typing import Dict, List, Tuple

from appmig import config

# Interface descriptions that mean a direct cable between two machines.
_DIRECT_LINK_HINTS = ("thunderbolt", "usb4", "usb 4", "remote ndis", "usb ethernet")


def interfaces() -> List[Tuple[str, str, bool]]:
    """(name, ipv4, is_link_local) for every up IPv4 interface."""
    import psutil

    stats = psutil.net_if_stats()
    found = []
    for name, addresses in psutil.net_if_addrs().items():
        if not stats.get(name) or not stats[name].isup:
            continue
        for address in addresses:
            if address.family != socket.AF_INET:
                continue
            if address.address.startswith("127."):
                continue
            found.append((name, address.address, address.address.startswith("169.254.")))
    return found


def classify(name: str) -> str:
    lowered = name.lower()
    if any(hint in lowered for hint in _DIRECT_LINK_HINTS):
        return "direct cable"
    if "ethernet" in lowered:
        return "ethernet"
    if "wi-fi" in lowered or "wireless" in lowered:
        return "wi-fi"
    if "bluetooth" in lowered:
        return "bluetooth (too slow)"
    if "tailscale" in lowered or "vpn" in lowered:
        return "vpn tunnel"
    return "other"


def show() -> Dict[str, str]:
    rows = interfaces()
    if not rows:
        print("No usable IPv4 interfaces are up.")
        return {}

    print(f"{'INTERFACE':<32} {'ADDRESS':<17} {'KIND':<20} NOTE")
    print("-" * 92)
    best: Dict[str, str] = {}
    for name, address, link_local in sorted(rows, key=lambda r: r[0]):
        kind = classify(name)
        note = ""
        if link_local:
            note = "link-local: a direct cable with no DHCP -- this is normal and works"
        if kind == "bluetooth":
            note = "far too slow for streaming"
        if kind == "vpn tunnel":
            note = "works, but routes over the internet"
        print(f"{name[:31]:<32} {address:<17} {kind:<20} {note}")
        if kind in ("direct cable", "ethernet") and kind not in best:
            best[kind] = address
    print()

    if "direct cable" in best:
        print(f"Best link: direct cable at {best['direct cable']}")
    elif "ethernet" in best:
        print(f"Best link: ethernet at {best['ethernet']}")
    else:
        print("No direct cable detected. Wi-Fi will work; a cable will be faster.")
    print("\nOn the other laptop, run:  python main.py agent")
    print("Then enter this laptop's address on the controller's Connection page.")
    return best


def watch() -> None:
    """Poll while you plug the cable in, and report what appears."""
    print("Watching for a new interface. Plug the cable in now. Ctrl+C to stop.\n")
    known = {(name, address) for name, address, _ll in interfaces()}
    for name, address in sorted(known):
        print(f"  already up: {name}  {address}")
    print()
    try:
        while True:
            time.sleep(1.5)
            current = {(name, address) for name, address, _ll in interfaces()}
            for entry in sorted(current - known):
                print(f"  + APPEARED: {entry[0]}  {entry[1]}   ({classify(entry[0])})",
                      flush=True)
                print("    The cable is up. Re-run without --watch for details.",
                      flush=True)
            for entry in sorted(known - current):
                print(f"  - went away: {entry[0]}  {entry[1]}", flush=True)
            known = current
    except KeyboardInterrupt:
        print("\nStopped.")


def probe(host: str) -> None:
    """Check whether the other laptop is reachable, and whether its agent is up."""
    print(f"Testing {host}...\n")

    result = subprocess.run(
        ["ping", "-n", "2", "-w", "1500", host],
        capture_output=True, text=True,
    )
    reachable = result.returncode == 0
    print(f"  ping            : {'reachable' if reachable else 'no reply'}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    try:
        sock.connect((host, config.CONTROL_PORT))
        print(f"  agent port {config.CONTROL_PORT}: OPEN -- the agent is running")
    except OSError as exc:
        print(f"  agent port {config.CONTROL_PORT}: closed ({exc.__class__.__name__})")
        if reachable:
            print("\n  The laptop is reachable but the agent is not running there.")
            print("  Start it with:  python main.py agent")
        else:
            print("\n  No network path to that address. Check the cable, and that")
            print("  both machines list an address on the same subnet.")
    finally:
        sock.close()


def main(argv=None) -> int:
    if sys.platform != "win32":
        print("This tool targets Windows.")
        return 1

    parser = argparse.ArgumentParser(description="Check the link between two laptops")
    parser.add_argument("host", nargs="?", help="Address of the other laptop to test")
    parser.add_argument("--watch", action="store_true",
                        help="Watch for a cable being plugged in")
    args = parser.parse_args(argv)

    if args.watch:
        watch()
    elif args.host:
        probe(args.host)
    else:
        show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
