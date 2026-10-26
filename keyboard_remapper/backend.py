"""Device back-ends: real evdev/uinput and an in-memory fake for tests."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from typing import Callable

from evdev import ecodes as e

from . import keys

VIRTUAL_NAME = "Keyboard Remapper virtual keyboard"
LEGACY_VIRTUAL_NAMES = ("Remapper virtual keyboard",)      # created by versions before the rename

# (type, code, value)
Event = tuple[int, int, int]


@dataclass
class NodeInfo:
    path: str
    name: str
    phys: str
    vendor: int
    product: int
    bus: int
    is_main: bool      # has the alphabet: a real keyboard rather than a consumer-control node
    uniq: str = ""     # unique id (Bluetooth address); tells apart devices that share a phys
    layout_hint: str = ""   # "jis" when the keyboard reports Yen / Ro keys (only JIS keyboards have them)

    @property
    def phys_base(self) -> str:
        base = self.phys.rsplit("/input", 1)[0] if self.phys else self.path
        return f"{base}|{self.uniq}" if self.uniq else base

    @property
    def model(self) -> str:
        return f"{self.vendor:04x}:{self.product:04x}"


class InputHandle:
    """One opened input node."""

    def attach(self, loop, on_events: Callable[[list[Event]], None],
               on_lost: Callable[[], None]) -> None: ...
    def detach(self) -> None: ...
    def grab(self) -> None: ...
    def ungrab(self) -> None: ...
    def active_keys(self) -> list[int]: ...
    def set_led(self, code: int, value: int) -> None: ...
    def close(self) -> None: ...


class OutputDevice:
    def write(self, code: int, value: int) -> None: ...
    def close(self) -> None: ...
    def attach_leds(self, loop, on_led: Callable[[int, int], None]) -> None: ...


class Backend:
    is_fake = False

    def create_output(self) -> OutputDevice: ...
    def scan(self) -> list[NodeInfo]: ...
    def open(self, info: NodeInfo) -> InputHandle: ...


# ---------------------------------------------------------------------------
# evdev
# ---------------------------------------------------------------------------

_LEDS = [e.LED_NUML, e.LED_CAPSL, e.LED_SCROLLL]


class EvdevInput(InputHandle):
    def __init__(self, path: str):
        import evdev
        self.dev = evdev.InputDevice(path)
        self._loop = None

    def attach(self, loop, on_events, on_lost) -> None:
        self._loop = loop
        os.set_blocking(self.dev.fd, False)

        def readable() -> None:
            try:
                batch = [(ev.type, ev.code, ev.value) for ev in self.dev.read()]
            except BlockingIOError:
                return
            except OSError:
                self.detach()
                on_lost()
                return
            if batch:
                on_events(batch)

        loop.add_reader(self.dev.fd, readable)

    def detach(self) -> None:
        if self._loop is not None:
            try:
                self._loop.remove_reader(self.dev.fd)
            except (ValueError, OSError):
                pass
            self._loop = None

    def grab(self) -> None:
        self.dev.grab()

    def ungrab(self) -> None:
        try:
            self.dev.ungrab()
        except OSError:
            pass

    def active_keys(self) -> list[int]:
        try:
            return self.dev.active_keys()
        except OSError:
            return []

    def set_led(self, code: int, value: int) -> None:
        try:
            self.dev.set_led(code, value)
        except OSError:
            pass

    def close(self) -> None:
        self.detach()
        try:
            self.dev.close()
        except OSError:
            pass


class EvdevOutput(OutputDevice):
    def __init__(self):
        import evdev
        caps = {e.EV_KEY: keys.keyboard_codes(), e.EV_LED: _LEDS}
        # No EV_REP: the desktop generates auto-repeat for held keys itself.
        self.ui = evdev.UInput(caps, name=VIRTUAL_NAME, vendor=0x1209, product=0x7e3a,
                               version=1, bustype=e.BUS_VIRTUAL)
        self._loop = None

    def write(self, code: int, value: int) -> None:
        self.ui.write(e.EV_KEY, code, value)
        self.ui.syn()

    def attach_leds(self, loop, on_led) -> None:
        self._loop = loop
        os.set_blocking(self.ui.fd, False)

        def readable() -> None:
            try:
                for ev in self.ui.read():
                    if ev.type == e.EV_LED:
                        on_led(ev.code, ev.value)
            except (BlockingIOError, OSError):
                pass

        loop.add_reader(self.ui.fd, readable)

    def close(self) -> None:
        if self._loop is not None:
            try:
                self._loop.remove_reader(self.ui.fd)
            except (ValueError, OSError):
                pass
        self.ui.close()


class EvdevBackend(Backend):
    def __init__(self):
        self._cache: dict[str, NodeInfo | None] = {}

    def create_output(self) -> OutputDevice:
        return EvdevOutput()

    def scan(self) -> list[NodeInfo]:
        import evdev
        try:
            names = [n for n in os.listdir("/dev/input") if n.startswith("event")]
        except OSError:
            names = []
        paths = {f"/dev/input/{n}" for n in names}
        for gone in set(self._cache) - paths:
            del self._cache[gone]
        for path in sorted(paths - set(self._cache)):
            self._cache[path] = self._probe(evdev, path)
        return [i for i in self._cache.values() if i is not None]

    @staticmethod
    def _probe(evdev, path: str) -> NodeInfo | None:
        try:
            dev = evdev.InputDevice(path)
        except OSError as ex:
            if ex.errno in (errno.ENOENT, errno.ENODEV):
                return None
            return None
        try:
            caps = dev.capabilities()
            ks = set(caps.get(e.EV_KEY, []))
            if dev.name == VIRTUAL_NAME or dev.name in LEGACY_VIRTUAL_NAMES or not ks:
                return None
            if e.EV_REL in caps or e.EV_ABS in caps:
                return None
            kbd = {c for c in ks if c < 0x100 or c >= 0x160}
            if not kbd:
                return None
            is_main = {e.KEY_A, e.KEY_Z, e.KEY_ENTER, e.KEY_SPACE} <= ks
            if not is_main and not (ks & {e.KEY_VOLUMEUP, e.KEY_PLAYPAUSE, e.KEY_MUTE,
                                          e.KEY_POWER, e.KEY_SLEEP, e.KEY_BRIGHTNESSUP,
                                          e.KEY_F1, e.KEY_LEFTCTRL}):
                return None
            return NodeInfo(path, dev.name, dev.phys or "", dev.info.vendor, dev.info.product,
                            dev.info.bustype, is_main, dev.uniq or "",
                            "jis" if ks & {e.KEY_YEN, e.KEY_RO} else "")
        finally:
            dev.close()

    def open(self, info: NodeInfo) -> InputHandle:
        return EvdevInput(info.path)


# ---------------------------------------------------------------------------
# fake (tests, demo)
# ---------------------------------------------------------------------------

class FakeInput(InputHandle):
    def __init__(self, info: NodeInfo):
        self.info = info
        self.grabbed = False
        self.down: set[int] = set()
        self.closed = False
        self._on_events = None
        self._on_lost = None
        self.leds: dict[int, int] = {}

    def attach(self, loop, on_events, on_lost) -> None:
        self._on_events, self._on_lost = on_events, on_lost

    def detach(self) -> None:
        self._on_events = None

    def grab(self) -> None:
        self.grabbed = True

    def ungrab(self) -> None:
        self.grabbed = False

    def active_keys(self) -> list[int]:
        return sorted(self.down)

    def set_led(self, code: int, value: int) -> None:
        self.leds[code] = value

    def close(self) -> None:
        self.closed = True
        self._on_events = None

    def inject(self, code: int, value: int) -> None:
        if value == 1:
            self.down.add(code)
        elif value == 0:
            self.down.discard(code)
        if self._on_events:
            self._on_events([(e.EV_KEY, code, value)])

    def unplug(self) -> None:
        if self._on_lost:
            self._on_lost()


class FakeOutput(OutputDevice):
    def __init__(self):
        self.log: list[tuple[int, int]] = []
        self.closed = False
        self._on_led = None

    def write(self, code: int, value: int) -> None:
        self.log.append((code, value))

    def attach_leds(self, loop, on_led) -> None:
        self._on_led = on_led

    def close(self) -> None:
        self.closed = True


class FakeBackend(Backend):
    is_fake = True

    def __init__(self, nodes: list[NodeInfo] | None = None):
        self.nodes: list[NodeInfo] = list(nodes or [])
        self.outputs: list[FakeOutput] = []      # every virtual device ever created
        self.inputs: dict[str, FakeInput] = {}

    def create_output(self) -> OutputDevice:
        out = FakeOutput()
        self.outputs.append(out)
        return out

    def scan(self) -> list[NodeInfo]:
        return list(self.nodes)

    def open(self, info: NodeInfo) -> InputHandle:
        h = FakeInput(info)
        self.inputs[info.path] = h
        return h

    # test helpers
    def plug(self, info: NodeInfo) -> None:
        self.nodes.append(info)

    def unplug(self, path: str) -> None:
        self.nodes = [n for n in self.nodes if n.path != path]
        h = self.inputs.pop(path, None)
        if h:
            h.unplug()


def fake_keyboard(index: int = 0, name: str = "Demo Keyboard", vendor: int = 0x1234,
                  product: int = 0x5678, consumer: bool = True) -> list[NodeInfo]:
    phys = f"usb-fake-{index}/input"
    nodes = [NodeInfo(f"/dev/input/fake{index}a", name, phys + "0", vendor, product, 3, True)]
    if consumer:
        nodes.append(NodeInfo(f"/dev/input/fake{index}b", name + " Consumer Control",
                              phys + "1", vendor, product, 3, False))
    return nodes
