# AppMigrate

Move a running application from one laptop to another. The app closes on laptop 1,
restarts on laptop 2 with its session intact, and its window is streamed back to
laptop 1 — so you keep the screen and the keyboard while the other machine does
the work.

![status](https://img.shields.io/badge/platform-Windows-blue) ![status](https://img.shields.io/badge/status-working%20prototype-green)

---

## How it actually works

The obvious approach — serialise a live process and rehydrate it elsewhere —
is not possible on Windows. There is no checkpoint/restore API, and even Linux's
CRIU falls over on GUI and GPU applications. So AppMigrate does something else:

> **It lets the application save itself.**

Every app that reopens where you left off already has session persistence built
in. Browsers have Session Restore, VS Code has workspace storage, Notepad keeps
unsaved tab text on disk. So instead of inventing a state capturer, AppMigrate
asks the app to close *gracefully* and then harvests the files it wrote on the
way out.

```
 LAPTOP 1 (controller)                          LAPTOP 2 (agent)
 ─────────────────────                          ────────────────
 1. adapter.prepare()      nudge app to save
 2. WM_CLOSE               app flushes session
 3. adapter.capture()      harvest its files
 4. write rollback         ← safety net on disk
 5. ship bundle  ────────────────────────────▶  6. adapter.restore()
                                                7. launch + find window
                          ◀──────────────────── 8. confirm live
 9. discard rollback
10. render frames ◀───────── JPEG stream ─────── capture window @ 20fps
11. mouse/keys  ──────────── input events ─────▶ inject into window
```

Step 4 matters. The app must be closed before its state can be captured, so it is
gone before we know the far side succeeded. Every capture is therefore written to
a rollback bundle first; if the restore fails, the session comes straight back up
on laptop 1.

---

## What survives the move

Fidelity is per-application, and the UI labels each one honestly before you commit.

| Badge | Applications | What carries across |
|---|---|---|
| **Full session** | Chrome, Edge, Brave | Open tabs and their current URLs |
| **Full session** | Windows 11 Notepad | Open tabs *including unsaved text* |
| **Full session** | VLC | Current media file and playback position |
| **Partial** | VS Code | Workspace folder, open editors, layout |
| **Fresh start** | everything else | Relaunches with the same command line |

The generic adapter matches every application, so nothing is greyed out — some
entries simply arrive clean. Notepad is the most convincing demo: type something,
never save it, transfer, and the words are still there on the other machine.

---

## Running it

Both laptops need Windows and Python 3.10+. Copy the project to both and run the
same command on each:

```bash
python run.py
```

That is the whole setup. Everything else is managed from the window: whether
this laptop receives applications, which target to send to, pairing, Tailscale,
and the transfer itself. There is no separate agent command.

On the **Connection** page, the laptop that should do the work presses
**Start receiving**. The other one picks it from the target list and presses
**Connect**. Then choose an app on the **Applications** page and press
**Transfer**.

Either machine can play either role, and both at once.

Optional flags, mostly for putting a dedicated machine straight into service:

```bash
python run.py --receive --name Workhorse
```

`run.bat` is a double-click wrapper for the same thing. For a laptop that should
receive with no window at all, `run_agent.py` still runs the agent headless.

<details>
<summary>Notes</summary>

Dependencies install themselves on first run, so a fresh laptop needs only
Python and a copy of this folder.

The Windows Store build of Python reports itself as `python3.13.exe` rather than
`python.exe`, which matters if you go looking for the process. `run.bat` uses the
`py` launcher to sidestep this.
</details>

---

## Finding the other laptop

Three ways, all shown in one list on the Connection page:

| Source | How it is found | When it applies |
|---|---|---|
| **Local link** | UDP broadcast | A cable, or both on the same Wi-Fi |
| **Tailscale** | `tailscale status --json` | Anywhere your tailnet reaches |
| **Manual** | You type the address | Broadcast filtered, or anything else |

Broadcast stops at the local link, so it will never find a laptop across a
tailnet. Rather than invent a second discovery mechanism, AppMigrate asks the
Tailscale CLI, which already knows every machine on your network. Tailscale peers
are marked with the connection quality Tailscale reports:

- **Direct** — a real peer-to-peer path. Fast enough for the video stream.
- **Relayed** — routed through a DERP relay. The state transfer works fine; the
  remote UI will usually lag.

Peers are probed in the background to see whether AppMigrate is actually running
over there, since being on the tailnet says nothing about that. A machine that
cannot run the agent at all — an iPhone, an Android — is listed but not offered.

Local entries win over Tailscale entries for the same machine, because a direct
link is always the better path.

---

## Pairing

An agent launches applications and receives keystrokes on request. That is far
too much authority to grant anything that can open a socket, and over Tailscale
every device on your tailnet can.

So each laptop has a **pairing code**, shown on its Connection page under "This
laptop". The first time another machine connects it must present that code; after
that it is remembered. Rejected connections are closed immediately, before any
other message is served.

Connections from the same machine (loopback) are exempt, so testing on one laptop
needs no ceremony.

**New code** issues a fresh one and invalidates the old — use it if a code has
been shared somewhere it should not have been.

---

## Connecting the two laptops by cable

Everything speaks plain TCP/IP, so the transport is whatever carries IP between
the machines. Develop over Wi-Fi, then plug in a cable and change nothing.

| Link | Works? | Notes |
|---|---|---|
| **USB4 / Thunderbolt 3–4, both ends** | ✅ best | Windows raises a *Thunderbolt Network* adapter; 10–20 Gbps |
| Ethernet cable, direct | ✅ | Link-local addressing sorts itself out |
| Wi-Fi, same network | ✅ | Fine for testing and for most apps |
| USB-C to USB-C, non-Thunderbolt ports | ❌ | No data link between two hosts |
| USB-A to USB-A cable | ❌ | Both ends are hosts. Don't buy one |
| USB "data transfer bridge" cable | ⚠️ | Works, but ~20–30 MB/s — too slow for video |

At 1080p the stream runs roughly 10–15 Mbps, so any of the working options is
comfortable.

### Checking your link

```bash
python check_link.py                # list usable interfaces on this machine
python check_link.py --watch        # watch for a cable being plugged in
python check_link.py 169.254.1.5    # test reachability of the other laptop
```

A direct cable usually comes up with a **link-local** address (`169.254.x.x`) on
both ends because there is no DHCP server between two laptops. That is normal and
works fine — read the address off `check_link.py` on the agent machine and type it
into the controller's Connection page if the UDP beacon does not find it by itself.

**USB-C to USB-C only works if both laptops have USB4 or Thunderbolt 3/4**, on a
port that supports it (usually marked ⚡), with a cable rated for data rather than
charge-only. Host-to-host IP over AMD USB4 is less proven than over Intel
Thunderbolt, so test it before relying on it. A plain **USB-A to USB-C cable never
works** — both ends are hosts.

---

## Does it actually save resources?

Laptop 1 isn't free after the handoff — it decodes JPEG frames and runs a socket
loop, costing a few percent CPU and tens of MB of RAM.

- **Heavy apps** — compilers, simulations, video export, ML, IDEs with big
  indexes: real savings. This is the case worth building for.
- **Light apps** — a text editor, a calculator: you may spend more than you save.

---

## Layout

```
appmig/
├── config.py            ports, timeouts, feature flags
├── security.py          pairing codes and remembered peers
├── migrate.py           the prepare → close → capture → rollback sequence
├── bundle.py            zip-based state bundle, pack/unpack/checksum
├── protocol/
│   ├── messages.py      wire message ids
│   └── channel.py       length-prefixed framing over one full-duplex socket
├── winapi/
│   ├── dpi.py           per-monitor DPI awareness (required for correct capture)
│   ├── windows.py       enumeration, graceful close, PrintWindow capture
│   └── input.py         PostMessage / SendInput injection
├── discovery/
│   ├── apps.py          the running-applications list
│   ├── peers.py         UDP beacon and peer presence
│   └── tailscale.py     tailnet peers and link quality
├── adapters/
│   ├── base.py          the adapter contract
│   ├── snss.py          Chromium session-file reader
│   ├── browser.py       Chrome / Edge / Brave
│   ├── vscode.py        Visual Studio Code
│   ├── notepad.py       Windows 11 Notepad
│   ├── vlc.py           VLC
│   └── generic.py       universal fallback
├── agent/
│   ├── server.py        laptop 2: receive, restore, stream
│   ├── embedded.py      run the agent inside the app, driven from the UI
│   └── streamer.py      window capture and JPEG encode loop
└── ui/
    ├── targets.py       merges local + Tailscale + manual into one list
    └── ...              PySide6 pages
```

---

## Adding an adapter

Subclass `StateAdapter`, implement three methods, register it in
`adapters/registry.py` ahead of the generic fallback.

```python
class MyAppAdapter(StateAdapter):
    id = "myapp"
    fidelity = FIDELITY_HIGH
    carries = "Open documents and cursor position."

    def can_handle(self, app):
        return app.exe_name.lower() == "myapp.exe"

    def capture(self, app, state):
        # Runs AFTER the app has closed, so its session files are complete.
        state.add_tree(Path(...), "myapp")

    def restore(self, state, workdir):
        source = self.materialise(state, workdir, "myapp")
        self.copy_into(source, Path(...))
        return LaunchSpec(argv=[self.resolve_executable(state, [...])])
```

---

## Design notes and known limits

**Browsers restore into an isolated profile** by default, so a transfer never
overwrites the real browser profile on the target. Tabs come back; saved logins
and extensions do not. Flip `BROWSER_SANDBOX_PROFILE` in `config.py` to transplant
into the real profile instead — more seamless, but it requires the browser to be
closed on the target.

**Files must be reachable from both machines.** A VS Code workspace or a VLC media
file at `C:\Users\you\project` only restores fully if that path exists on the
target too. Restores still happen, with a warning. Shared or network paths avoid
this entirely.

**Window discovery uses two strategies.** Packaged apps (Notepad, Paint), launcher
stubs and single-instance apps hand off to a process that is not a descendant of
the one we launched, so the pid tree is tried first and a new-window-by-executable
match second.

**DPI awareness is not optional.** On a scaled display a non-DPI-aware process
gets virtualised window rects and clipped `PrintWindow` bitmaps. Both entry points
call `enable_dpi_awareness()` before anything else.

**Input injection defaults to `PostMessage`**, which does not disturb the target
machine's real cursor. Some hardware-accelerated apps ignore synthetic messages;
set `INPUT_MODE = "sendinput"` in `config.py` for those, at the cost of taking
over that machine's mouse and keyboard.

### Not implemented

- **Return transfers.** Moving a session back means running the controller on the
  other laptop. The plumbing is symmetric; only the UI flow is missing.
- **H.264 streaming.** Frames are JPEG, chosen so the project needs no external
  binaries. `WindowStreamer._encode` is the single seam to replace for an
  NVENC/QuickSync path.
- **Multiple concurrent sessions.** The agent restores and streams one at a time.
- **Transport encryption.** Pairing gates who may connect, but the link itself is
  not encrypted. Over Tailscale that does not matter: Tailscale already encrypts
  everything end to end. Over a plain LAN it does — treat that as a trusted
  network, or route it through Tailscale.
