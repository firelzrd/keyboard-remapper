import asyncio

import pytest

from keyboard_remapper import keys
from keyboard_remapper.backend import FakeBackend, fake_keyboard
from keyboard_remapper.daemon import Daemon
from keyboard_remapper.ipc import Client


def code(n):
    return keys.name_to_code(n)


PRESET = {"name": "t", "mappings": [
    {"trigger": ["CTRL", "J"], "action": {"type": "key", "output": ["DOWN"]}},
    {"trigger": ["CAPSLOCK"], "action": {"type": "key", "output": ["LEFTCTRL"]}},
]}


async def make(tmp_path, nodes=None, **kw):
    b = FakeBackend(nodes if nodes is not None else fake_keyboard(0))
    d = Daemon(b, state_path=str(tmp_path / "state.json"), socket_path=str(tmp_path / "s.sock"),
               check_peer=False, **kw)
    await d.start()
    return b, d


def call(c, *a, **kw):
    return asyncio.get_running_loop().run_in_executor(None, lambda: c.request(*a, **kw))


@pytest.mark.asyncio
async def test_groups_and_single_output_device(tmp_path):
    b, d = await make(tmp_path)
    assert len(d.groups) == 1                      # keyboard + consumer node = one group
    g = next(iter(d.groups.values()))
    assert len(g.nodes) == 2
    await d.stop()


@pytest.mark.asyncio
async def test_apply_over_ipc_and_translate(tmp_path):
    b, d = await make(tmp_path)
    c = Client(str(tmp_path / "s.sock"))
    assert c.connect()
    assert (await call(c, "hello"))["ok"]
    r = await call(c, "apply", model="1234:5678", preset=PRESET)
    assert r["ok"]
    await asyncio.sleep(0.2)
    assert b.inputs["/dev/input/fake0a"].grabbed and b.inputs["/dev/input/fake0b"].grabbed
    h = b.inputs["/dev/input/fake0a"]
    h.inject(code("CAPSLOCK"), 1)
    h.inject(code("J"), 1)
    h.inject(code("J"), 0)
    h.inject(code("CAPSLOCK"), 0)
    log = [(keys.code_to_name(c_), v) for c_, v in b.outputs[0].log]
    # CapsLock is Ctrl, and Ctrl+J -> Down: the user gets a bare Down, Ctrl is hidden meanwhile
    assert log == [("LEFTCTRL", 1), ("LEFTCTRL", 0), ("DOWN", 1), ("DOWN", 0)]
    c.close()
    await d.stop()


@pytest.mark.asyncio
async def test_never_more_than_one_virtual_device(tmp_path):
    """The stutter regression: no matter what we do, no second output device appears."""
    b, d = await make(tmp_path, fake_keyboard(0) + fake_keyboard(1, "Other", 0x9, 0x9, False))
    c = Client(str(tmp_path / "s.sock"))
    c.connect()
    for _ in range(3):
        await call(c, "apply", model="1234:5678", preset=PRESET)
        await call(c, "apply", model="0009:0009", preset=PRESET)
        await call(c, "capture", model="1234:5678", on=True)
        await call(c, "capture", model="1234:5678", on=False)
        await call(c, "enable", model="1234:5678", enabled=False)
        await call(c, "enable", model="1234:5678", enabled=True)
        await call(c, "forget", model="0009:0009")
        await asyncio.sleep(0.1)
    b.unplug("/dev/input/fake1a")
    b.plug(fake_keyboard(1, "Other", 0x9, 0x9, False)[0])
    d.rescan()
    assert len(b.outputs) == 1 and not b.outputs[0].closed
    # events from both keyboards leave through the same device
    await call(c, "apply", model="0009:0009", preset=PRESET)
    await asyncio.sleep(0.1)
    b.inputs["/dev/input/fake0a"].inject(code("A"), 1)
    b.inputs["/dev/input/fake1a"].inject(code("B"), 1)
    names = [keys.code_to_name(x) for x, v in b.outputs[0].log if v == 1]
    assert "A" in names and "B" in names
    c.close()
    await d.stop()


