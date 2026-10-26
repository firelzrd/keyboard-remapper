"""Glue between the GTK main loop and the daemon connection."""

from __future__ import annotations

from typing import Callable

from gi.repository import GLib

from ..ipc import Client


def _ui(fn):
    """Run *fn* on the GTK main loop (called from the reader thread)."""
    def wrapper(*a, **kw):
        GLib.idle_add(lambda: (fn(*a, **kw), False)[1])
    return wrapper


class DaemonLink:
    def __init__(self, socket_path: str):
        self.client = Client(socket_path, on_event=_ui(self._event), on_state=_ui(self._state))
        self.connected = False
        self.devices: list[dict] = []
        self.on_connection: list[Callable[[bool], None]] = []
        self.version: str | None = None            # version the daemon reports
        self.on_hello: list[Callable[[str | None], None]] = []
        self.on_devices: list[Callable[[list[dict]], None]] = []
        self.on_key: list[Callable[[dict], None]] = []
        self.on_capture_ended: list[Callable[[str], None]] = []
        self._retry = GLib.timeout_add_seconds(2, self._reconnect)
        self._reconnect()

    def _reconnect(self) -> bool:
        if not self.client.connected:
            self.client.connect()
        return True

    def _state(self, ok: bool) -> None:
        self.connected = ok
        if ok:
            self.client.request_async("hello", _ui(self._hello))
        else:
            self.devices = []
        for cb in list(self.on_connection):
            cb(ok)

    def _hello(self, msg: dict) -> None:
        if msg.get("ok"):
            self.version = msg.get("version")
            for cb in list(self.on_hello):
                cb(self.version)
            self.devices = msg.get("devices", [])
            for cb in list(self.on_devices):
                cb(self.devices)

    def _event(self, msg: dict) -> None:
        ev = msg.get("event")
        if ev == "devices":
            self.devices = msg.get("devices", [])
            for cb in list(self.on_devices):
                cb(self.devices)
        elif ev == "key":
            for cb in list(self.on_key):
                cb(msg)
        elif ev == "capture_ended":
            for cb in list(self.on_capture_ended):
                cb(msg.get("model", ""))

    # -- commands (fire and forget; the daemon is the source of truth for state)

    def apply(self, model: str, preset: dict, enabled: bool) -> None:
        self.client.request_async("apply", None, model=model, preset=preset, enabled=enabled)

    def forget(self, model: str) -> None:
        self.client.request_async("forget", None, model=model)

    def enable(self, model: str, enabled: bool) -> None:
        self.client.request_async("enable", None, model=model, enabled=enabled)

    def monitor(self, on: bool) -> None:
        self.client.request_async("monitor", None, on=on)

    def capture(self, model: str, on: bool) -> None:
        self.client.request_async("capture", None, model=model, on=on)
