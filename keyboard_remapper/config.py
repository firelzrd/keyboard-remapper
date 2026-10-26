"""Per-user configuration: presets, layout choices and UI state."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field

from . import layouts
from .mapping import Preset


# manual: the user's own (drag) order; keyboard: by key position; <column>-asc/desc: header clicks
SORT_MODES = ("manual", "keyboard", "trigger-asc", "trigger-desc", "action-asc", "action-desc")


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "keyboard-remapper")


def legacy_config_path() -> str:
    """Where this program kept its config before it was renamed from "Remapper"."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "remapper", "config.json")


def _size(value) -> str:
    """A saved layout size; sizes dropped since are mapped to the nearest one, unknown ones to "full"."""
    value = layouts.LEGACY_SIZES.get(value, value)
    return value if value in layouts.SIZE_IDS else "full"


@dataclass
class DeviceConfig:
    name: str = ""
    preset: Preset = field(default_factory=Preset)
    enabled: bool = True
    standard: str = "ansi"        # ansi | iso | jis
    size: str = "full"            # full | tkl | apple | apple-num

    def to_dict(self) -> dict:
        return {"name": self.name, "preset": self.preset.to_dict(), "enabled": self.enabled,
                "standard": self.standard, "size": self.size}

    @staticmethod
    def from_dict(d: dict) -> "DeviceConfig":
        return DeviceConfig(
            name=str(d.get("name", "")),
            preset=Preset.from_dict(d.get("preset", {})),
            enabled=bool(d.get("enabled", True)),
            standard=d.get("standard", "ansi") if d.get("standard") in ("ansi", "iso", "jis") else "ansi",
            size=_size(d.get("size", "full")),
        )


class Config:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "config.json")
        if path is None:
            self._migrate_legacy()
        self.devices: dict[str, DeviceConfig] = {}
        self.last_model: str = ""
        self.sort: str = "keyboard"          # list order, see SORT_MODES
        self.load()

    def _migrate_legacy(self) -> None:
        """Pick up the config of the old "Remapper" (copied, the old file is left alone)."""
        old = legacy_config_path()
        if os.path.exists(self.path) or not os.path.exists(old):
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            shutil.copy2(old, self.path)
        except OSError:
            pass

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self.last_model = str(data.get("last_model", ""))
        legacy = {"name": "trigger-asc", "added": "manual"}
        mode = legacy.get(data.get("sort"), data.get("sort"))
        if mode in SORT_MODES:
            self.sort = mode
        for model, d in data.get("devices", {}).items():
            try:
                self.devices[model] = DeviceConfig.from_dict(d)
            except (ValueError, TypeError, AttributeError):
                continue

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = {"version": 1, "last_model": self.last_model, "sort": self.sort,
                "devices": {m: d.to_dict() for m, d in self.devices.items()}}
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def device(self, model: str, name: str = "", default_standard: str = "ansi") -> DeviceConfig:
        d = self.devices.get(model)
        if d is None:
            d = DeviceConfig(name=name, standard=default_standard)
            self.devices[model] = d
        if name and not d.name:
            d.name = name
        return d


def system_standard() -> str:
    """Best guess at the physical layout from system keyboard settings / locale."""
    from .i18n import LANG
    xkb = os.environ.get("XKB_DEFAULT_LAYOUT")
    if not xkb:
        try:
            with open("/etc/default/keyboard") as f:
                for line in f:
                    if line.startswith("XKBLAYOUT="):
                        xkb = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
    return layouts.guess_standard(LANG, xkb)
