"""keyboard-remapperd: grabs keyboards, translates keys, emits on ONE virtual device.

Design rule (the whole point of this project): there is exactly one output
device, created at start-up and never re-created.  Pass-through keys and
remapped keys leave through it, so the desktop never sees the key source
switch between devices and never re-registers its global shortcuts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import struct
import sys
from dataclasses import dataclass, field

from evdev import ecodes as e

from . import __version__, keys
from .backend import Backend, EvdevBackend, FakeBackend, InputHandle, NodeInfo, fake_keyboard
from .engine import Engine, Output
from .mapping import MappingError, Preset

log = logging.getLogger("keyboard_remapper.daemon")

DEFAULT_SOCKET = "/run/keyboard-remapper/keyboard-remapper.sock"
DEFAULT_STATE = "/var/lib/keyboard-remapper/state.json"
CAPTURE_TIMEOUT_S = 25.0
RESCAN_INTERVAL_S = 1.0
GRAB_RETRY_S = 0.03
GRAB_GIVE_UP_S = 3.0


class LoopScheduler:
    def __init__(self, loop):
        self.loop = loop

    def call_later(self, delay_ms, fn):
        return self.loop.call_later(delay_ms / 1000.0, fn)


@dataclass
class Group:
    """All input nodes of one physical keyboard."""

    id: str
    model: str
    name: str
    nodes: dict[str, tuple[NodeInfo, InputHandle]] = field(default_factory=dict)
    engine: Engine | None = None
    capture: bool = False
    capture_timer: object = None
    grabbed: bool = False
    grab_pending: bool = False

    def handles(self):
        return [h for _, h in self.nodes.values()]


def peer_allowed(uid: int) -> bool:
    """root, or a user with an active local login session."""
    if uid == 0:
        return True
    sessions = "/run/systemd/sessions"
    try:
        names = os.listdir(sessions)
    except OSError:
        return os.path.isdir(f"/run/user/{uid}")
    for n in names:
        try:
            with open(os.path.join(sessions, n)) as f:
                kv = dict(line.strip().split("=", 1) for line in f if "=" in line)
        except OSError:
            continue
        if kv.get("UID") == str(uid) and kv.get("ACTIVE") == "1" and kv.get("REMOTE", "0") == "0":
            return True
    return False


class Client:
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.monitor = False
        self.monitor_out = False
        self.capture_models: set[str] = set()

    def send(self, msg: dict) -> None:
        try:
            self.writer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        except (ConnectionError, RuntimeError):
            pass


class Daemon:
    def __init__(self, backend: Backend, state_path: str | None = DEFAULT_STATE,
                 socket_path: str = DEFAULT_SOCKET, grab_all: bool = False,
                 check_peer: bool = True):
        self.backend = backend
        self.state_path = state_path
        self.socket_path = socket_path
        self.grab_all = grab_all
        self.check_peer = check_peer
        self.loop: asyncio.AbstractEventLoop | None = None
        self.out_dev = None
        self.output: Output | None = None
        self.groups: dict[str, Group] = {}
        self.clients: set[Client] = set()
        self.presets: dict[str, dict] = {}       # model -> {"preset": dict, "enabled": bool}
        self.server = None
        self._rescan_handle = None
        self._valid_codes = set(keys.keyboard_codes())

    def _emit(self, code: int, value: int) -> None:
        """Every key event leaves through here: the one virtual device (and the output monitors)."""
        self.out_dev.write(code, value)
        for c in self.clients:
            if c.monitor_out:
                c.send({"event": "out", "code": code, "value": value})

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._load_state()
        # THE one and only virtual device.  Never re-created while we run.
        self.out_dev = self.backend.create_output()
        self.out_dev.attach_leds(self.loop, self._on_led)
        self.output = Output(self._emit)
        self.rescan()
        if self.socket_path:
            await self._serve()
        self._rescan_handle = self.loop.call_later(RESCAN_INTERVAL_S, self._rescan_tick)

    async def stop(self) -> None:
        if self._rescan_handle:
            self._rescan_handle.cancel()
        if self.server:
            self.server.close()
        for c in list(self.clients):
            c.writer.close()
        await asyncio.sleep(0)
        for g in list(self.groups.values()):
            self._drop_group(g)
        if self.output:
            self.output.release_all()
        if self.out_dev:
            self.out_dev.close()
        if self.socket_path:
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

    def _rescan_tick(self) -> None:
        try:
            self.rescan()
        except Exception:
            log.exception("rescan failed")
        self._rescan_handle = self.loop.call_later(RESCAN_INTERVAL_S, self._rescan_tick)

    # -- persistence --------------------------------------------------------

    def _load_state(self) -> None:
        if not self.state_path:
            return
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            self.presets = dict(data.get("models", {}))
            self.grab_all = bool(data.get("grab_all", self.grab_all))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("could not read %s", self.state_path)

    def _save_state(self) -> None:
        if not self.state_path:
            return
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"models": self.presets, "grab_all": self.grab_all}, f)
            os.replace(tmp, self.state_path)
        except OSError:
            log.warning("could not write %s", self.state_path, exc_info=True)

    # -- device discovery -----------------------------------------------------

    def rescan(self) -> None:
        infos = self.backend.scan()
        present = {i.path for i in infos}
        changed = False
        for g in list(self.groups.values()):
            for path in list(g.nodes):
                if path not in present:
                    self._remove_node(g, path)
                    changed = True
        known = {p for g in self.groups.values() for p in g.nodes}
        by_group: dict[str, list[NodeInfo]] = {}
        for i in infos:
            if i.path not in known:
                by_group.setdefault(f"{i.model}@{i.phys_base}", []).append(i)
        for gid, new_nodes in by_group.items():
            g = self.groups.get(gid)
            if g is None:
                if not any(i.is_main for i in new_nodes):
                    continue          # a consumer-control node alone is not a keyboard
                main = next(i for i in new_nodes if i.is_main)
                g = Group(gid, main.model, main.name)
                self.groups[gid] = g
            for i in new_nodes:
                try:
                    h = self.backend.open(i)
                except OSError as ex:
                    log.warning("cannot open %s: %s", i.path, ex)
                    continue
                g.nodes[i.path] = (i, h)
                h.attach(self.loop, lambda evs, g=g: self._on_events(g, evs),
                         lambda g=g, p=i.path: self._on_lost(g, p))
            self._configure(g)
            changed = True
        if changed:
            self._broadcast({"event": "devices", "devices": self.device_list()})

    def _on_lost(self, g: Group, path: str) -> None:
        self._remove_node(g, path)
        self._broadcast({"event": "devices", "devices": self.device_list()})

    def _remove_node(self, g: Group, path: str) -> None:
        item = g.nodes.pop(path, None)
        if item:
            item[1].close()
        if not g.nodes:
            self._drop_group(g)

    def _drop_group(self, g: Group) -> None:
        if g.engine:
            g.engine.release_all()
        for _, h in g.nodes.values():
            h.ungrab()
            h.close()
        g.nodes.clear()
        if g.capture_timer:
            g.capture_timer.cancel()
        self.groups.pop(g.id, None)

    # -- configuration --------------------------------------------------------

    def _configure(self, g: Group) -> None:
        entry = self.presets.get(g.model)
        want_engine = (entry is not None and entry.get("enabled", True)) or self.grab_all
        if want_engine:
            if g.engine is None:
                g.engine = Engine(self.output, LoopScheduler(self.loop), engine_id=g.id)
            preset = Preset.from_dict(entry["preset"]) if entry and entry.get("enabled", True) else Preset()
            g.engine.set_preset(preset)
        elif g.engine is not None:
            g.engine.release_all()
            g.engine = None
        self._update_grab(g)

    def _update_grab(self, g: Group) -> None:
        wanted = g.engine is not None or g.capture
        if wanted and not g.grabbed and not g.grab_pending:
            g.grab_pending = True
            self._try_grab(g, self.loop.time() + GRAB_GIVE_UP_S)
        elif not wanted and g.grabbed:
            if g.engine:
                g.engine.release_all()
            for h in g.handles():
                h.ungrab()
            g.grabbed = False

    def _try_grab(self, g: Group, deadline: float) -> None:
        """Grab once no key is held, otherwise the desktop would never see its release."""
        if g.id not in self.groups:
            return
        if not (g.engine is not None or g.capture):
            g.grab_pending = False
            return
        if any(h.active_keys() for h in g.handles()) and self.loop.time() < deadline:
            self.loop.call_later(GRAB_RETRY_S, self._try_grab, g, deadline)
            return
        g.grab_pending = False
        for info, h in g.nodes.values():
            try:
                h.grab()
            except OSError as ex:
                log.warning("cannot grab %s: %s", info.path, ex)
        g.grabbed = True

    # -- event path (hot) ------------------------------------------------------

    def _on_events(self, g: Group, events) -> None:
        for etype, code, value in events:
            if etype != e.EV_KEY:
                continue
            if value != 2 and any(c.monitor for c in self.clients):
                msg = {"event": "key", "group": g.id, "model": g.model, "code": code,
                       "value": value, "captured": g.capture}
                for c in self.clients:
                    if c.monitor:
                        c.send(msg)
            if g.capture or not g.grabbed or g.engine is None:
                continue
            if code in self._valid_codes:
                g.engine.handle(code, value)

    def _on_led(self, code: int, value: int) -> None:
        for g in self.groups.values():
            for h in g.handles():
                h.set_led(code, value)

    # -- IPC ------------------------------------------------------------------

    async def _serve(self) -> None:
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass
        self.server = await asyncio.start_unix_server(self._client, path=self.socket_path,
                                                      limit=32 * 1024 * 1024)
        os.chmod(self.socket_path, 0o666)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.check_peer:
            sock = writer.get_extra_info("socket")
            try:
                _pid, uid, _gid = struct.unpack("3i", sock.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            except OSError:
                uid = -1
            if not peer_allowed(uid):
                writer.close()
                return
        c = Client(writer)
        self.clients.add(c)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                req = {}
                try:
                    req = json.loads(line)
                    reply = self.dispatch(c, req)
                except (ValueError, KeyError, TypeError, MappingError) as ex:
                    reply = {"ok": False, "error": str(ex)}
                if isinstance(req, dict) and "id" in req:
                    reply["id"] = req["id"]
                c.send(reply)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.clients.discard(c)
            for model in list(c.capture_models):
                self.set_capture(model, False)
            writer.close()

    def device_list(self) -> list[dict]:
        out = []
        for g in self.groups.values():
            main = next((i for i, _ in g.nodes.values() if i.is_main), None)
            entry = self.presets.get(g.model)
            out.append({
                "id": g.id, "model": g.model, "name": g.name,
                "vendor": main.vendor if main else 0, "product": main.product if main else 0,
                "bus": main.bus if main else 0,
                "layout_hint": main.layout_hint if main else "",
                "applied": bool(entry and entry.get("enabled", True)),
                "configured": entry is not None,
            })
        out.sort(key=lambda d: (d["name"].lower(), d["id"]))
        return out

    def dispatch(self, c: Client, req: dict) -> dict:
        cmd = req["cmd"]
        if cmd == "hello":
            return {"ok": True, "version": __version__, "fake": self.backend.is_fake,
                    "devices": self.device_list(), "grab_all": self.grab_all}
        if cmd == "devices":
            return {"ok": True, "devices": self.device_list()}
        if cmd == "apply":
            model = str(req["model"])
            preset = Preset.from_dict(req["preset"], strict=True)
            self.presets[model] = {"preset": preset.to_dict(), "enabled": bool(req.get("enabled", True))}
            self._save_state()
            self._reconfigure(model)
            return {"ok": True}
        if cmd == "enable":
            model = str(req["model"])
            if model in self.presets:
                self.presets[model]["enabled"] = bool(req["enabled"])
                self._save_state()
                self._reconfigure(model)
            return {"ok": True}
        if cmd == "forget":
            self.presets.pop(str(req["model"]), None)
            self._save_state()
            self._reconfigure(str(req["model"]))
            return {"ok": True}
        if cmd == "get_preset":
            entry = self.presets.get(str(req["model"]))
            return {"ok": True, "entry": entry}
        if cmd == "monitor":
            c.monitor = bool(req.get("on", True))
            c.monitor_out = c.monitor and bool(req.get("output", False))
            return {"ok": True}
        if cmd == "capture":
            model = str(req["model"])
            on = bool(req.get("on", True))
            (c.capture_models.add if on else c.capture_models.discard)(model)
            self.set_capture(model, on)
            return {"ok": True}
        if cmd == "set_options":
            if "grab_all" in req:
                self.grab_all = bool(req["grab_all"])
                self._save_state()
                for g in self.groups.values():
                    self._configure(g)
            return {"ok": True}
        if self.backend.is_fake and cmd.startswith("debug_"):
            return self._debug(req)
        return {"ok": False, "error": f"unknown command {cmd!r}"}

    def _reconfigure(self, model: str) -> None:
        for g in self.groups.values():
            if g.model == model:
                self._configure(g)
        self._broadcast({"event": "devices", "devices": self.device_list()})

    def set_capture(self, model: str, on: bool) -> None:
        for g in self.groups.values():
            if g.model != model:
                continue
            if g.capture_timer:
                g.capture_timer.cancel()
                g.capture_timer = None
            if on:
                if g.engine:
                    g.engine.release_all()
                g.capture = True
                g.capture_timer = self.loop.call_later(
                    CAPTURE_TIMEOUT_S, self._capture_timeout, g)
            else:
                g.capture = False
            self._update_grab(g)

    def _capture_timeout(self, g: Group) -> None:
        g.capture_timer = None
        g.capture = False
        self._update_grab(g)
        self._broadcast({"event": "capture_ended", "model": g.model})

    def _broadcast(self, msg: dict) -> None:
        for c in self.clients:
            c.send(msg)

    # -- fake-backend debugging --------------------------------------------------

    def _debug(self, req: dict) -> dict:
        b: FakeBackend = self.backend           # type: ignore[assignment]
        cmd = req["cmd"]
        if cmd == "debug_inject":
            path = req["path"]
            b.inputs[path].inject(int(req["code"]), int(req["value"]))
            return {"ok": True}
        if cmd == "debug_output":
            return {"ok": True, "devices_created": len(b.outputs),
                    "log": [[keys.code_to_name(c), v] for c, v in b.outputs[-1].log]}
        if cmd == "debug_clear":
            b.outputs[-1].log.clear()
            return {"ok": True}
        if cmd == "debug_state":
            return {"ok": True, "groups": {
                g.id: {"grabbed": g.grabbed, "capture": g.capture, "engine": g.engine is not None,
                       "nodes": list(g.nodes)} for g in self.groups.values()}}
        return {"ok": False, "error": "unknown debug command"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="keyboard-remapperd")
    ap.add_argument("--version", action="version", version=f"keyboard-remapperd {__version__}")
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    ap.add_argument("--state", default=DEFAULT_STATE)
    ap.add_argument("--grab-all", action="store_true",
                    help="route every keyboard through the virtual device (no device switching at all)")
    ap.add_argument("--fake", action="store_true", help="use in-memory fake keyboards (testing)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    if args.fake:
        backend: Backend = FakeBackend(fake_keyboard(0, "Demo Keyboard", 0x1234, 0x5678)
                                       + fake_keyboard(1, "Demo Mini Keyboard", 0x4321, 0x8765, False))
    else:
        if os.geteuid() != 0:
            print("keyboard-remapperd must run as root (it reads /dev/input and writes /dev/uinput)",
                  file=sys.stderr)
            return 1
        backend = EvdevBackend()

    daemon = Daemon(backend, state_path=args.state, socket_path=args.socket,
                    grab_all=args.grab_all, check_peer=not args.fake)

    async def run() -> None:
        await daemon.start()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(s, stop.set)
        log.info("keyboard-remapperd %s ready on %s", __version__, args.socket)
        await stop.wait()
        await daemon.stop()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
