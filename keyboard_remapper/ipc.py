"""Blocking/threaded client for the daemon's JSON-lines socket."""

from __future__ import annotations

import itertools
import json
import socket
import threading
from typing import Callable

from .daemon import DEFAULT_SOCKET


class Client:
    """Thread-based client.  ``on_event``/``on_state`` run on the reader thread."""

    def __init__(self, path: str = DEFAULT_SOCKET,
                 on_event: Callable[[dict], None] | None = None,
                 on_state: Callable[[bool], None] | None = None):
        self.path = path
        self.on_event = on_event
        self.on_state = on_state
        self.sock: socket.socket | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, Callable[[dict], None]] = {}
        self._lock = threading.Lock()
        self.connected = False

    def connect(self) -> bool:
        if self.connected:
            return True
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(self.path)
        except OSError:
            s.close()
            return False
        self.sock = s
        self.connected = True
        threading.Thread(target=self._read, args=(s,), daemon=True).start()
        if self.on_state:
            self.on_state(True)
        return True

    def close(self) -> None:
        s, self.sock = self.sock, None
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    def _read(self, s: socket.socket) -> None:
        buf = b""
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        self._dispatch(json.loads(line))
        except (OSError, ValueError):
            pass
        finally:
            self.connected = False
            with self._lock:
                pending, self._pending = self._pending, {}
            for cb in pending.values():
                cb({"ok": False, "error": "disconnected"})
            if self.on_state:
                self.on_state(False)

    def _dispatch(self, msg: dict) -> None:
        if "id" in msg:
            with self._lock:
                cb = self._pending.pop(msg["id"], None)
            if cb:
                cb(msg)
        elif self.on_event:
            self.on_event(msg)

    def request_async(self, cmd: str, callback: Callable[[dict], None] | None = None, **kw) -> None:
        if not self.connected or self.sock is None:
            if callback:
                callback({"ok": False, "error": "not connected"})
            return
        rid = next(self._ids)
        if callback:
            with self._lock:
                self._pending[rid] = callback
        data = (json.dumps({"id": rid, "cmd": cmd, **kw}, ensure_ascii=False) + "\n").encode()
        try:
            with self._lock:
                self.sock.sendall(data)
        except OSError:
            with self._lock:
                cb = self._pending.pop(rid, None)
            if cb:
                cb({"ok": False, "error": "not connected"})

    def request(self, cmd: str, timeout: float = 5.0, **kw) -> dict:
        done = threading.Event()
        box: dict = {}

        def cb(msg: dict) -> None:
            box.update(msg)
            done.set()

        self.request_async(cmd, cb, **kw)
        if not done.wait(timeout):
            return {"ok": False, "error": "timeout"}
        return box