@pytest.mark.asyncio
async def test_capture_blocks_forwarding_and_streams_keys(tmp_path):
    b, d = await make(tmp_path)
    events = []
    c = Client(str(tmp_path / "s.sock"), on_event=events.append)
    c.connect()
    await call(c, "monitor", on=True)
    await call(c, "capture", model="1234:5678", on=True)
    await asyncio.sleep(0.1)
    h = b.inputs["/dev/input/fake0a"]
    assert h.grabbed
    h.inject(code("A"), 1)
    h.inject(code("A"), 0)
    await asyncio.sleep(0.1)
    assert b.outputs[0].log == []
    assert [x for x in events if x.get("event") == "key" and x["captured"]]
    await call(c, "capture", model="1234:5678", on=False)
    await asyncio.sleep(0.1)
    assert not h.grabbed                         # no preset -> released again
    c.close()
    await d.stop()


@pytest.mark.asyncio
async def test_capture_released_when_client_disconnects(tmp_path):
    b, d = await make(tmp_path)
    c = Client(str(tmp_path / "s.sock"))
    c.connect()
    await call(c, "capture", model="1234:5678", on=True)
    await asyncio.sleep(0.1)
    assert b.inputs["/dev/input/fake0a"].grabbed
    c.close()
    await asyncio.sleep(0.2)
    assert not b.inputs["/dev/input/fake0a"].grabbed
    await d.stop()


@pytest.mark.asyncio
async def test_grab_waits_for_keys_to_be_released(tmp_path):
    b, d = await make(tmp_path)
    h = b.inputs["/dev/input/fake0a"]
    h.inject(code("ENTER"), 1)                   # user is holding Enter (e.g. clicked via keyboard)
    d.presets["1234:5678"] = {"preset": PRESET, "enabled": True}
    d._reconfigure("1234:5678")
    await asyncio.sleep(0.15)
    assert not h.grabbed
    h.inject(code("ENTER"), 0)
    await asyncio.sleep(0.15)
    assert h.grabbed
    await d.stop()


@pytest.mark.asyncio
async def test_state_persists_and_applies_on_hotplug(tmp_path):
    b, d = await make(tmp_path)
    c = Client(str(tmp_path / "s.sock"))
    c.connect()
    await call(c, "apply", model="1234:5678", preset=PRESET)
    c.close()
    await d.stop()
    # new daemon instance (reboot) with the keyboard attached
    b2, d2 = await make(tmp_path)
    await asyncio.sleep(0.2)
    g = next(iter(d2.groups.values()))
    assert g.engine is not None and g.grabbed
    await d2.stop()


@pytest.mark.asyncio
async def test_unplug_releases_held_outputs(tmp_path):
    b, d = await make(tmp_path)
    c = Client(str(tmp_path / "s.sock"))
    c.connect()
    await call(c, "apply", model="1234:5678", preset=PRESET)
    await asyncio.sleep(0.1)
    h = b.inputs["/dev/input/fake0a"]
    h.inject(code("A"), 1)
    b.unplug("/dev/input/fake0a")
    b.unplug("/dev/input/fake0b")
    d.rescan()
    assert not d.groups
    assert b.outputs[0].log[-1] == (code("A"), 0)
    c.close()
    await d.stop()


@pytest.mark.asyncio
async def test_bad_preset_rejected(tmp_path):
    b, d = await make(tmp_path)
    c = Client(str(tmp_path / "s.sock"))
    c.connect()
    r = await call(c, "apply", model="1234:5678",
                   preset={"mappings": [{"trigger": ["NOPE"], "action": {"type": "key", "output": ["A"]}}]})
    assert not r["ok"]
    c.close()
    await d.stop()


@pytest.mark.asyncio
async def test_output_monitor_shows_what_is_sent(tmp_path):
    b, d = await make(tmp_path)
    events = []
    c = Client(str(tmp_path / "s.sock"), on_event=events.append)
    c.connect()
    pre = {"mappings": [{"trigger": ["LEFTCTRL"], "action": {"type": "disable"}},
                        {"trigger": ["CTRL", "SPACE"], "action": {"type": "key", "output": ["ZENKAKUHANKAKU"]}}]}
    await call(c, "apply", model="1234:5678", preset=pre)
    await call(c, "monitor", on=True, output=True)
    await asyncio.sleep(0.2)
    h = b.inputs["/dev/input/fake0a"]
    for n, v in (("LEFTCTRL", 1), ("SPACE", 1), ("SPACE", 0), ("LEFTCTRL", 0)):
        h.inject(code(n), v)
    await asyncio.sleep(0.2)
    out = [(keys.code_to_name(e_["code"]), e_["value"]) for e_ in events if e_.get("event") == "out"]
    assert out == [("ZENKAKUHANKAKU", 1), ("ZENKAKUHANKAKU", 0)]
    c.close()
    await d.stop()
