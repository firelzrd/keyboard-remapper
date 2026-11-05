"""Device classification and the evdev scan cache (no real devices needed)."""

import os
from types import SimpleNamespace

from evdev import ecodes as e

from keyboard_remapper import backend
from keyboard_remapper.backend import EvdevBackend, NodeInfo, classify

ALPHA = {e.KEY_A, e.KEY_Z, e.KEY_ENTER, e.KEY_SPACE, e.KEY_LEFTCTRL}


def test_plain_keyboard_and_media_node():
    assert classify(ALPHA, set(), set()) is True
    assert classify({e.KEY_VOLUMEUP, e.KEY_MUTE}, set(), set()) is False


def test_pointers_are_never_taken():
    assert classify(ALPHA | {e.BTN_LEFT}, {e.REL_X, e.REL_Y, e.REL_WHEEL}, set()) is None
    assert classify(ALPHA, set(), {e.ABS_X, e.ABS_Y}) is None
    assert classify({e.BTN_LEFT, e.BTN_RIGHT}, {e.REL_X, e.REL_Y}, set()) is None
    assert classify(ALPHA, {e.REL_WHEEL}, set()) is None          # a scroll wheel would stop working


def test_keyboard_with_a_volume_axis_is_still_a_keyboard():
    """Some keyboards put ABS_VOLUME on their main node; they used to vanish from the list."""
    assert classify(ALPHA, set(), {e.ABS_VOLUME}) is True
    assert classify(ALPHA, set(), {e.ABS_MISC}) is True
    # a media node with an axis keeps working ungrabbed
    assert classify({e.KEY_VOLUMEUP}, set(), {e.ABS_VOLUME}) is None


def test_other_devices_skipped():
    assert classify(set(), set(), set()) is None
    assert classify({e.KEY_CAMERA_FOCUS}, set(), set()) is None


def _fake_dev(monkeypatch, nodes):
    """nodes: path -> [inode, name]; patch /dev/input listing, stat and probing."""
    monkeypatch.setattr(backend.os, "listdir", lambda p: [os.path.basename(k) for k in nodes])

    def stat(path):
        if path not in nodes:
            raise FileNotFoundError(path)
        return SimpleNamespace(st_rdev=1, st_ino=nodes[path][0], st_ctime_ns=0)

    monkeypatch.setattr(backend.os, "stat", stat)
    probes = []

    def probe(_evdev, path):
        probes.append(path)
        if nodes[path][1] is OSError:
            raise PermissionError(path)
        return NodeInfo(path, nodes[path][1], "p", 1, 2, 3, True)

    monkeypatch.setattr(EvdevBackend, "_probe", staticmethod(probe))
    return probes


def test_scan_reprobes_a_reused_event_node(monkeypatch):
    """eventN freed by an unplug and taken by another device: the cache must not keep the old one."""
    nodes = {"/dev/input/event5": [100, "Keyboard A"]}
    probes = _fake_dev(monkeypatch, nodes)
    b = EvdevBackend()
    assert [i.name for i in b.scan()] == ["Keyboard A"]
    assert [i.name for i in b.scan()] == ["Keyboard A"]
    assert len(probes) == 1                                   # cached while unchanged
    nodes["/dev/input/event5"] = [101, "Keyboard B"]          # same path, new node
    assert [i.name for i in b.scan()] == ["Keyboard B"]


def test_scan_retries_a_node_that_could_not_be_opened(monkeypatch):
    nodes = {"/dev/input/event3": [7, OSError]}
    _fake_dev(monkeypatch, nodes)
    b = EvdevBackend()
    assert b.scan() == []
    nodes["/dev/input/event3"][1] = "Late Keyboard"
    assert [i.name for i in b.scan()] == ["Late Keyboard"]
