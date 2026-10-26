"""Settings written by the program's old name ("Remapper") are carried over."""

import json
import os

import pytest

from keyboard_remapper import backend, config, daemon


def test_config_copied_from_old_location(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    old = tmp_path / "remapper"
    old.mkdir()
    (old / "config.json").write_text(json.dumps({"version": 1, "last_model": "1234:5678", "devices": {
        "1234:5678": {"name": "Kbd", "preset": {"mappings": [
            {"trigger": ["CAPSLOCK"], "action": {"type": "key", "output": ["LEFTCTRL"]}}]}}}}))
    cfg = config.Config()
    assert cfg.path == str(tmp_path / "keyboard-remapper" / "config.json")
    assert cfg.devices["1234:5678"].preset.find(("CAPSLOCK",))
    assert (old / "config.json").exists()                      # the old file is left alone


def test_existing_new_config_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for d, last in (("remapper", "old"), ("keyboard-remapper", "new")):
        (tmp_path / d).mkdir()
        (tmp_path / d / "config.json").write_text(json.dumps({"last_model": last}))
    assert config.Config().last_model == "new"


@pytest.mark.asyncio
async def test_daemon_state_copied_from_old_location(tmp_path, monkeypatch):
    legacy = tmp_path / "old" / "state.json"
    new = tmp_path / "new" / "state.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"models": {"1234:5678": {"enabled": True, "preset": {"mappings": []}}}}))
    monkeypatch.setattr(daemon, "LEGACY_STATE", str(legacy))
    monkeypatch.setattr(daemon, "DEFAULT_STATE", str(new))
    d = daemon.Daemon(backend.FakeBackend([]), state_path=str(new), socket_path=None, check_peer=False)
    await d.start()
    assert "1234:5678" in d.presets and os.path.exists(new)
    await d.stop()


def test_old_virtual_device_is_still_recognised():
    assert "Remapper virtual keyboard" in backend.LEGACY_VIRTUAL_NAMES
    assert backend.VIRTUAL_NAME not in backend.LEGACY_VIRTUAL_NAMES
